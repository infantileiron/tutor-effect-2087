import{request,post}from'./client.js';
export const getJointPackages=()=>request('/joint-packages');
export const getJointPackage=id=>request(`/joint-packages/${id}`);
export const createJointPackage=data=>post('/joint-packages',data);
export const retryJointPackage=id=>post(`/joint-packages/${id}/retry`,{});
export const savePackageConclusion=(id,data)=>request(`/joint-packages/${id}/conclusion`,{method:'PATCH',body:JSON.stringify(data)});
