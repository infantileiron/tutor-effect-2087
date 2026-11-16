import math,hashlib,json
from types import SimpleNamespace
from scipy import stats

def welch(students,plan):
    """按方案口径计算 Welch 检验。students 为当前 ORM 对象或封存快照均可。"""
    selected=[s for s in students if plan.campus=='全部' or s.campus==plan.campus]
    kept=[s for s in selected if s.score is not None and (not plan.exclude_absent or not s.absent)]
    control=[s.score for s in kept if s.group=='control']
    treatment=[s.score for s in kept if s.group=='intervention']
    n0,n1=len(control),len(treatment)
    if min(n0,n1)<2: raise ValueError('每组至少需要 2 个有效成绩；请调整教学点或补录样本')
    m0,m1=sum(control)/n0,sum(treatment)/n1
    v0=sum((x-m0)**2 for x in control)/(n0-1)
    v1=sum((x-m1)**2 for x in treatment)/(n1-1)
    se2=v0/n0+v1/n1
    if se2<=0: raise ValueError('两组方差均为零，无法进行 Welch 检验')
    df=se2**2/((v0/n0)**2/(n0-1)+(v1/n1)**2/(n1-1))
    se=math.sqrt(se2);delta=m1-m0;t=delta/se
    p=float(2*stats.t.sf(abs(t),df))
    margin=float(stats.t.ppf(.975,df))*se
    pooled=math.sqrt(((n0-1)*v0+(n1-1)*v1)/(n0+n1-2))
    digest=hashlib.sha256(json.dumps([(s.code,s.score,s.group,s.absent) for s in kept],ensure_ascii=False).encode()).hexdigest()
    return {'control_n':n0,'intervention_n':n1,'excluded':len(selected)-len(kept),'total_selected':len(selected),'control_mean':m0,'intervention_mean':m1,'difference':delta,'t':t,'df':df,'p_value':p,'ci_low':delta-margin,'ci_high':delta+margin,'cohen_d':delta/pooled if pooled else None,'significant':p<.05,'checksum':digest,'sample_snapshot':[{'code':s.code,'group':s.group,'score':s.score,'campus':s.campus} for s in kept],'method':'Welch 独立样本 t 检验；双侧 α=0.05；干预组减对照组；95% CI'}

def welch_from_snapshot(student_snapshot,plan_snapshot):
    """对封存样本与封存方案口径重算，完全不读取当前成绩/方案表。"""
    students=[SimpleNamespace(**s) for s in student_snapshot]
    plan=SimpleNamespace(**plan_snapshot)
    return welch(students,plan)

def holm_adjust(p_values,alpha=0.05):
    """Holm 逐步降序校正，控制族系整体误报率。
    返回与输入等长的列表：{rank(从1开始), adjusted_p, significant, rejected}。
    缺失 p 值（None）保留占位、不参与校正。"""
    m=sum(1 for p in p_values if p is not None)
    order=sorted((i for i,p in enumerate(p_values) if p is not None),key=lambda i:p_values[i])
    out=[None]*len(p_values)
    running=0.0
    rejected=True
    for rank,idx in enumerate(order,start=1):
        raw=p_values[idx]
        running=max(running,min(1.0,(m-rank+1)*raw))
        # Holm：按 p 升序逐项检验，首个未拒绝后后续均不拒绝
        rejected=rejected and raw<=alpha/(m-rank+1)
        out[idx]={'rank':rank,'adjusted_p':float(running),'significant':bool(rejected),
                  'threshold':alpha/(m-rank+1)}
    return out
