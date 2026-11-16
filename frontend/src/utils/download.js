async function download(url,filename,token){
 const response=await fetch(url,{headers:{Authorization:`Bearer ${token}`}});
 if(!response.ok) throw new Error('导出失败，请确认已完成签核发布');
 const objectUrl=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=objectUrl;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
}
export async function downloadReport(id,token){return download(`/api/reports/${id}/export`,`tutor-effect-report-${id}.json`,token);}
export async function downloadPackage(id,token){return download(`/api/joint-packages/${id}/export`,`tutor-effect-joint-package-${id}.json`,token);}
