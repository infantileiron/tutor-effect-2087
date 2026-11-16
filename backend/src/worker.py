import time,traceback
from pathlib import Path
from src.config.database import SessionLocal
from src.services.reports import queue
from src.services.joint_packages import QUEUE_KEY
from src.services import processing
def main():
    print('tutor effect worker started',flush=True)
    reclaimed=False
    while True:
        Path('/tmp/worker-heartbeat').touch()
        try:
            if not reclaimed:
                with SessionLocal() as db:
                    recovered=processing.reclaim_stale(db)
                for kind,task_id in recovered: print(f'reclaimed {kind}={task_id} -> queued',flush=True)
                reclaimed=True
            # 任一队列有通知即唤醒；通知丢失时下面的数据库扫描仍会兜底
            queue.blpop(['tutor:reports',QUEUE_KEY],timeout=2)
            with SessionLocal() as db:
                processing.claim_report(db)
                processing.claim_joint_package(db)
        except Exception:
            traceback.print_exc();time.sleep(2)
if __name__=='__main__':
    main()
