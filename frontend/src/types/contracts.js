/** @typedef {{id:number,code:string,name:string,campus:string,group:'control'|'intervention',score:number|null,absent:boolean}} Student */
/** @typedef {{id:number,title:string,campus:string,exclude_absent:boolean,description:string}} Plan */
/** @typedef {{id:number,plan_id:number,status:string,result:object|null,conclusion:string,published:boolean}} Report */
/** @typedef {{id:number,package_id:number,plan_id:number,plan_title:string,status:string,result:object|null,raw_p_value:number|null,holm_rank:number|null,holm_adjusted_p:number|null,holm_significant:boolean|null,error:string,attempts:number}} JointPackageItem */
/** @typedef {{id:number,title:string,status:'queued'|'running'|'completed'|'failed'|'published',alpha:number,result:object|null,error:string,conclusion:string,published:boolean,published_at:string|null,items:JointPackageItem[]}} JointPackage */
export const contractVersion=2;
