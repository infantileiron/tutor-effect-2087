"""端到端集成：FastAPI + 真实 worker 循环（线程内）+ 假 Redis。
验证建包入队后 worker 自动拾取、整包完成、发布、下载全链路，
以及 worker 启动时对 running 中断任务的回收。"""
import os,time,tempfile,threading
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

_DB=os.path.join(tempfile.gettempdir(),'tutor_integration.sqlite')
os.environ['DATABASE_URL']=f'sqlite:///{_DB}'
os.environ.setdefault('REDIS_URL','redis://unused:6379/0')
os.environ.setdefault('JWT_SECRET','integration-secret')
os.environ.setdefault('SEED_DEMO','false')

from src.config.database import Base,SessionLocal
from src.models.entities import Student,Plan,User,JointPackage
from src.utils.security import hash_password
import src.services.reports as reports_svc
import src.services.joint_packages as joint_svc
import src.worker as worker_module
import src.main as main_module

class FakeRedis:
    """最小 Redis 协议替身：LPUSH 入头、BLPOP 出头，支持超时唤醒。"""
    def __init__(self):
        self.lists={};self.lock=threading.Condition()
    def lpush(self,key,value):
        with self.lock:
            self.lists.setdefault(key,[]).insert(0,str(value).encode())
            self.lock.notify_all()
    def blpop(self,keys,timeout=0):
        keys=[keys] if isinstance(keys,str) else keys
        deadline=time.time()+timeout
        with self.lock:
            while True:
                for k in keys:
                    if self.lists.get(k):
                        return (k.encode(),self.lists[k].pop(0))
                remaining=deadline-time.time()
                if remaining<=0: return None
                self.lock.wait(min(0.2,remaining))
    def brpop(self,key,timeout=0):
        with self.lock:
            deadline=time.time()+timeout
            while not self.lists.get(key):
                if time.time()>=deadline: return None
                self.lock.wait(0.2)
            return (key.encode(),self.lists[key].pop())
    def ping(self): return True

@pytest.fixture(scope='session')
def worker():
    fake=FakeRedis()
    # 三个模块共享同一假队列，worker 线程全程唯一消费者
    reports_svc.queue=fake;joint_svc.queue=fake;worker_module.queue=fake
    t=threading.Thread(target=worker_module.main,daemon=True)
    t.start()
    yield fake

@pytest.fixture
def client(worker):
    Base.metadata.drop_all(main_module.engine);Base.metadata.create_all(main_module.engine)
    with SessionLocal() as db:
        db.add_all([User(email='admin@demo.local',role='admin',password_hash=hash_password('Demo123!')),
                    User(email='analyst@demo.local',role='analyst',password_hash=hash_password('Demo123!'))])
        for i in range(6):
            db.add(Student(code=f'C-{i}',name=f'对照{i}',campus='城东',group='control',score=70.0+i,absent=False))
            db.add(Student(code=f'T-{i}',name=f'干预{i}',campus='城东',group='intervention',score=83.0+i,absent=False))
        db.add_all([Plan(title='集成方案A',campus='城东',exclude_absent=True,description=''),
                    Plan(title='集成方案B',campus='城东',exclude_absent=True,description='')])
        db.commit()
    with TestClient(main_module.app) as c:
        yield c

def _token(c,email):
    return c.post('/auth/login',json={'email':email,'password':'Demo123!'}).json()['access_token']
def _auth(t): return {'Authorization':f'Bearer {t}'}

def _wait(c,token,pkg_id,want,timeout=15):
    deadline=time.time()+timeout
    while time.time()<deadline:
        r=c.get(f'/joint-packages/{pkg_id}',headers=_auth(token))
        if r.json()['status']==want: return r.json()
        time.sleep(0.2)
    raise AssertionError(f'package did not reach {want}: {r.json()["status"]}')

def test_worker_picks_up_package_and_full_publish_flow(client):
    analyst=_token(client,'analyst@demo.local');admin=_token(client,'admin@demo.local')
    plans=client.get('/plans',headers=_auth(analyst)).json()
    ids=sorted(p['id'] for p in plans)[-2:]
    r=client.post('/joint-packages',json={'title':'端到端联合包','plan_ids':ids},headers=_auth(analyst))
    assert r.status_code==202
    pkg_id=r.json()['id']
    # worker 线程应自动拾取并完成，无需任何手动调用
    detail=_wait(client,analyst,pkg_id,'completed')
    assert len(detail['items'])==2
    assert all(it['status']=='completed' for it in detail['items'])
    assert all(it['holm_adjusted_p'] is not None for it in detail['items'])
    # 未发布不能下载
    assert client.get(f'/joint-packages/{pkg_id}/export',headers=_auth(analyst)).status_code==409
    # 分析员不能发布
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包联合结论','published':True},headers=_auth(analyst))
    assert r.status_code==403
    # 负责人一次性发布
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包联合结论','published':True},headers=_auth(admin))
    assert r.status_code==200 and r.json()['status']=='published'
    exported=client.get(f'/joint-packages/{pkg_id}/export',headers=_auth(admin)).json()
    assert exported['correction_method'].startswith('Holm')
    assert len(exported['items'])==2
    # 独立报告流程仍可用
    r=client.post('/reports',json={'plan_id':ids[0]},headers=_auth(analyst))
    rid=r.json()['id']
    deadline=time.time()+10
    while time.time()<deadline:
        if client.get(f'/reports/{rid}',headers=_auth(analyst)).json()['status']=='completed': break
        time.sleep(0.2)
    assert client.get(f'/reports/{rid}/export',headers=_auth(analyst)).status_code==200

def test_worker_startup_reclaim_interrupted_package(client,monkeypatch):
    analyst=_token(client,'analyst@demo.local')
    plans=client.get('/plans',headers=_auth(analyst)).json()
    ids=sorted(p['id'] for p in plans)[-2:]
    r=client.post('/joint-packages',json={'title':'中断联合包','plan_ids':ids},headers=_auth(analyst))
    pkg_id=r.json()['id']
    _wait(client,analyst,pkg_id,'completed')
    # 模拟新进程启动前的中断残留：直接改库为 running
    with SessionLocal() as db:
        pkg=db.get(JointPackage,pkg_id);pkg.status='running';db.commit()
    # 新 worker 实例的启动回收（模块内 reclaimed 标志重置）
    monkeypatch.setattr(worker_module,'reclaimed',False,raising=False)
    import src.services.processing as processing
    with SessionLocal() as db:
        recovered=processing.reclaim_stale(db)
    assert ('joint_package',pkg_id) in recovered
    # 回收后队列扫描兜底：下一轮 worker 循环自动完成
    detail=_wait(client,analyst,pkg_id,'completed')
    assert detail['status']=='completed'
