"""后台统计处理：独立报告与联合检验包。
纯数据库驱动、可单测；worker 仅负责唤醒与调用。
失败项保留不删除、重试不新建任何报告；中断的 running 任务由 reclaim_stale 回收。"""
from sqlalchemy import select
from src.models.entities import Report,Plan,Student,JointPackage,JointPackageItem
from src.services.statistics import welch,welch_from_snapshot,holm_adjust

def _locked(db,stmt):
    # PostgreSQL 行级跳过锁定；SQLite 等测试方言不支持时降级为普通查询
    if db.bind.dialect.name=='postgresql':
        return stmt.with_for_update(skip_locked=True)
    return stmt

def process_report(db,task):
    task.status='running';db.commit()
    try:
        plan=db.get(Plan,task.plan_id)
        task.result=welch(db.scalars(select(Student).order_by(Student.code)).all(),plan)
        task.status='completed'
    except Exception as e:
        task.error=str(e);task.status='failed'
    db.commit()
    return task

def claim_report(db):
    task=db.scalar(_locked(db,select(Report).where(Report.status=='queued').order_by(Report.id)))
    if task: process_report(db,task)
    return task

def process_joint_package(db,package):
    """按封存样本逐项重算并做 Holm 校正；整包任一失败则整包失败、项保留。"""
    if package.status not in ('queued',):
        return package
    package.status='running';package.error=''
    db.commit()
    items=db.scalars(_locked(db,select(JointPackageItem).where(JointPackageItem.package_id==package.id)
                     .order_by(JointPackageItem.id))).all()
    for item in items:
        if item.status=='completed':
            continue  # 重试轮次：成功项不重复计算
        item.status='running';item.error='';item.attempts=(item.attempts or 0)+1
        db.commit()
        try:
            plan_snapshot=package.plan_snapshots[str(item.plan_id)]
            result=welch_from_snapshot(item.student_snapshot,plan_snapshot)
            item.result=result
            item.raw_p_value=result['p_value']
            item.status='completed'
        except Exception as e:
            item.error=str(e);item.status='failed'
            item.holm_adjusted_p=None;item.holm_rank=None;item.holm_significant=None
        db.commit()
    db.refresh(package)
    items=db.scalars(select(JointPackageItem).where(JointPackageItem.package_id==package.id)
                     .order_by(JointPackageItem.id)).all()
    failed=[i for i in items if i.status!='completed']
    if failed:
        package.status='failed'
        package.error='整包失败：%d 个检验项未通过（缺样本或方差为零），失败项已保留。中断/瞬时故障可沿原包重试；封存样本不可变，数据口径问题请修订成绩或方案后新建检验包。'%len(failed)
        package.result={'completed_count':len(items)-len(failed),'total_count':len(items),
                        'failed_item_ids':[i.id for i in failed],
                        'failed_plan_titles':[i.plan_title for i in failed]}
        db.commit()
        return package
    # 全部成功：对整族原始 p 值做 Holm 校正（整体 5% 误报率）
    p_values=[i.raw_p_value for i in items]
    if any(p is None for p in p_values):
        # 防御：标记完成但缺 p 值（如历史中断残留），回退重算该项而非生成错误校正
        for item in items:
            if item.raw_p_value is None: item.status='queued'
        db.commit()
        return process_joint_package(db,package)
    holm=holm_adjust(p_values,alpha=package.alpha or 0.05)
    for item,h in zip(items,holm):
        item.holm_rank=h['rank']
        item.holm_adjusted_p=h['adjusted_p']
        item.holm_significant=h['significant']
    package.result={
        'family_size':len(items),'family_alpha':package.alpha or 0.05,
        'correction':'Holm 逐步降序校正',
        'raw_significant_count':sum(1 for i in items if i.raw_p_value<(package.alpha or 0.05)),
        'holm_significant_count':sum(1 for i in items if i.holm_significant),
        'items':[{'item_id':i.id,'plan_id':i.plan_id,'plan_title':i.plan_title,
                  'raw_p_value':i.raw_p_value,'holm_rank':i.holm_rank,
                  'holm_adjusted_p':i.holm_adjusted_p,'holm_significant':i.holm_significant}
                 for i in items],
    }
    package.status='completed';package.error=''
    db.commit()
    return package

def claim_joint_package(db):
    package=db.scalar(_locked(db,select(JointPackage).where(JointPackage.status=='queued')
                      .order_by(JointPackage.id)))
    if package: process_joint_package(db,package)
    return package

def reclaim_stale(db):
    """进程中断恢复：running 状态的任务/检验包重置为 queued，等待重新拾取。
    成功项保持 completed，重试时只重算未完成项，不重复建报告。"""
    recovered=[]
    for task in db.scalars(select(Report).where(Report.status=='running')).all():
        task.status='queued';recovered.append(('report',task.id))
    for package in db.scalars(select(JointPackage).where(JointPackage.status=='running')).all():
        package.status='queued';package.error=''
        for item in db.scalars(select(JointPackageItem)
                               .where(JointPackageItem.package_id==package.id,
                                      JointPackageItem.status=='running')).all():
            item.status='queued';item.error=''
        recovered.append(('joint_package',package.id))
    if recovered: db.commit()
    return recovered
