import os,json
from datetime import datetime,timezone
from sqlalchemy import select
from fastapi import HTTPException
import redis
from src.models.entities import JointPackage,JointPackageItem,Plan,Student,Report
from src.constants.enums import FAMILY_ALPHA,PACKAGE_STATUSES

queue=redis.Redis.from_url(os.environ['REDIS_URL'])
QUEUE_KEY='tutor:joint_packages'

def _now(): return datetime.now(timezone.utc).isoformat()

def list_packages(db):
    return db.scalars(select(JointPackage).order_by(JointPackage.id.desc())).all()

def get_package(db,package_id):
    package=db.get(JointPackage,package_id)
    if not package: raise HTTPException(404,'联合检验包不存在')
    return package

def get_items(db,package_id):
    return db.scalars(select(JointPackageItem).where(JointPackageItem.package_id==package_id).order_by(JointPackageItem.id)).all()

def create_package(db,data,user):
    plan_ids=data.plan_ids
    if len(plan_ids)<2: raise HTTPException(422,'联合检验包至少选择 2 个方案')
    if len(set(plan_ids))!=len(plan_ids): raise HTTPException(422,'同一检验包内方案不能重复，请去掉重复方案')
    plans=[]
    for plan_id in plan_ids:
        plan=db.get(Plan,plan_id)
        if not plan: raise HTTPException(404,f'方案 {plan_id} 不存在')
        plans.append(plan)
    # 同一时点样本快照：建包瞬间的全量学员成绩，后续修订不影响本包
    students=db.scalars(select(Student).order_by(Student.code)).all()
    student_snapshot=[{'code':s.code,'name':s.name,'campus':s.campus,'group':s.group,
                       'score':s.score,'absent':s.absent} for s in students]
    now=_now()
    package=JointPackage(title=data.title,status='queued',alpha=FAMILY_ALPHA,
                         plan_snapshots={str(p.id):{'id':p.id,'title':p.title,'campus':p.campus,
                                                    'exclude_absent':p.exclude_absent,
                                                    'description':p.description} for p in plans},
                         created_at=now)
    db.add(package);db.flush()
    for plan in plans:
        db.add(JointPackageItem(package_id=package.id,plan_id=plan.id,plan_title=plan.title,
                                status='queued',student_snapshot=student_snapshot,attempts=0,
                                created_at=now))
    db.commit();db.refresh(package)
    queue.lpush(QUEUE_KEY,package.id)
    return package

def retry_package(db,package_id,user):
    """失败后沿原包恢复：不新建包、不新建报告，仅把失败/中断项重新入队。"""
    package=get_package(db,package_id)
    if package.status=='published': raise HTTPException(409,'整包已发布，不能重试')
    if package.status in ('queued','running'): raise HTTPException(409,'检验包仍在计算中，请等待当前轮次结束')
    items=get_items(db,package.id)
    if package.status=='completed':
        # 待发布包无需重试
        raise HTTPException(409,'检验包已计算完成，等待签核发布')
    stale=[i for i in items if i.status in ('queued','running','failed')]
    if not stale: raise HTTPException(409,'没有需要恢复的检验项')
    package.status='queued';package.error=''
    for item in stale:
        item.status='queued';item.error=''
    db.commit()
    queue.lpush(QUEUE_KEY,package.id)
    db.refresh(package)
    return package

def save_package_conclusion(db,package_id,data,user):
    package=get_package(db,package_id)
    if package.published and user.role!='admin':
        raise HTTPException(403,'已发布检验包仅管理员可更改')
    if data.published:
        if user.role!='admin': raise HTTPException(403,'仅管理员可整包签核发布')
        if package.status!='completed':
            raise HTTPException(409,'整包全部检验项成功并完成 Holm 校正后才能发布')
        package.published=True
        package.status='published'
        package.published_at=_now()
    else:
        if package.status not in ('completed','published'):
            raise HTTPException(409,'检验包计算完成后才能起草结论')
        if package.published and user.role!='admin':
            raise HTTPException(403,'已发布检验包仅管理员可更改')
    package.conclusion=data.conclusion
    db.commit();db.refresh(package)
    return package

def export_package(db,package_id):
    package=get_package(db,package_id)
    if package.status!='published' or not package.published:
        raise HTTPException(409,'整包签核发布后才能下载联合检验包')
    items=get_items(db,package.id)
    return {
        'joint_package_id':package.id,
        'title':package.title,
        'status':package.status,
        'family_alpha':package.alpha,
        'correction_method':'Holm 逐步降序校正（族系整体误报率 5%）',
        'created_at':package.created_at,
        'published_at':package.published_at,
        'conclusion':package.conclusion,
        'plan_snapshots':package.plan_snapshots,
        'package_summary':package.result,
        'items':[{'item_id':i.id,'plan_id':i.plan_id,'plan_title':i.plan_title,
                  'status':i.status,'attempts':i.attempts,'error':i.error,
                  'raw_p_value':i.raw_p_value,'holm_rank':i.holm_rank,
                  'holm_adjusted_p':i.holm_adjusted_p,'holm_significant':i.holm_significant,
                  'statistics':i.result} for i in items],
    }
