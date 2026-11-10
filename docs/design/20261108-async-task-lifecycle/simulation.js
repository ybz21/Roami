'use strict';
const $=id=>document.getElementById(id);
const STORAGE='roami.async-lifecycle.proposal.v1';
const timers=new Map();
let online=true,page='demo',tab='live',selected='preview',closeTarget=null,conflictTarget=null,lastRequest=null,toastTimer;
const escapeText=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=name=>`<i class="icon ${name}-icon" aria-hidden="true"></i>`;
const uid=prefix=>prefix+'-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,9));
const clock=at=>new Date(at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
function initial(){return {version:1,auto:true,scenario:'normal',theme:'dark',tasks:[
 {id:'preview',title:'修复附件预览',goal:'修复图片附件的预览和返回导航，完成后提交验证结果。',business:'working',lifecycle:'ready',workspace:'使用中',branch:'fix/attachment-preview',draft:'',dirty:2,events:[{at:Date.now(),text:'执行器已开始处理任务。'}]},
 {id:'mobile',title:'检查手机导航',goal:'检查手机顶部返回栏与底部导航，记录触控验证结果。',business:'queued',lifecycle:'ready',workspace:'使用中',branch:'test/mobile-navigation',draft:'',dirty:0,events:[{at:Date.now(),text:'会话已就绪，等待现有执行队列。'}]},
 {id:'settings',title:'整理设置文案',goal:'统一设置页的操作名称和错误提示。',business:'verified',lifecycle:'ready',workspace:'使用中',branch:'fix/settings-copy',draft:'',dirty:0,events:[{at:Date.now(),text:'结果已通过独立验证，会话仍可继续使用。'}]}
 ],ops:[]};}
let state;
try{const saved=JSON.parse(localStorage.getItem(STORAGE)||'null');state=saved?.version===1?saved:initial();}catch{state=initial();}
const taskById=id=>state.tasks.find(t=>t.id===id);
const opFor=t=>state.ops.find(o=>o.id===t?.operationId);
const inFlight=o=>['queued','running','recovering','cancelling'].includes(o.state);
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3200);}
function persist(){try{localStorage.setItem(STORAGE,JSON.stringify(state));return true;}catch{$('control-status').textContent='本地记录保存失败，未确认接收。';return false;}}
function event(task,text){task.events.push({at:Date.now(),text});task.events=task.events.slice(-24);}
function commit(change){const previous=structuredClone(state);change();if(!persist()){state=previous;return false;}return true;}
function isPhone(){return ['compact','medium'].includes(document.documentElement.dataset.size);}
const businessLabel=t=>({working:'执行中',queued:'排队中',verified:'已核验',stopped:'已停止，尚未核验',draft:'待执行'})[t.business]||'待核验';
function label(t){const op=opFor(t);if(t.lifecycle==='preparing')return ['准备中','active'];if(t.lifecycle==='prepare-failed')return ['准备失败','warn'];if(t.lifecycle==='cancelling')return ['取消中','active'];if(t.lifecycle==='cancelled')return ['已取消',''];if(t.lifecycle==='closing')return ['关闭中','active'];if(t.lifecycle==='closed'){if(op?.state==='attention')return [op.intent.mode==='merge'?'会话已关 · 合并待处理':'会话已关 · 清理失败','warn'];if(op&&inFlight(op))return ['会话已关 · 清理中','active'];return [t.workspace==='已保留'?'会话已关 · 工作区已保留':'会话已关 · 已清理',''];}return t.business==='working'?['在跑','active']:t.business==='queued'?['排队中','']:t.business==='verified'?['已核验','ok']:['空闲',''];}
function lifecycleLabel(t){return ({ready:'已就绪',preparing:'准备中','prepare-failed':'准备失败',closing:'关闭中',closed:'已关闭',cancelling:'取消中',cancelled:'已取消'})[t.lifecycle]||t.lifecycle;}
function queueNext(){if(state.tasks.some(t=>t.business==='working'&&t.lifecycle!=='closed'&&t.lifecycle!=='cancelled'))return;const next=state.tasks.find(t=>t.business==='queued'&&t.lifecycle==='ready');if(next){next.business='working';event(next,'停止确认已释放执行槽位，开始处理排队任务。');}}
function schedule(){for(const op of state.ops){if(!state.auto||!inFlight(op)){clearTimeout(timers.get(op.id));timers.delete(op.id);continue;}if(timers.has(op.id))continue;const delay=op.scenario==='slow'&&op.kind==='create'?2400:1050;timers.set(op.id,setTimeout(()=>{timers.delete(op.id);advance(op.id);},delay));}}
function advance(id){const op=state.ops.find(o=>o.id===id);if(!op||!inFlight(op))return;clearTimeout(timers.get(id));timers.delete(id);const t=taskById(op.resourceId);let announcement='';
 const accepted=commit(()=>{
  if(op.state==='cancelling'){
   const stages=['停止已准备的会话','回收本操作的独占资源','记录取消结果'];
   const n=op.cancelStep||0;event(t,stages[n]+'。');op.cancelStep=n+1;
   if(n===2){t.lifecycle='cancelled';t.workspace='已回收';t.business='stopped';op.state='cancelled';announcement='准备已取消，任务说明仍保留在记录中。';}return;
  }
  if(op.state==='queued'||op.state==='recovering'){op.state='running';event(t,op.kind==='create'?'后台开始准备会话。':'后台继续关闭与收尾。');return;}
  const stage=op.stages[op.step];
  if(op.scenario==='prepare-fail'&&op.kind==='create'&&op.step===0&&!op.failureInjected){op.failureInjected=true;op.state='attention';op.error='工作区准备失败，请重试。';t.lifecycle='prepare-failed';t.workspace='准备未完成';event(t,'工作区准备失败；没有发送开工指令。');announcement='准备失败，任务说明已保留。';return;}
  if(op.scenario==='cleanup-fail'&&stage==='清理工作区'&&!op.failureInjected){op.failureInjected=true;op.state='attention';op.error='暂时无法删除目录，文件与分支仍保留。';t.workspace='需要处理';event(t,'目录清理失败，工作区仍保留。');announcement='会话已关闭，清理未完成。可在收尾中重试。';return;}
  if(op.scenario==='merge-conflict'&&stage==='合并到 main'&&!op.resolved){op.state='attention';op.error='合并存在冲突，工作区与分支未删除。';t.workspace='合并待处理';event(t,'合并冲突；没有执行后续删除。');announcement='合并需要处理，工作区已保留。';return;}
  if(op.kind==='create'){
   if(stage==='准备工作区')t.workspace='已准备';
   if(stage==='创建会话')event(t,'会话资源已创建，尚未发送任务。');
   if(stage==='核对目录')event(t,'工作区和会话目录已核对。');
   if(stage==='提交开工'){
    t.lifecycle='ready';t.workspace='使用中';t.business='queued';event(t,'开工请求按现有调度入队；会话现在可进入。');queueNext();
   }
  }else{
   if(stage==='停止并核对'){
    t.lifecycle='closed';t.workspace=op.intent.mode==='keep'?'保留待确认':'待清理';
    if(t.business==='working')t.business='stopped';
    event(t,'执行器及关联写入已停止，会话已关闭。');event(t,'执行槽位已释放；目录收尾继续在后台进行。');queueNext();
   }
   if(stage==='合并到 main'){op.merged=true;event(t,'合并结果已确认并记录，重试不会重复合并。');}
   if(stage==='清理工作区')t.workspace='已清理';
   if(stage==='保留工作区')t.workspace='已保留';
  }
  op.receipts.push(stage);op.step++;
  if(op.step===op.stages.length){op.state='done';event(t,op.kind==='create'?'会话准备完成。':t.workspace==='已保留'?'会话已关闭，工作区按选择保留。':'会话与工作区收尾完成。');announcement=op.kind==='create'?'会话已就绪。':t.workspace==='已保留'?'会话已关闭，工作区已保留。':'后台收尾已完成。';}
 });
 if(!accepted){state.auto=false;for(const timer of timers.values())clearTimeout(timer);timers.clear();return;}
 if(online){render();if(announcement)toast(announcement);}schedule();
}
function accept(kind,payload,key){const prior=state.ops.find(o=>o.requestKey===key);if(prior){$('control-status').textContent='已找到原操作 '+prior.id+'；资源数量没有增加。';if(online)toast('同一请求返回原操作，未重复执行。');return prior;}
 let result;
 const accepted=commit(()=>{
  const resourceId=kind==='create'?uid('session'):payload.resourceId;
  const op={id:uid('op'),requestKey:key,resourceId,kind,state:'queued',step:0,attempt:1,receipts:[],scenario:state.scenario,intent:{...payload},createdAt:Date.now(),revision:1};
  if(kind==='create'){
   const t={id:resourceId,title:payload.title,goal:payload.goal,business:'draft',lifecycle:'preparing',workspace:'待准备',branch:'准备后确定',draft:'',dirty:0,events:[]};
   op.stages=['准备工作区','创建会话','核对目录','提交开工'];t.operationId=op.id;event(t,'请求已保存，可以离开本页。');state.tasks.unshift(t);selected=t.id;tab='live';
  }else{
   const t=taskById(resourceId);if(!t||t.lifecycle!=='ready')throw new Error('会话状态已变化，请重新确认。');
   op.stages=['冻结新输入','停止并核对',...(payload.mode==='keep'?['保留工作区']:['复查工作区',...(payload.mode==='merge'?['合并到 main']:[]),'清理工作区']),'保存结果'];
   op.approvedSnapshot={workspace:resourceId,incarnation:'demo-'+resourceId,head:t.branch,dirty:t.dirty};t.lifecycle='closing';t.operationId=op.id;event(t,'关闭意图已保存，新输入与续派已冻结。');
   const next=state.tasks.find(x=>x.id!==resourceId&&x.lifecycle==='ready');if(next)selected=next.id;
  }
  state.ops.push(op);result=op;
 });
 if(!accepted)return null;lastRequest={kind,payload:structuredClone(payload),key};$('control-status').textContent='请求已确认，后台操作标记已保存。';render();schedule();return result;
}
function renderList(){const live=state.tasks.filter(t=>!['closed','cancelled'].includes(t.lifecycle));const records=state.tasks.filter(t=>['closed','cancelled'].includes(t.lifecycle));const pending=records.filter(t=>{const o=opFor(t);return o&&(inFlight(o)||o.state==='attention');});
 $('live-count').textContent=live.length||'';$('record-count').textContent=pending.length||records.length||'';$('record-count').className=pending.some(t=>opFor(t)?.state==='attention')?'attention-count':'';
 $('tab-live').setAttribute('aria-current',tab==='live'?'page':'false');$('tab-records').setAttribute('aria-current',tab==='records'?'page':'false');
 const items=tab==='live'?live:records;
 $('task-list').innerHTML=items.length?items.map(t=>{const [text,tone]=label(t);return `<div class="task-row"><button type="button" class="task-pick" data-select="${escapeText(t.id)}" aria-current="${selected===t.id}">${icon(t.lifecycle==='closed'?'archive':'terminal')}<span class="task-text"><b>${escapeText(t.title)}</b><span class="state ${tone}">${text}</span><small>${escapeText(t.lifecycle==='ready'?t.branch:t.lifecycle==='preparing'?'任务说明已保存':businessLabel(t))}</small></span></button>${t.lifecycle==='ready'?`<button type="button" class="task-close icon-button quiet" data-close="${escapeText(t.id)}" aria-label="关闭${escapeText(t.title)}" ${online?'':'disabled'}>${icon('close')}</button>`:''}</div>`;}).join(''):'<p class="empty">'+(tab==='live'?'没有打开的会话。':'暂无收尾记录。')+'</p>';
}
function operationHtml(op){if(!op)return '<p class="muted">当前没有待处理的创建或关闭操作。</p>';
 if(op.state==='cancelling')return `<div class="status-banner"><b>正在取消准备</b><p>正在停止已启动部分，确认资源回收后才标记为已取消。</p></div>`;
 return `<ol class="step-list">${op.stages.map((stage,i)=>{const done=i<op.step||op.state==='done',current=i===op.step&&op.state!=='done',blocked=current&&op.state==='attention';return `<li class="${done?'done':blocked?'blocked':current?'current':''}"><span class="step-symbol">${done?icon('check'):i+1}</span><span class="step-text">${stage}${current?`<small>${blocked?'需要处理':op.state==='queued'?'等待后台继续':op.state==='recovering'?'正在核对上次结果':'正在处理'}</small>`:''}</span></li>`;}).join('')}</ol><details class="operation-details"><summary>操作记录</summary><code>${escapeText(op.id)}</code><code>第 ${op.attempt} 次尝试 · 已确认 ${op.receipts.length} 个步骤</code><p>这是本地演示记录；真实执行需核对服务端资源与回执。</p></details>`;
}
function renderDetail(){const t=taskById(selected);if(!t){$('detail').innerHTML='<div class="empty">选择一个会话查看进度。</div>';return;}
 const op=opFor(t),[status,tone]=label(t);let banner='';
 if(t.lifecycle==='preparing')banner='<div class="status-banner"><b>请求已接收，正在准备会话</b><p>可以离开或先写草稿，准备完成后再发送。</p></div>';
 if(t.lifecycle==='ready'&&t.business==='queued')banner='<div class="status-banner"><b>会话已就绪，执行正在排队</b><p>资源准备已完成，开工仍遵循现有调度与额度准入。</p></div>';
 if(t.lifecycle==='closing')banner='<div class="status-banner"><b>关闭请求已接收</b><p>正在确认停止。此时尚未释放执行槽位。</p></div>';
 if(t.lifecycle==='closed'&&op&&inFlight(op))banner='<div class="status-banner"><b>会话已关闭，工作区正在收尾</b><p>其他排队任务可以继续；此工作区暂不开放复用。</p></div>';
 if(op?.state==='attention')banner=`<div class="status-banner warn"><b>${t.lifecycle==='prepare-failed'?'准备失败':'收尾需要处理'}</b><p>${escapeText(op.error)}</p><div class="detail-actions">${op.scenario==='merge-conflict'&&!op.resolved?`<button type="button" class="primary" data-conflict="${op.id}">查看冲突</button>`:`<button type="button" class="primary" data-retry="${op.id}">${op.kind==='create'?'重试准备':'重试清理'}</button>`}${op.kind==='close'?`<button type="button" data-retain="${op.id}">改为保留工作区</button>`:''}</div></div>`;
 if(op?.state==='done'&&t.lifecycle==='closed')banner=`<div class="status-banner ok"><b>${t.workspace==='已保留'?'工作区已按选择保留':'后台收尾已完成'}</b><p>任务记录和对话仍保留，验收状态不因关闭而改变。</p></div>`;
 const canDraft=['ready','preparing','prepare-failed'].includes(t.lifecycle),canSend=t.lifecycle==='ready'&&online;
 $('detail').innerHTML=`<div class="detail-header"><button type="button" id="detail-back" class="icon-button quiet detail-back" aria-label="返回会话列表">${icon('back')}</button><h2>${escapeText(t.title)}</h2>${t.lifecycle==='ready'?`<button type="button" class="quiet" data-close="${escapeText(t.id)}" ${online?'':'disabled'}>关闭</button>`:''}</div><div class="detail-scroll"><div class="status-line"><span class="state ${tone}">${status}</span><span class="muted">${escapeText(businessLabel(t))}</span></div>${banner}<div class="detail-columns"><div class="detail-column"><h3>任务说明</h3><p class="goal">${escapeText(t.goal)}</p>${t.business==='verified'?`<section class="section"><h3>已验证结果</h3><div class="artifact">${icon('file')}设置文案检查记录</div><p class="muted">示例产物。关闭会话后仍可从任务记录查看。</p></section>`:''}<section class="section"><h3>资源状态</h3><dl class="resource-grid"><dt>会话</dt><dd>${lifecycleLabel(t)}</dd><dt>工作区</dt><dd>${escapeText(t.workspace)}</dd><dt>任务</dt><dd>${escapeText(businessLabel(t))}</dd></dl><p class="note">任务、会话和清理各自记录结果。</p></section><section class="section"><h3>${op?.kind==='create'?'创建进度':'收尾进度'}</h3>${operationHtml(op)}${op?.kind==='create'&&['queued','running','recovering'].includes(op.state)?`<button type="button" class="quiet" data-cancel="${op.id}">取消准备</button>`:''}</section></div><div class="detail-column"><h3>最近进展</h3><ul class="events">${t.events.slice(-8).reverse().map(e=>`<li><time>${clock(e.at)}</time><span>${escapeText(e.text)}</span></li>`).join('')}</ul></div></div></div>${canDraft?`<form class="composer" id="composer"><textarea id="draft" rows="2" aria-label="会话草稿" placeholder="${canSend?'补充任务或继续讨论':'先写下补充，准备完成后再发送'}">${escapeText(t.draft)}</textarea><div class="composer-bottom"><small>${canSend?'消息仍按当前会话顺序处理。':'草稿会保留，暂不发送。'}</small><button type="submit" class="primary" ${canSend?'':'disabled'}>发送</button></div></form>`:''}`;
 $('draft')?.addEventListener('input',e=>{t.draft=e.target.value;persist();});
 $('composer')?.addEventListener('submit',e=>{e.preventDefault();const text=t.draft.trim();if(!text||!canSend)return;if(commit(()=>{event(t,'补充内容已加入当前会话输入队列。');t.draft='';t.goal+='\n补充：'+text;})){renderDetail();toast('补充已接收。');}});
 $('detail-back')?.addEventListener('click',()=>document.body.classList.remove('mobile-detail-open'));
}
function render(){document.documentElement.dataset.theme=state.theme;$('theme').textContent=state.theme==='dark'?'浅色':'深色';$('scenario').value=state.scenario;$('autoplay').checked=state.auto;$('connection').hidden=online;$('disconnect').textContent=online?'模拟断线':'重新连接';$('new-task').disabled=!online;renderList();const draft=document.activeElement?.id==='draft'?{start:$('draft').selectionStart,end:$('draft').selectionEnd}:null;renderDetail();if(draft&&$('draft')){$('draft').focus();$('draft').setSelectionRange(draft.start,draft.end);}}
function selectTask(id){selected=id;$('demo-work').classList.remove('no-detail');$('toggle-detail').setAttribute('aria-pressed','true');if(isPhone())document.body.classList.add('mobile-detail-open');render();}
function showClose(id){const t=taskById(id);if(!online||!t||t.lifecycle!=='ready')return;closeTarget=id;$('close-title').textContent='关闭 '+t.title+'？';$('close-summary').textContent=t.dirty?`有 ${t.dirty} 个未提交改动，请选择如何处理。`:'工作区没有未提交改动。请选择保留或清理。';$('close-form').elements.mode.value=state.scenario==='merge-conflict'?'merge':'keep';syncCloseChoice();$('close-dialog').showModal();}
function syncCloseChoice(){const keep=$('close-form').elements.mode.value==='keep';$('delete-branch').disabled=keep;$('delete-branch').checked=!keep;}
document.addEventListener('click',e=>{const target=e.target.closest('button');if(!target)return;const d=target.dataset;
 if(d.dismiss){$(d.dismiss).close();return;}
 if(d.page){page=d.page;document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='page-'+page);document.querySelectorAll('[data-page]').forEach(b=>b.setAttribute('aria-current',b.dataset.page===page?'page':'false'));document.body.classList.remove('mobile-detail-open');return;}
 if(d.select){selectTask(d.select);return;}
 if(d.close){showClose(d.close);return;}
 if(d.retry){const op=state.ops.find(o=>o.id===d.retry);if(op&&op.state==='attention'&&online){commit(()=>{op.state='queued';op.attempt++;op.error=null;if(op.kind==='create'){taskById(op.resourceId).lifecycle='preparing';}event(taskById(op.resourceId),'从失败步骤重试，已确认结果继续保留。');});render();schedule();}return;}
 if(d.cancel){const op=state.ops.find(o=>o.id===d.cancel);if(op&&inFlight(op)){commit(()=>{op.state='cancelling';op.cancelStep=0;taskById(op.resourceId).lifecycle='cancelling';event(taskById(op.resourceId),'取消请求已保存，等待停止与资源补偿。');});render();schedule();}return;}
 if(d.retain){const op=state.ops.find(o=>o.id===d.retain);if(!op||op.state!=='attention')return;commit(()=>{op.priorIntent={...op.intent};op.intent={...op.intent,mode:'keep',deleteBranch:false};op.revision++;op.state='done';op.completion='retained_after_failure';const t=taskById(op.resourceId);t.workspace='已保留';event(t,'用户改为保留工作区；原清理未完成，删除意图已撤回。');});render();toast('已改为保留工作区，原清理结果未记为成功。');return;}
 if(d.conflict){conflictTarget=d.conflict;$('conflict-dialog').showModal();return;}
 if(d.mobileNav){if(d.mobileNav==='projects')document.body.classList.remove('mobile-detail-open');else toast('此原型只演示项目中的创建与收尾。');}
});
$('close-form').addEventListener('change',e=>{if(e.target.name==='mode')syncCloseChoice();});
$('new-task').onclick=()=>$('create-dialog').showModal();
$('create-form').onsubmit=e=>{e.preventDefault();const title=$('create-name').value.trim();if(!title||!online)return;const payload={title,goal:$('create-goal').value.trim()||title};const op=accept('create',payload,uid('request'));if(op){$('create-dialog').close();toast('请求已接收，正在后台准备。');}};
$('close-form').onsubmit=e=>{e.preventDefault();if(!closeTarget||!online)return;const payload={resourceId:closeTarget,mode:$('close-form').elements.mode.value,deleteBranch:$('delete-branch').checked};try{const op=accept('close',payload,uid('request'));if(op){$('close-dialog').close();document.body.classList.remove('mobile-detail-open');toast('关闭请求已接收，可以继续处理其他会话。');}}catch(err){toast(err.message);}};
$('scenario').onchange=e=>{state.scenario=e.target.value;persist();$('control-status').textContent='下次创建或关闭将使用此情境。';};
$('autoplay').onchange=e=>{state.auto=e.target.checked;persist();schedule();};
$('next-step').onclick=()=>{const op=state.ops.find(inFlight);if(op)advance(op.id);else $('control-status').textContent='当前没有可推进的操作；需要处理的失败不会被强行跳过。';};
$('disconnect').onclick=()=>{online=!online;$('connection').hidden=online;$('disconnect').textContent=online?'模拟断线':'重新连接';$('new-task').disabled=!online;if(online){render();toast('已重新连接，按最新快照同步。');}else{$('control-status').textContent='仅暂停页面同步，后台演示继续执行。';render();}};
$('restart').onclick=()=>{for(const timer of timers.values())clearTimeout(timer);timers.clear();commit(()=>{for(const op of state.ops.filter(inFlight)){if(op.state!=='cancelling')op.state='recovering';op.attempt++;event(taskById(op.resourceId),'服务恢复，先核对已确认阶段，再继续原操作。');}});if(online)render();$('control-status').textContent='仍使用同一个操作标记，不重新创建会话。';schedule();};
$('repeat').onclick=()=>{if(!lastRequest){$('control-status').textContent='请先提交一次创建或关闭请求。';return;}accept(lastRequest.kind,lastRequest.payload,lastRequest.key);};
$('reset').onclick=()=>{for(const timer of timers.values())clearTimeout(timer);timers.clear();state=initial();selected='preview';tab='live';online=true;lastRequest=null;document.body.classList.remove('mobile-detail-open');persist();render();$('control-status').textContent='演示已重置。';};
$('theme').onclick=()=>{state.theme=state.theme==='dark'?'light':'dark';persist();render();};
$('tab-live').onclick=()=>{tab='live';renderList();};$('tab-records').onclick=()=>{tab='records';const closed=state.tasks.find(t=>['closed','cancelled'].includes(t.lifecycle));if(closed)selected=closed.id;render();};
$('toggle-detail').onclick=()=>{const hidden=$('demo-work').classList.toggle('no-detail');$('toggle-detail').setAttribute('aria-pressed',String(!hidden));$('toggle-detail').setAttribute('aria-label',hidden?'展开详情':'收起详情');};
$('show-controls').onclick=()=>{if(isPhone()){$('mobile-controls-host').append($('controls'));$('controls-dialog').showModal();}else $('workspace').classList.toggle('hide-controls');};
$('controls-dialog').addEventListener('close',()=>$('control-host').append($('controls')));
$('resolve-conflict').onclick=()=>{const op=state.ops.find(o=>o.id===conflictTarget);if(op&&op.state==='attention'){commit(()=>{op.resolved=true;op.state='queued';op.attempt++;event(taskById(op.resourceId),'用户表示冲突已解决；后台重新核对后继续。');});$('conflict-dialog').close();render();schedule();}};
for(const op of state.ops.filter(inFlight)){if(op.state!=='cancelling')op.state='recovering';op.attempt++;event(taskById(op.resourceId),'页面重新连接，恢复原操作的进度。');}
persist();render();schedule();
