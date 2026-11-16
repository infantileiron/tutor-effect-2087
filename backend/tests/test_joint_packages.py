"""联合检验包后端验收测试（SQLite 内存库，无需 Redis/Postgres 服务）。
覆盖：Holm 校正、重复方案拒绝、失败项保留与原包恢复、发布中断回收、
封存快照与后续修订隔离、权限控制、独立报告保留。"""
import os
import types
import tempfile
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

_DB_PATH=os.path.join(tempfile.gettempdir(),'tutor_joint_test.sqlite')
os.environ['DATABASE_URL']=f'sqlite:///{_DB_PATH}'
os.environ.setdefault('REDIS_URL','redis://unused:6379/0')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('SEED_DEMO','false')

from src.config.database import Base,engine as app_engine,SessionLocal as AppSession
from src.models import entities
from src.models.entities import Student,Plan,JointPackage,JointPackageItem,Report,User
from src.services import processing,joint_packages as js
from src.services.statistics import holm_adjust
from src.schemas.business import JointPackageInput
from src.utils.security import hash_password
import src.services.reports as reports_svc
import src.main as main_module

class FakeRedis:
    def __init__(self): self.items=[]
    def lpush(self,k,v): self.items.append((k,v))
    def blpop(self,keys,timeout=0): return None
    def ping(self): return True

@pytest.fixture
def db(monkeypatch):
    Base.metadata.drop_all(app_engine)
    Base.metadata.create_all(app_engine)
    session=AppSession()
    fake=FakeRedis()
    monkeypatch.setattr(js,'queue',fake)
    monkeypatch.setattr(reports_svc,'queue',fake)
    yield session
    session.close()

def _students(db,campus='城东',base_n=6):
    rows=[]
    # 对照组与干预组各 6 条，干预组均分更高
    for i in range(base_n):
        rows.append(Student(code=f'C-{campus}-{i}',name=f'对照{i}',campus=campus,
                            group='control',score=70.0+i,absent=False))
    for i in range(base_n):
        rows.append(Student(code=f'T-{campus}-{i}',name=f'干预{i}',campus=campus,
                            group='intervention',score=82.0+i,absent=False))
    db.add_all(rows);db.commit()
    return rows

def _plan(db,title,campus='城东',exclude_absent=True):
    p=Plan(title=title,campus=campus,exclude_absent=exclude_absent,description='测试方案')
    db.add(p);db.commit();db.refresh(p);return p

def _make_package(db,plan_ids,title='联合检验包'):
    data=JointPackageInput(title=title,plan_ids=plan_ids)
    user=types.SimpleNamespace(role='analyst',email='analyst@demo.local')
    return js.create_package(db,data,user)

# ---------- Holm 校正数学性质 ----------
def test_holm_known_values():
    out=holm_adjust([0.01,0.04,0.03],0.05)
    ranks=[o['rank'] for o in out]
    assert ranks==[1,3,2]
    # 调整 p：.01*3=.03；.03*2=.06；.04*1=.04，但单调化后第3位=max(.06,.04)=.06
    assert out[0]['adjusted_p']==pytest.approx(0.03)
    assert out[1]['adjusted_p']==pytest.approx(0.06)
    assert out[2]['adjusted_p']==pytest.approx(0.06)
    # 仅最小 p 拒绝（.01<=.0167），.03>.025 停止，后续均不拒绝
    assert [o['significant'] for o in out]==[True,False,False]

def test_holm_keeps_missing_slots():
    out=holm_adjust([0.01,None,0.02],0.05)
    assert out[1] is None
    assert out[0]['rank']==1 and out[2]['rank']==2
    assert out[0]['significant'] is True

def test_holm_all_significant_when_tiny_p():
    out=holm_adjust([0.001,0.001,0.001],0.05)
    assert all(o['significant'] for o in out)

# ---------- 建包与重复方案 ----------
def test_duplicate_plans_rejected(db):
    _students(db)
    p=_plan(db,'方案A')
    with pytest.raises(Exception) as ei:
        JointPackageInput(title='联合包',plan_ids=[p.id,p.id])
    assert '重复' in str(ei.value)
    user=types.SimpleNamespace(role='analyst')
    data=JointPackageInput.model_construct(title='联合包',plan_ids=[p.id,p.id])
    # 服务层同样拦截
    with pytest.raises(Exception):
        js.create_package(db,data,user)

def test_create_package_seals_snapshot_and_plans(db):
    _students(db)
    p1=_plan(db,'方案A');p2=_plan(db,'方案B')
    pkg=_make_package(db,[p1.id,p2.id])
    assert pkg.status=='queued'
    items=js.get_items(db,pkg.id)
    assert len(items)==2
    assert {i.plan_id for i in items}=={p1.id,p2.id}
    # 同一时点样本快照：全量且含当时成绩
    assert all(len(i.student_snapshot)==12 for i in items)
    assert set(pkg.plan_snapshots.keys())=={str(p1.id),str(p2.id)}
    # 入队通知
    assert js.queue.items and js.queue.items[-1][1]==pkg.id

# ---------- 整包成功路径与 Holm 落库 ----------
def test_full_success_and_holm_stored(db):
    _students(db)
    p1=_plan(db,'方案A');p2=_plan(db,'方案B')
    pkg=_make_package(db,[p1.id,p2.id])
    processing.claim_joint_package(db)
    db.refresh(pkg)
    assert pkg.status=='completed'
    items=js.get_items(db,pkg.id)
    assert all(i.status=='completed' for i in items)
    assert all(i.raw_p_value is not None and i.holm_adjusted_p is not None for i in items)
    ranks=sorted(i.holm_rank for i in items)
    assert ranks==[1,2]
    assert pkg.result['family_size']==2
    assert pkg.result['correction'].startswith('Holm')
    # 每项保留完整 Welch 统计与样本快照
    assert all(i.result and 'sample_snapshot' in i.result for i in items)

# ---------- 失败项保留、整包失败不删项 ----------
def test_failed_item_kept_and_package_failed(db,monkeypatch):
    _students(db,campus='城东')
    good=_plan(db,'有效方案')
    # 滨江无任何样本 → 每组 0 个有效成绩
    bad=_plan(db,'缺样本方案',campus='滨江')
    pkg=_make_package(db,[good.id,bad.id])
    processing.claim_joint_package(db)
    db.refresh(pkg)
    assert pkg.status=='failed'
    items=js.get_items(db,pkg.id)
    assert len(items)==2  # 失败项不删除
    by_plan={i.plan_id:i for i in items}
    assert by_plan[good.id].status=='completed'
    assert by_plan[bad.id].status=='failed'
    assert '每组至少需要' in by_plan[bad.id].error
    assert by_plan[bad.id].attempts==1
    # 整包失败时不产生 Holm 结果
    assert by_plan[bad.id].holm_adjusted_p is None
    assert pkg.result['failed_item_ids']==[by_plan[bad.id].id]

# ---------- 失败后沿原包恢复：重试不重复建报告 ----------
def test_retry_reuses_package_and_completed_items(db,monkeypatch):
    _students(db)
    good=_plan(db,'有效方案')
    bad=_plan(db,'缺样本方案',campus='滨江')
    pkg=_make_package(db,[good.id,bad.id])
    processing.claim_joint_package(db)
    db.refresh(pkg)
    assert pkg.status=='failed'
    item_ids_before={i.id for i in js.get_items(db,pkg.id)}
    report_count_before=db.scalar(select(func.count()).select_from(Report))

    # 让重算在本轮成功：给滨江补样本（封存快照不变，故通过让 bad 方案口径改为城东模拟修复）
    # 真实修复路径是封存包不可改样本——这里验证重试机制本身：成功项不重算、失败项 attempts 增加
    user=types.SimpleNamespace(role='analyst')
    js.retry_package(db,pkg.id,user)
    db.refresh(pkg)
    assert pkg.status=='queued'
    items=js.get_items(db,pkg.id)
    assert {i.id for i in items}==item_ids_before  # 没有新建项
    good_item=next(i for i in items if i.plan_id==good.id)
    bad_item=next(i for i in items if i.plan_id==bad.id)
    assert good_item.status=='completed'  # 成功项保持
    assert bad_item.status=='queued'      # 失败项重新排队
    processing.claim_joint_package(db)
    db.refresh(pkg)
    items=js.get_items(db,pkg.id)
    good_item=next(i for i in items if i.plan_id==good.id)
    bad_item=next(i for i in items if i.plan_id==bad.id)
    assert good_item.attempts==1  # 成功项未重复计算
    assert bad_item.attempts==2   # 失败项沿原包重试
    assert pkg.status=='failed'   # 封存样本未变，仍失败但项保留
    report_count_after=db.scalar(select(func.count()).select_from(Report))
    assert report_count_after==report_count_before  # 全程不产生独立报告

def test_retry_success_after_snapshot_fix_via_new_data_then_reclaim(db):
    """补录数据后建的新包可成功；旧失败包保持原封存口径不变。"""
    _students(db)
    bad=_plan(db,'滨江方案',campus='滨江')
    good=_plan(db,'城东方案')
    old=_make_package(db,[good.id,bad.id],title='旧包')
    processing.claim_joint_package(db)
    db.refresh(old)
    assert old.status=='failed'
    old_snapshot=js.get_items(db,old.id)[0].student_snapshot
    # 后续成绩修订
    db.add_all([Student(code='C-BIN-0',name='x',campus='滨江',group='control',score=70.0,absent=False),
                Student(code='C-BIN-1',name='y',campus='滨江',group='control',score=71.0,absent=False),
                Student(code='T-BIN-0',name='z',campus='滨江',group='intervention',score=80.0,absent=False),
                Student(code='T-BIN-1',name='w',campus='滨江',group='intervention',score=81.0,absent=False)])
    db.commit()
    new=_make_package(db,[good.id,bad.id],title='新包')
    processing.claim_joint_package(db)
    db.refresh(new)
    assert new.status=='completed'
    # 旧包封存样本不变
    assert js.get_items(db,old.id)[0].student_snapshot==old_snapshot

# ---------- 发布中断：running 回收 ----------
def test_reclaim_stale_running_package(db):
    _students(db)
    p1=_plan(db,'方案A');p2=_plan(db,'方案B')
    pkg=_make_package(db,[p1.id,p2.id])
    # 模拟进程中断：包停在 running，第一项 running、第二项已真实算出结果
    pkg.status='running';db.commit()
    items=js.get_items(db,pkg.id)
    items[0].status='running';db.commit()
    plan_snapshot=pkg.plan_snapshots[str(items[1].plan_id)]
    real=processing.welch_from_snapshot(items[1].student_snapshot,plan_snapshot)
    items[1].status='completed';items[1].result=real;items[1].raw_p_value=real['p_value'];items[1].attempts=1
    db.commit()
    recovered=processing.reclaim_stale(db)
    assert ('joint_package',pkg.id) in recovered
    db.refresh(pkg)
    assert pkg.status=='queued'
    items=js.get_items(db,pkg.id)
    assert items[0].status=='queued' and items[1].status=='completed'
    # 回收后轮次完成，completed 项不重算
    processing.claim_joint_package(db)
    db.refresh(pkg)
    assert pkg.status=='completed'
    items=js.get_items(db,pkg.id)
    assert items[1].attempts==1          # 完成项未被重复执行
    assert items[0].attempts==1          # 中断项重新计算一次
    assert all(i.holm_adjusted_p is not None for i in items)

# ---------- 封存快照与修订并发不混版 ----------
def test_snapshot_sealed_against_later_edits(db):
    _students(db)
    p1=_plan(db,'方案A');p2=_plan(db,'方案B')
    pkg=_make_package(db,[p1.id,p2.id])
    processing.claim_joint_package(db)
    db.refresh(pkg)
    before={i.plan_id:i.result['checksum'] for i in js.get_items(db,pkg.id)}
    # 修订成绩与方案口径
    for s in db.scalars(select(Student)).all(): s.score=99.0
    p1.campus='滨江';p1.exclude_absent=False
    db.commit()
    # 用封存快照重算，结果必须与首算一致
    for item in js.get_items(db,pkg.id):
        again=processing.welch_from_snapshot(item.student_snapshot,pkg.plan_snapshots[str(item.plan_id)])
        assert again['checksum']==before[item.plan_id]

# ---------- 权限与发布流程（API 层） ----------
@pytest.fixture
def client(db,monkeypatch):
    monkeypatch.setattr(js,'queue',FakeRedis())
    monkeypatch.setattr(reports_svc,'queue',FakeRedis())
    with TestClient(main_module.app) as c:
        admin=User(email='admin@demo.local',role='admin',password_hash=hash_password('Demo123!'))
        analyst=User(email='analyst@demo.local',role='analyst',password_hash=hash_password('Demo123!'))
        viewer=User(email='viewer@demo.local',role='viewer',password_hash=hash_password('Demo123!'))
        db.add_all([admin,analyst,viewer]);db.commit()
        yield c

def _token(client,email):
    r=client.post('/auth/login',json={'email':email,'password':'Demo123!'})
    return r.json()['access_token']

def _auth(t): return {'Authorization':f'Bearer {t}'}

def test_api_permissions_and_publish_flow(client,db):
    _students(db)
    p1=_plan(db,'方案A');p2=_plan(db,'方案B')
    admin=_token(client,'admin@demo.local')
    analyst=_token(client,'analyst@demo.local')
    viewer=_token(client,'viewer@demo.local')
    # viewer 不能建包
    r=client.post('/joint-packages',json={'title':'权限包','plan_ids':[p1.id,p2.id]},headers=_auth(viewer))
    assert r.status_code==403
    # analyst 建包
    r=client.post('/joint-packages',json={'title':'权限包','plan_ids':[p1.id,p2.id]},headers=_auth(analyst))
    assert r.status_code==202
    pkg_id=r.json()['id']
    processing.claim_joint_package(db)
    # 进度查询对所有成员开放
    r=client.get(f'/joint-packages/{pkg_id}',headers=_auth(viewer))
    assert r.status_code==200 and r.json()['status']=='completed'
    # viewer 不能签核
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包结论内容','published':True},headers=_auth(viewer))
    assert r.status_code==403
    # analyst 不能发布
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包结论内容','published':True},headers=_auth(analyst))
    assert r.status_code==403
    # 未发布不能导出
    r=client.get(f'/joint-packages/{pkg_id}/export',headers=_auth(analyst))
    assert r.status_code==409
    # analyst 可先起草（不发布）
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包结论内容','published':False},headers=_auth(analyst))
    assert r.status_code==200
    # admin 一次性整包签核发布
    r=client.patch(f'/joint-packages/{pkg_id}/conclusion',
                   json={'conclusion':'整包结论内容','published':True},headers=_auth(admin))
    assert r.status_code==200 and r.json()['status']=='published'
    # 发布后才可下载，且包含逐项原始与校正结论
    r=client.get(f'/joint-packages/{pkg_id}/export',headers=_auth(viewer))
    assert r.status_code==200
    body=r.json()
    assert len(body['items'])==2
    assert all('raw_p_value' in it and 'holm_adjusted_p' in it for it in body['items'])
    assert body['correction_method'].startswith('Holm')

def test_api_retry_endpoint_and_duplicate_validation(client,db):
    _students(db)
    good=_plan(db,'有效')
    bad=_plan(db,'缺样本',campus='滨江')
    analyst=_token(client,'analyst@demo.local')
    r=client.post('/joint-packages',json={'title':'重复包','plan_ids':[good.id,good.id]},headers=_auth(analyst))
    assert r.status_code==422
    r=client.post('/joint-packages',json={'title':'失败包','plan_ids':[good.id,bad.id]},headers=_auth(analyst))
    pkg_id=r.json()['id']
    processing.claim_joint_package(db)
    r=client.post(f'/joint-packages/{pkg_id}/retry',headers=_auth(analyst))
    assert r.status_code==202 and r.json()['status']=='queued'
    # 计算中不能重复重试
    r=client.post(f'/joint-packages/{pkg_id}/retry',headers=_auth(analyst))
    assert r.status_code==409

def test_standalone_reports_remain(client,db):
    """原有独立报告流程保留且不受联合包影响。"""
    _students(db)
    p=_plan(db,'独立方案')
    analyst=_token(client,'analyst@demo.local')
    r=client.post('/reports',json={'plan_id':p.id},headers=_auth(analyst))
    assert r.status_code==202
    processing.claim_report(db)
    rid=r.json()['id']
    r=client.get(f'/reports/{rid}',headers=_auth(analyst))
    assert r.json()['status']=='completed'
    r=client.get(f'/reports/{rid}/export',headers=_auth(analyst))
    assert r.status_code==200 and 'statistics' in r.json()
