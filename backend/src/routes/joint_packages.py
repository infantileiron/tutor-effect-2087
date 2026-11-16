import json
from fastapi import APIRouter,Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.utils.security import current_user,editor,admin
from src.schemas.business import JointPackageInput,PackageConclusionInput
from src.services import joint_packages as service
from src.controllers.business import serialize,serialize_many
router=APIRouter()

def _detail(db,package):
    payload=serialize(package)
    payload['items']=serialize_many(service.get_items(db,package.id))
    return payload

@router.get('/joint-packages')
def listing(db=Depends(get_db),user=Depends(current_user)):
    return [_detail(db,p) for p in service.list_packages(db)]

@router.post('/joint-packages',status_code=202)
def create(data:JointPackageInput,db=Depends(get_db),user=Depends(editor)):
    return _detail(db,service.create_package(db,data,user))

@router.get('/joint-packages/{id}')
def detail(id:int,db=Depends(get_db),user=Depends(current_user)):
    return _detail(db,service.get_package(db,id))

@router.post('/joint-packages/{id}/retry',status_code=202)
def retry(id:int,db=Depends(get_db),user=Depends(editor)):
    return _detail(db,service.retry_package(db,id,user))

@router.patch('/joint-packages/{id}/conclusion')
def conclusion(id:int,data:PackageConclusionInput,db=Depends(get_db),user=Depends(editor)):
    return _detail(db,service.save_package_conclusion(db,id,data,user))

@router.get('/joint-packages/{id}/export')
def export(id:int,db=Depends(get_db),user=Depends(current_user)):
    content=service.export_package(db,id)
    return Response(json.dumps(content,ensure_ascii=False,indent=2),media_type='application/json',
                    headers={'Content-Disposition':f'attachment; filename="tutor-effect-joint-package-{id}.json"'})
