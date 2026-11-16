import{store}from'../stores/business.js';import{esc,num}from'../utils/format.js';import{table}from'../components/common/table.js';import{notice}from'../components/common/notice.js';import{PACKAGE_STATUS,PACKAGE_ITEM_STATUS}from'../constants/enums.js';

const pkgBadge=status=>`<span class="badge ${status==='published'?'completed':status}">${PACKAGE_STATUS[status]||status}</span>`;
const itemBadge=status=>`<span class="badge ${status}">${PACKAGE_ITEM_STATUS[status]||status}</span>`;
const canEdit=()=>store.user.role!=='viewer';

export function jointPackagesPage(){
 const busy=store.packages.some(p=>['queued','running'].includes(p.status));
 return `<header class=page-head><div><span class=eyebrow>05 / JOINT INFERENCE & FAMILY-WISE CONTROL</span><h1>联合检验包</h1><p>同一教研轮次多方案联合封存，逐项检验后按 Holm 校正把整体误报率控制在 5%，整包成功后一次性发布。</p></div></header>
 <div class=split><section><div class=section-title><h2>检验包台账</h2><span>${store.packages.length} 个包${busy?' · 后台计算中':''}</span></div>
 ${store.packages.map((p,idx)=>packageListItem(p,idx===0)).join('')||notice('还没有联合检验包。在右侧至少选择 2 个方案建包。')}
 <div id=package-detail>${store.packages[0]?packageDetail(store.packages[0]):''}</div>
 </section><aside class=side-sheet><span class=eyebrow>PACKAGE BUILDER · 同一时点封存</span><h2>新建联合检验包</h2>
 ${canEdit()?`<form id=package-form><label>检验包名称<input name=title required minlength=2 maxlength=120 placeholder="2026秋季 · 四教学点联合复核"></label>
 <label class=check-wrap>勾选纳入的方案（至少 2 个，不可重复）<div class=plan-pick>${store.plans.map(p=>`<label class="check plan-pick-row"><input type=checkbox name=plan_ids value=${p.id}> <span><b>${esc(p.title)}</b><small>${esc(p.campus)} · ${p.exclude_absent?'排除缺考':'含缺考有效成绩'}</small></span></label>`).join('')||'<small>暂无方案</small>'}</div></label>
 <button class=primary>封存方案与当前样本并提交 →</button></form>`:notice('观察员可查看检验包进度，不能建包、签核或导出。')}
 ${notice('建包瞬间封存全量成绩快照与方案口径；之后成绩、方案修订不影响本包，重算始终使用原样本。')}
 ${notice('整包任一检验项失败即整包失败，失败项保留不删除；沿原包重试不重复建报告。')}
 </aside></div>`;
}

function packageListItem(p,active=false){
 return `<button class="history-entry package-entry ${active?'active':''}" data-package=${p.id}>联合包 № ${p.id}　${esc(p.title)} ${pkgBadge(p.status)}<small>${esc(p.created_at.slice(0,19).replace('T',' '))} UTC · ${p.items?.length||0} 个检验项</small></button>`;
}

export function packageDetail(p){
 if(!p)return notice('请选择一个检验包。');
 const editable=canEdit();
 const rows=p.items.map(i=>{
   const r=i.result||{};
   const raw=i.raw_p_value;
   const holm=i.holm_adjusted_p;
   return [
     `<b>${esc(i.plan_title)}</b><small>方案 № ${i.plan_id} · 检验项 ${i.id}</small>`,
     itemBadge(i.status)+(i.attempts>1?`<small class=muted>　重试 ${i.attempts-1} 次</small>`:''),
     i.status==='completed'
       ? `n₀ ${r.control_n} / n₁ ${r.intervention_n}<br><small>排除 ${r.excluded}/${r.total_selected} · Δ ${num(r.difference)}</small>`
       : `<span class=muted>${esc(i.error||'等待计算')}</span>`,
     i.status==='completed'
       ? `${raw==null?'—':(raw<0.0001?'< 0.0001':num(raw,4))}<br><small>原始 α=0.05：${raw<0.05?'显著':'不显著'}</small>`
       : '—',
     i.status==='completed'
       ? `<b>${holm==null?'—':(holm<0.0001?'< 0.0001':num(holm,4))}</b><br><small>排名 ${i.holm_rank} · ${i.holm_significant?'<span class=sig-yes>校正后显著</span>':'<span class=muted>校正后不显著</span>'}</small>`
       : '—',
   ];
 });
 const summary=p.result;
 return `<section class="result-sheet package-sheet">
 <div class=result-heading><div><span class=eyebrow>JOINT PACKAGE · HOLM α=0.05</span><h2>${esc(p.title)} ${pkgBadge(p.status)}</h2>
 <p>${p.status==='failed'?esc(p.error):p.status==='completed'?'全部检验项成功，已完成 Holm 校正，等待负责人整包签核发布。':p.status==='published'?`整包已于 ${esc((p.published_at||'').slice(0,19).replace('T',' '))} UTC 一次性发布。`:'后台正在按封存样本逐项计算，可随时查看进度。'}</p></div>
 <span class=report-no>联合检验包<br>№ ${String(p.id).padStart(3,'0')}</span></div>
 ${summary&&summary.family_size?`<div class="stats-strip"><div><label>检验项数</label><strong>${summary.family_size}</strong></div><div><label>原始显著数</label><strong>${summary.raw_significant_count}</strong></div><div><label>Holm 校正后显著</label><strong>${summary.holm_significant_count}</strong></div><div><label>族系误报率</label><strong>${num(summary.family_alpha,2)}</strong></div></div>`:''}
 ${table(['检验项（封存方案）','状态','样本与差值','原始 p 值结论','Holm 校正结论'],rows)}
 <div class=package-actions>
 ${p.status==='failed'&&editable?`<button class=primary data-package-retry=${p.id}>沿原包恢复重试 →</button>${notice('重试只重算未完成项，成功项不重复计算、不新建报告。它用于进程中断或瞬时故障恢复；若失败原因是封存样本缺数据（如每组不足 2 条），因封存快照不可变，需修订成绩/方案后新建检验包。')}`:''}
 ${p.status==='failed'&&!editable?notice('检验包整包失败，失败项已保留。分析员可沿原包重试；若为封存样本缺数据，需修订后新建检验包。'):''}
 ${p.status==='queued'||p.status==='running'?notice('计算进行中：成员可查看进度，但不能单独签核或导出任何检验项。'):''}
 ${p.status==='completed'||p.status==='published'?`
 <form id=package-conclusion-form data-id=${p.id}><label>整包教研解释与采纳建议（随整包一次性发布）<textarea name=conclusion rows=3 minlength=4 maxlength=3000 required ${!editable||(p.published&&store.user.role!=='admin')?'disabled':''}>${esc(p.conclusion)}</textarea></label>
 ${store.user.role==='admin'?`<label class=check><input name=published type=checkbox ${p.published?'checked':''}> 负责人整包签核并一次性发布（仅管理员）</label>
 <button class=primary>${p.published?'更新已发布结论':'整包签核发布'}</button>`:`<p class=muted>分析员可保存结论草稿；整包签核发布仅负责人可操作。观察员只读。</p>`}
 ${editable&&!p.published?`<button type=button class=quiet data-package-save-draft=${p.id}>仅保存草稿</button>`:''}
 </form>`:''}
 ${p.published?`<button class=quiet data-package-export=${p.id}>下载联合检验包 JSON ↓</button>`:`<p class="muted checksum">整包成功发布后才允许下载，含逐项原始/校正结论与封存样本。</p>`}
 </div></section>`;
}
