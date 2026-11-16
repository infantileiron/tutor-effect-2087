from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    role:Mapped[str]=mapped_column(String(20))
    password_hash:Mapped[str]=mapped_column(String(200))
class Student(Base):
    __tablename__='students'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    name:Mapped[str]=mapped_column(String(80))
    campus:Mapped[str]=mapped_column(String(50))
    group:Mapped[str]=mapped_column(String(20))
    score:Mapped[float|None]=mapped_column(Float,nullable=True)
    absent:Mapped[bool]=mapped_column(Boolean,default=False)
class Plan(Base):
    __tablename__='plans'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(120),unique=True)
    campus:Mapped[str]=mapped_column(String(50),default='全部')
    exclude_absent:Mapped[bool]=mapped_column(Boolean,default=True)
    description:Mapped[str]=mapped_column(Text,default='')
class Report(Base):
    __tablename__='reports'
    id:Mapped[int]=mapped_column(primary_key=True)
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    status:Mapped[str]=mapped_column(String(20),default='queued')
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    conclusion:Mapped[str]=mapped_column(Text,default='')
    published:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[str]=mapped_column(String(40))
class Audit(Base):
    __tablename__='audit_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(String(200))
    status:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[str]=mapped_column(String(40))
class JointPackage(Base):
    """联合检验包：一次封存同一时点的多个方案，做 Holm 联合校正后整体发布。"""
    __tablename__='joint_packages'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(120))
    status:Mapped[str]=mapped_column(String(20),default='queued')
    # 封存时点与口径：plan_id -> 方案字段快照，保证后续方案修订不影响包内重算
    plan_snapshots:Mapped[dict]=mapped_column(JSON)
    alpha:Mapped[float]=mapped_column(Float,default=0.05)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    conclusion:Mapped[str]=mapped_column(Text,default='')
    published:Mapped[bool]=mapped_column(Boolean,default=False)
    published_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
    created_at:Mapped[str]=mapped_column(String(40))
class JointPackageItem(Base):
    """包内逐项检验：封存所选方案及同一时点样本快照，失败项保留不删除。"""
    __tablename__='joint_package_items'
    __table_args__=(UniqueConstraint('package_id','plan_id',name='uq_package_plan'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    package_id:Mapped[int]=mapped_column(ForeignKey('joint_packages.id'))
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    plan_title:Mapped[str]=mapped_column(String(120))
    status:Mapped[str]=mapped_column(String(20),default='queued')
    # 建包同一时点的学员样本快照（全量，按方案口径在计算时筛选）
    student_snapshot:Mapped[list]=mapped_column(JSON)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    raw_p_value:Mapped[float|None]=mapped_column(Float,nullable=True)
    holm_adjusted_p:Mapped[float|None]=mapped_column(Float,nullable=True)
    holm_rank:Mapped[int|None]=mapped_column(Integer,nullable=True)
    holm_significant:Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[str]=mapped_column(String(40))
