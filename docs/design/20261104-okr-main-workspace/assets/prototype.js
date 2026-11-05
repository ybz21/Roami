(() => {
  'use strict';
  const scriptURL = new URL(document.currentScript.src);
  const runtimeURL = new URL('../index.html', scriptURL).href;
  const studioURL = new URL('../../20261104-okr-studio-project-ownership/index.html', scriptURL).href;
  const technicalURL = new URL('../../20261104-okr-studio-project-ownership/implementation.html', scriptURL).href;
  const iconURL = new URL('icons.svg', scriptURL).href;
  const page = document.body.dataset.page;
  const params = new URLSearchParams(location.search);
  const embedded = params.get('embed') === '1';
  const key = 'roami.design.okr.20261105.v1';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => `<svg aria-hidden="true"><use href="${iconURL}#${name}"></use></svg>`;
  const copy = value => JSON.parse(JSON.stringify(value));
  const read = (suffix, fallback) => { try { return JSON.parse(localStorage.getItem(key + suffix)) ?? fallback; } catch { return fallback; } };
  const write = (suffix, value) => localStorage.setItem(key + suffix, JSON.stringify(value));
  const base = {
    title:'Roami 宣传',objective:'让更多开发者认识并使用 Roami',period:'2026 年 11 月',project:'demo-promotion',main:'demo-promotion-main',revision:12,
    template:'content-growth',github:11,forks:5,bili:false,source:'python',daily:false,dailyAt:'09:00',timezone:'Asia/Shanghai',
    members:[{id:'editor',name:'内容编辑',executor:'Codex',duty:'图文、脚本与来源核对',state:'等待验收',working:false},{id:'video',name:'视频制作',executor:'Claude',duty:'录屏剪辑与短视频交付',state:'制作中',working:true},{id:'analyst',name:'数据分析',executor:'Roami',duty:'采集真实指标，检查口径',state:'空闲',working:false},{id:'reviewer',name:'独立验收',executor:'Codex',duty:'核验当轮产物与发布凭证',state:'等待交付',working:false}],
    krs:[{title:'让感兴趣的人留下来',metric:'GitHub star',value:11,target:30,method:'图文介绍与真实使用案例',description:'围绕移动协作场景制作内容，保留真实来源。'},{title:'让用户看到产品如何工作',metric:'演示视频',value:2,target:6,method:'短视频与操作演示',description:'用可核对的产品画面说明一个具体场景。'},{title:'形成可重复的反馈闭环',metric:'有效反馈',value:3,target:10,method:'日常取数与反馈访谈',description:'记录来源、日期和疑问，再决定下一轮实验。'}]
  };
  const templates = [
    {id:'content-growth',name:'内容增长',description:'目标、图文与视频协作、公开数据采集。',objective:base.objective,roles:['内容编辑','视频制作','数据分析','独立验收']},
    {id:'product-delivery',name:'产品交付',description:'里程碑、实现、审查和交付验收。',objective:'按期交付一个可用的产品版本',roles:['产品设计','功能实现','独立测试']},
    {id:'operations',name:'运营指标',description:'多来源指标、每日采集和异常跟进。',objective:'建立可信的日常经营数据视图',roles:['数据采集','分析跟进']}
  ];
  let model = read('.applied', copy(base));
  let draft = read('.draft', copy(model));
  let section = params.get('tab') || 'team', teamView='chat', recipient='main', fileSelected='', studioPreview='preview', scenario='normal', phonePane='chat';
  let sceneChoice = {}, motion=true, drawer=null, toastTimer, resetting=false;
  const drafts = read('.messages', {}), studioMessages = read('.studioMessages', []);
  const histories = {};
  const root = document.getElementById('prototype');
  const html = document.documentElement;
  const phone = () => ['compact','medium'].includes(html.dataset.size);
  const liveModel = () => embedded && params.get('draft') === '1' ? draft : model;
  const sceneOpen = () => sceneChoice[phone() ? 'phone' : 'desktop'] ?? !phone();
  const recipientKey = () => liveModel().project + ':' + recipient;
  const member = () => liveModel().members.find(item => item.id === recipient);
  const activeName = () => recipient === 'main' ? 'Main' : recipient === 'group' ? '群聊' : member()?.name || '成员';
  const roleState = item => scenario === 'unknown' && item.id === 'editor' ? '待恢复' : item.state;
  const snapshot = () => { write('.messages',drafts);if(page==='studio'){write('.draft',draft);write('.studioMessages',studioMessages);} };
  const rememberText = () => {
    const field = document.querySelector('[data-compose]');
    if (field) { if (page === 'studio') write('.studioInput',field.value);else drafts[recipientKey()] = field.value; snapshot(); }
  };
  function frame(content) {
    const review = `<header class="reviewbar"><nav aria-label="原型顺序"><a href="${runtimeURL}" ${page==='runtime'?'aria-current="page"':''}>01 运行态</a><a href="${studioURL}" ${page==='studio'?'aria-current="page"':''}>02 Studio</a><a href="${technicalURL}" ${page==='technical'?'aria-current="page"':''}>技术实现</a></nav><div class="review-end"><span class="prototype-label">交互原型 · 示例数据</span>${page==='technical'?'':`<select aria-label="验收场景" data-action="scenario"><option value="normal">日常使用</option><option value="stale" ${scenario==='stale'?'selected':''}>采集失败</option><option value="unknown" ${scenario==='unknown'?'selected':''}>成员待恢复</option><option value="empty" ${scenario==='empty'?'selected':''}>空白项目</option>${page==='studio'?'<option value="conflict">保存冲突</option>':''}</select>`}<button class="quiet theme-button" data-action="theme">${html.dataset.theme==='light'?'深色':'浅色'}</button></div></header>`;
    root.innerHTML = `<div class="design-frame${embedded?' embedded':''}">${review}${content}</div>`;
    bind();
  }
  function projectHeader(studio=false) {
    const m = studio ? draft : liveModel();
    return `<header class="project-head tt-pagehead"><div class="project-identity"><h1>${studio?'编辑 ':''}${esc(m.title)}</h1><small>${studio?'草稿 · 原项目与团队保留':esc(m.period)}</small></div><div class="end">${studio?`<button class="quiet phone-only" data-action="phone-preview">${phonePane==='chat'?'预览':'继续聊'}</button><a class="quiet desktop-only" href="${runtimeURL}">查看运行态</a><button class="primary" data-action="apply">保存并应用</button>`:`<a class="quiet edit-link" href="${studioURL}">编辑 OKR</a>`}</div></header>`;
  }
  function projectNav() { return `<nav class="project-nav" aria-label="OKR 导航">${[['okr','OKR'],['data','数据看板'],['team','团队'],['memory','团队记忆'],['files','项目文件']].map(([id,label])=>`<button role="tab" aria-selected="${section===id}" data-section="${id}">${label}</button>`).join('')}</nav>`; }
  function bottomNav() { return `<nav class="mobile-bottom" aria-label="全局导航"><button data-global="home">首页</button><button aria-current="page" data-global="projects">项目</button><button data-global="tools">工具</button><button data-global="settings">设置</button></nav>`; }
  function renderRuntime() {
    const content = section==='team' ? team() : section==='okr' ? objectives() : section==='data' ? dashboard() : files(section==='memory');
    frame(`<main class="app">${projectHeader()}${projectNav()}<div class="canvas" data-section="${section}">${content}</div>${bottomNav()}</main>`);
  }
  function contacts() {
    const m=liveModel();
    const entry=(id,name,sub,type='UserIcon')=>`<button class="contact" aria-pressed="${recipient===id}" data-recipient="${id}"><span class="avatar ${id==='main'?'main':''}">${icon(type)}</span><span class="copy"><strong>${esc(name)}</strong><small>${esc(sub)}</small></span></button>`;
    return `<nav class="contacts" aria-label="切换对话">${entry('main','Main','本 OKR 的固定负责人','SwarmIcon')}${entry('group','群聊','团队共享讨论','UserIcon')}${scenario==='empty'?'':`<h3>成员</h3>${m.members.map(item=>entry(item.id,item.name,item.executor+' · '+roleState(item))).join('')}`}</nav>`;
  }
  function team() {
    return `<div class="work-toolbar"><button class="flat-tab" role="tab" aria-selected="${teamView==='chat'}" data-team="chat">对话与协作</button><button class="flat-tab" role="tab" aria-selected="${teamView==='tasks'}" data-team="tasks">任务<span class="counter">3</span></button></div>${teamView==='tasks'?tasks():`<div class="team-workspace" data-scene="${sceneOpen()}">${contacts()}${conversation()}${sceneOpen()?scene():''}</div>`}`;
  }
  function initialHistory() {
    const item=member(), m=liveModel();
    if (recipient==='main') return [{by:'Main',at:'09:12',html:`<p>今天先完成短视频脚本，再根据真实数据决定下一轮内容。</p><div class="progress-line"><i class="dot"></i>视频制作正在处理脚本和分镜</div><div class="progress-line"><i class="dot wait"></i>介绍稿已交付，等你核对</div><p>团队继续使用原来的成员和对话。你想先看稿件，还是调整今天的安排？</p><div class="delivery"><button data-action="artifact">查看介绍稿</button><button data-action="task-detail">查看待验收任务</button></div>`},{by:'你',at:'09:14',text:'今天先把视频做好，文稿晚一点看。'},{by:'Main',at:'09:14',html:'<p>先推进视频。我会接续视频制作的原对话，完成后核对画面、字幕和来源，再把成片交给你。</p><p class="muted">不会因为追加这轮任务再建一个成员。</p>'}];
    if (recipient==='group') return [{by:'Main',at:'09:12',text:'视频先做脚本，内容编辑准备介绍稿，数据分析核对来源。'},{by:'内容编辑',at:'09:13',html:'<p>介绍稿已放进今天的项目目录，来源也整理好了。</p><div class="delivery"><button data-action="artifact">查看文件</button></div>'},{by:'视频制作',at:'09:14',text:'我接着原来的对话继续做脚本，完成后在这里回报。'}];
    return [{by:item?.name||'成员',at:'09:13',text:item?.id==='editor'?'介绍稿已完成。稿件、ALT 文本和来源说明放在同一份交付目录里，等待核对。':'我会继续当前工作，并把产物交回 Main 验收。'},{by:'你',at:'09:15',text:'继续这一轮，保留之前的上下文。'}];
  }
  function messageHTML(message) { return `<article class="message ${message.by==='你'?'user':''}"><header class="message-author">${esc(message.by)}<time>${esc(message.at||'刚刚')}</time></header>${message.html || `<p>${esc(message.text).replace(/\n/g,'<br>')}</p>`}</article>`; }
  function conversation() {
    const item=member(), unknown=scenario==='unknown'&&recipient==='editor';
    const history=histories[recipientKey()] || initialHistory();
    return `<section class="conversation" data-main-id="${esc(liveModel().main)}" data-chat="${recipient}" aria-label="${esc(activeName())} 对话"><header class="conversation-head"><button class="icon-button phone-only" aria-label="切换对话" data-action="contacts">${icon('UserIcon')}</button><div class="topic"><strong>${esc(activeName())}</strong><small>${recipient==='main'?'本 OKR 的负责人':recipient==='group'?'发给团队，由 Main 协调':esc(item?.executor||'')+' · '+esc(item?.duty||'')}</small></div>${item?`<button class="quiet" data-action="member-detail">详情</button>`:''}${item?`<button class="quiet desktop-only" ${unknown?'disabled':''} data-action="native">进入对话</button>`:''}<button class="quiet" aria-label="协作场景" aria-pressed="${sceneOpen()}" data-action="scene">${icon('PanelRightIcon')}<span class="desktop-only">协作</span></button></header>${unknown?'<div class="notice">原会话状态待核对。<button class="quiet" data-action="ask-main">请 Main 核对</button></div>':''}<div class="messages" role="log"><div class="transcript">${history.map(messageHTML).join('')}</div></div>${composer(drafts[recipientKey()]||'',recipient==='main'?'和 Main 聊，交给它协调团队':recipient==='group'?'发到群聊，Main 会看到':`只发给${item?.name||'这名成员'}`,unknown)}</section>`;
  }
  function composer(value, placeholder, disabled=false, studio=false) {
    return `<div class="composer-wrap"><form class="tt-composer prototype-composer" data-form="${studio?'studio':'chat'}"><textarea data-compose aria-label="${studio?'描述 OKR 修改':'发送给'+activeName()}" rows="2" placeholder="${esc(placeholder)}" ${disabled?'disabled':''}>${esc(value)}</textarea><div class="composer-bar"><button type="button" class="quiet" data-action="attachment">${icon('PlusIcon')}附件</button><span class="muted model-label">${studio?'okr-development':'Roami'} · ${studio?'开发编辑':'项目对话'}</span><button class="send" aria-label="发送" type="submit" ${!value.trim()||disabled?'disabled':''}>${icon('ArrowUp')}</button></div></form></div>`;
  }
  function scene() {
    const m=liveModel(), people=[{id:'main',name:'Main',state:'协调中',working:true},...(scenario==='empty'?[]:m.members.filter(item=>!(scenario==='unknown'&&item.id==='editor')))];
    return `<aside class="scene-pane" aria-label="团队活动"><header class="scene-head"><strong>团队活动</strong><button class="quiet" data-action="motion" aria-pressed="${motion}">${motion?'暂停动画':'开启动画'}</button></header><div class="office" data-motion="${motion}"><div class="office-floor"></div><div class="office-agents">${people.map(item=>`<button class="desk-person" data-scene-recipient="${item.id}" aria-label="与${esc(item.name)}对话" aria-pressed="${recipient===item.id}" data-working="${item.working}"><span class="person"><i class="head"></i><i class="body"></i><i class="desk"></i></span><strong>${esc(item.name)}</strong><small>${esc(item.state)}</small></button>`).join('')}</div></div><p class="scene-foot">点成员，继续同一个对话。</p></aside>`;
  }
  function objectives() {
    const m=liveModel();
    if (scenario==='empty') return `<div class="empty-state"><p>还没有定义这个 OKR。</p><a class="primary" href="${studioURL}">和 Main 一起创建</a></div>`;
    return `<div class="scroll-content"><div class="section-heading"><h2>目标与实施手段</h2><span class="end muted">${esc(m.period)}</span></div><div class="objective-map"><section class="objective-node"><small>O · 目标</small><h2>${esc(m.objective)}</h2></section><div class="kr-column">${m.krs.map((kr,i)=>`<section class="kr-node"><small>KR ${i+1}</small><h3>${esc(kr.title)}</h3><div class="kr-metric"><strong>${kr.value ?? '未知'}</strong><small>/ ${kr.target} ${esc(kr.metric)}</small></div><div class="meter"><span style="width:${Math.min(100,kr.value/kr.target*100)}%"></span></div></section>`).join('')}</div><div class="method-column">${m.krs.map(kr=>`<section class="method-node"><small>实施手段</small><h3>${esc(kr.method)}</h3><p class="muted">${esc(kr.description)}</p></section>`).join('')}</div></div></div>`;
  }
  function dashboard() {
    const m=liveModel(), metrics=m.template!=='content-growth'?m.krs.map(kr=>({title:kr.metric,value:null,unit:'',source:'待确认来源与口径',skill:'collect-'+m.template})).concat(m.bili?[{title:'B 站播放量',value:null,unit:'次',source:'账号待连接',skill:'collect-bilibili'}]:[]):[{title:'GitHub star',value:m.github,unit:'个',values:[6,8,8,9,10,11,11],source:'GitHub · ybz21/Roami',skill:'collect-github'},{title:'GitHub fork',value:m.forks,unit:'个',values:[2,3,3,4,4,5,5],source:'GitHub · ybz21/Roami',skill:'collect-github'},{title:'有效反馈',value:3,unit:'条',values:[0,0,1,1,2,2,3],source:'已核对的反馈记录',skill:'review-feedback'},{title:'演示视频',value:2,unit:'条',values:[0,0,0,1,1,1,2],source:'已验收的项目文件',skill:'review-deliveries'},{title:'X 曝光',value:null,unit:'',source:'账号未连接',skill:'collect-x'},...(m.bili?[{title:'B 站播放量',value:null,unit:'次',source:'账号待连接',skill:'collect-bilibili'}]:[])];
    return `<div class="scroll-content">${scenario==='stale'?'<div class="notice">今天的采集未完成，保留上次有效数据。Main 会跟进来源问题。</div>':''}<div class="section-heading"><h2>数据看板</h2><small class="end">11 月 5 日 ${scenario==='stale'?'上次有效值':'09:00 更新'}</small></div><div class="dashboard">${metrics.map(metric=>`<article class="metric-card"><header><h3>${metric.title}</h3><small>${metric.value===null?'未知':scenario==='stale'?'待更新':'最近 7 天'}</small></header><div class="metric-value">${metric.value===null?'<strong class="unknown">暂无数据</strong>':`<strong>${metric.value}</strong><small>${metric.unit}</small>`}</div>${metric.values?`<div class="chart" aria-label="${metric.title} 近七日趋势">${metric.values.map(v=>`<span style="height:${Math.max(4,v/Math.max(...metric.values)*100)}%"></span>`).join('')}</div><div class="chart-labels"><span>10/30</span><span>11/05</span></div>`:'<div class="empty-chart">等待真实观测</div>'}<details><summary>数据来源</summary><p>${esc(metric.source)}</p><p>Skill：${esc(metric.skill)}。失败保留旧值，缺失不记为零。</p></details></article>`).join('')}</div></div>`;
  }
  function tasks() {
    const columns=[['待办',[['补齐反馈来源','数据分析 · 等待安排']]],['进行中',[['完成短视频脚本','视频制作 · 原对话继续']]],['待验收',[['介绍稿与来源说明','内容编辑 · 交付已收到']]],['已完成',[['核对本周公开数据','独立验收 · 已核对']]]];
    return `<div class="scroll-content"><div class="board">${columns.map(([title,items])=>`<section class="board-column"><h3>${title}</h3>${items.map(([name,sub])=>`<button class="task-card" data-action="task-detail"><strong>${name}</strong><small>${sub}</small></button>`).join('')}</section>`).join('')}</div></div>`;
  }
  function fileEntries(memory=false, studio=false) {
    const m=studio?draft:liveModel();
    const entries={
      'AGENTS.md':`# 项目工作约定\n\n本项目 Main 与首页 Main 相互独立。\n团队记忆：.roami/okr/memory/team.md\n重要事项：.roami/okr/memory/decisions.md\n成员记忆：.roami/okr/memory/members/<stable-member-id>/memory.md\n每个职责复用原实例，追加任务形成新轮次。\n产物按 YYYY/YYYYMM/YYYYMMDD/ 保存。`,
      '.roami/okr/okr.json':JSON.stringify({revision:m.revision,objective:m.objective,startDate:'2026-11-01',endDate:'2026-11-30',metrics:[{id:'stars',name:'GitHub star',unit:'个',source:'github',repo:'ybz21/Roami',field:'stars'},{id:'forks',name:'GitHub fork',unit:'个',source:'github',repo:'ybz21/Roami',field:'forks'},{id:'videos',name:'演示视频',unit:'条',source:'manual'},{id:'feedback',name:'有效反馈',unit:'条',source:'manual'},...(m.template==='product-delivery'?[{id:'milestones',name:'已验收里程碑',unit:'项',source:'manual'},{id:'workflows',name:'通过的关键流程',unit:'项',source:'manual'}]:m.template==='operations'?[{id:'coverage',name:'来源覆盖',unit:'个',source:'manual'}]:[])],keyResults:m.krs.map((kr,i)=>({id:'kr-'+(i+1),title:kr.title,horizon:'short',metricId:(m.template==='product-delivery'?['milestones','workflows']:m.template==='operations'?['coverage']:['stars','videos','feedback'])[i]||'feedback',mode:'atLeast',target:kr.target,dueDate:'2026-11-30'})),autoCollect:false,swarm:'demo-bound-team'},null,2),
      '.roami/okr/dashboard.json':JSON.stringify({schemaVersion:1,widgets:[{id:'public-counts',type:'metricTrend',metricIds:['stars','forks']},...(m.bili?[{id:'bili-views',type:'metricTrend',metricIds:['bili-views']}]:[])]},null,2),
      '.roami/okr/agents/team.json':JSON.stringify({schemaVersion:1,roles:(m.plannedRoles||m.members).map(item=>({id:item.id,name:item.name,executor:item.executor==='Roami'?'native':item.executor.toLowerCase(),duty:item.duty}))},null,2),
      '.roami/okr/skills/collect-github/SKILL.md':'---\nname: collect-github\ndescription: 采集本项目 GitHub 公开指标并提交有来源的观测。\n---\n\n1. 读取已确认的仓库、指标和采集日期。\n2. '+(m.source==='mcp'?'调用已连接的 MCP 只读取数工具。':'运行 scripts/collect.py，获取公开仓库统计。')+'\n3. 检查仓库身份、口径、日期和数值，保留原始证据。\n4. 通过受管采集回执提交结果，由宿主检查并发布。\n5. 失败保留旧数据；状态未知先核对原执行。',
      '.roami/okr/skills/collect-github/scripts/collect.py':'# 提议中的 Skill 内部脚本接口，非现有产品 Runner。\n# Python 只负责取数、标准化及证据；不直接覆盖已确认数据。\ndef collect(source, as_of):\n    payload = fetch_confirmed_source(source)\n    return normalize_with_evidence(payload, as_of)\n',
      '.roami/okr/connectors/public-counts/connector.json':JSON.stringify({schemaVersion:2,skill:'collect-github',metricIds:['stars','forks'],source:{service:'github',resource:'ybz21/Roami'}},null,2),
      '.roami/okr/schedules/daily.json':JSON.stringify({schemaVersion:1,enabled:m.daily,skill:'collect-github',dailyAt:m.dailyAt,timezone:m.timezone},null,2),
      '.roami/okr/memory/team.md':'# 团队记忆\n\n每个职责只有一名固定成员；新一轮追加任务不重建实例。\n事实必须带来源。今天的产物与历史素材分开保存。\n外部发布先核对内容与账号，保留平台回执。',
      '.roami/okr/memory/decisions.md':'# 重要事项\n\n2026-11-05：Connector 以 Skill 为入口，内部可用 Python 或 MCP。\n每日时刻与时区由用户确认后启用。\n看板定义与有效数据放文件，运行记录与重试由执行数据库管理。',
      '2026/202611/20261105/x-content/intro.md':'# 介绍稿（示例）\n\n用手机继续开发机上的同一个智能体对话。\n\n来源：产品的真实操作记录。\n状态：待核对，未上传、未发布。',
      '2026/202611/20261105/README.md':'# 当日交付索引\n\n介绍稿：x-content/intro.md\n视频脚本：bili-video/script.md\n各轮产物保留原任务、修订与执行回执。'
    };
    if (m.source==='mcp') { delete entries['.roami/okr/skills/collect-github/scripts/collect.py'];entries['.roami/okr/skills/collect-github/references/mcp.md']='使用已经登记的 MCP 连接及只读取数工具。\n记录连接身份、账号、工具 schema 与结果映射。\n连接不存在或权限不足时，保持待连接；不自动换账号。'; }
    if (m.bili) entries['.roami/okr/skills/collect-bilibili/SKILL.md']='---\nname: collect-bilibili\ndescription: 从已授权来源采集 B 站播放量。\n---\n\n确认账号和日期后调用对应来源。\n未连接时不启用采集、不生成假数据。';
    return Object.entries(entries).filter(([name])=>!memory||name.startsWith('.roami/okr/memory/'));
  }
  function files(memory=false,studio=false) {
    const entries=fileEntries(memory,studio);if(!entries.some(([name])=>name===fileSelected)) fileSelected=entries[0][0];
    const current=entries.find(([name])=>name===fileSelected);
    return `<div class="file-workspace"><nav class="file-tree" aria-label="${memory?'团队记忆':'项目文件'}"><h3>${memory?'.roami/okr/memory/':'roami-promotion/'}</h3>${entries.map(([name])=>`<button class="file-row" data-file="${esc(name)}" aria-pressed="${fileSelected===name}">${esc(memory?name.replace('.roami/okr/memory/',''):name)}</button>`).join('')}</nav><article class="file-preview"><h2>${esc(current[0].split('/').pop())}</h2><pre>${esc(current[1])}</pre></article></div>`;
  }
  function renderStudio() {
    frame(`<main class="app">${projectHeader(true)}<div class="studio-shell" data-phone-pane="${phonePane}"><section class="studio-conversation"><header class="studio-title"><h2>和 Main 一起编辑</h2><button class="quiet" data-action="templates">选择模板</button></header><div class="messages" role="log"><div class="transcript"><article class="message"><header class="message-author">Main<small>okr-development</small></header><p>说清你想改什么，先在右侧看效果。确认后更新原项目，团队、历史和数据继续保留。</p><div class="prompt-suggestions"><button class="quiet" data-prompt="增加 B 站播放量看板">增加 B 站播放量看板</button><button class="quiet" data-prompt="每天 09:00 更新 GitHub 数据">每天 09:00 更新 GitHub 数据</button><button class="quiet" data-action="connector">把取数接成 Python 或 MCP Skill</button></div></article>${studioMessages.map(messageHTML).join('')}</div></div>${composer(read('.studioInput',''),'描述目标、看板、分工或数据来源',false,true)}</section><section class="studio-preview"><header class="preview-toolbar"><button class="flat-tab" aria-selected="${studioPreview==='preview'}" data-preview="preview">运行预览</button><button class="flat-tab" aria-selected="${studioPreview==='files'}" data-preview="files">项目文件</button><div class="end"><small>草稿未应用</small><button class="quiet" data-action="changes">查看变更</button></div></header><div class="preview-host">${studioPreview==='files'?files(false,true):`<iframe title="OKR 运行预览" src="${runtimeURL}?embed=1&draft=1&tab=${draft.bili?'data':'okr'}"></iframe>`}</div></section></div></main>`);
    document.querySelector('iframe')?.addEventListener('load',updatePreview);
  }
  function updatePreview(){ const frame=document.querySelector('iframe');if(frame)frame.contentWindow.postMessage({kind:'roami-okr-design-draft',draft},location.origin==='null'?'*':location.origin); }
  function toast(text) {document.querySelector('.toast')?.remove();const node=document.createElement('div');node.className='toast';node.setAttribute('role','status');node.textContent=text;document.body.append(node);clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.remove(),4500);}
  function closeDrawer(){document.querySelector('.drawer-backdrop')?.remove();document.querySelector('.inspector')?.remove();drawer=null;}
  function showDrawer(title,content) {
    closeDrawer();drawer=title;
    const cover=document.createElement('div');cover.className='drawer-backdrop';cover.dataset.action='close-drawer';
    const node=document.createElement('section');node.className='inspector';node.setAttribute('role','dialog');node.setAttribute('aria-modal','true');node.setAttribute('aria-label',title);node.innerHTML=`<header><h2>${esc(title)}</h2><button class="icon-button" aria-label="返回" data-action="close-drawer">${icon('CloseIcon')}</button></header>${content}`;
    document.body.append(cover,node);bind(node);cover.onclick=closeDrawer;
  }
  function memberDetails() {
    const item=member();if(!item)return;
    showDrawer(item.name,`<div class="drawer-body"><p>${esc(item.duty)}</p><dl><dt>执行器</dt><dd>${item.executor}</dd><dt>当前状态</dt><dd>${roleState(item)}</dd><dt>长期记忆</dt><dd>个人笔记与原对话保留</dd></dl><h3>本轮交付</h3><button class="quiet strong" data-action="artifact">介绍稿与来源说明</button><h3>执行轮次</h3><p>第 3 轮 · 当前交付待验收</p><p class="muted">第 2 轮 · 已验收<br>第 1 轮 · 已验收</p><button class="primary" data-action="native" ${scenario==='unknown'?'disabled':''}>进入 ${item.executor} 原对话</button><details><summary>身份与恢复</summary><pre>project: ${esc(liveModel().project)}\nmember: ${esc(item.id)}\nprovider conversation: demo-${esc(item.id)}-original\n原对话身份必须匹配；状态未知不新建替身。</pre></details></div>`);
  }
  function sendChat(field) {
    const text=field.value.trim();if(!text)return;
    const k=recipientKey();histories[k] ||= initialHistory();histories[k].push({by:'你',text,at:'刚刚'});
    histories[k].push({by:activeName()==='群聊'?'Main':activeName(),at:'刚刚',text:recipient==='main'?'收到。我会在这个 OKR 的原团队里安排，完成后带着本轮产物和核对结果回来。':recipient==='group'?'我看到了这条群聊消息。会按当前分工协调，并把回执留在这里。':'收到，我会在当前实例里接着做，把结果交给 Main 核对。'});
    drafts[k]='';snapshot();renderRuntime();document.querySelector('.messages')?.scrollTo({top:1e6});toast('原型消息已加入当前对话；未发送到真实智能体。');
  }
  function changeDraft(text) {
    if(!text.trim())return;studioMessages.push({by:'你',text,at:'刚刚'});
    const changes=[];
    if(/B\s*站|bilibili/i.test(text)){draft.bili=true;changes.push('新增 B 站播放量卡片；数据在连接来源前保持未知。');}
    if(/每天|日更|定时|09:00/.test(text)){draft.daily=true;draft.dailyAt=(text.match(/\d{1,2}:\d{2}/)||['09:00'])[0].padStart(5,'0');changes.push(`采集草稿：每天 ${draft.dailyAt}，Asia/Shanghai。应用时仍需来源与调度器确认。`);}
    if(/MCP/i.test(text)){draft.source='mcp';changes.push('Connector Skill 内改用 MCP；保留来源绑定和发布校验。');}
    if(/Python/i.test(text)){draft.source='python';changes.push('Connector Skill 内使用 Python 脚本；定义与日更独立。');}
    if(/视频.*成员|视频制作|增加.*成员/.test(text)){if(!draft.members.some(item=>item.id==='video'))draft.members.push(copy(base.members[1]));changes.push('复用视频制作职责；只为缺少的职责补定义。');}
    if(!changes.length){draft.objective=text;changes.push('目标文字已更新到草稿预览；原指标与团队保持。');}
    studioMessages.push({by:'Main',at:'刚刚',html:`<p>草稿已更新，请先看运行效果。</p><div class="draft-changes">${changes.map(c=>`<p>${esc(c)}</p>`).join('')}</div>`});write('.studioInput','');snapshot();renderStudio();
  }
  function templatePicker() {
    showDrawer('选择预置模板',`<div class="drawer-body"><p class="muted">模板提供起点，KR、图表和成员数量仍按目标调整。</p><div class="template-grid">${templates.map(item=>`<button class="template-choice" data-template="${item.id}"><h3>${item.name}</h3><p>${item.description}</p><small>${item.roles.join('、')}</small></button>`).join('')}</div></div>`);
  }
  function connectorSettings() {
    showDrawer('数据采集 Skill',`<div class="drawer-body"><p>Python 与 MCP 都由 Skill 组织，取数后提交有来源的观测。</p><div class="settings-row"><label for="source-type">Skill 内部实现</label><select id="source-type"><option value="python" ${draft.source==='python'?'selected':''}>Python 脚本</option><option value="mcp" ${draft.source==='mcp'?'selected':''}>已连接的 MCP 工具</option></select></div><label class="settings-check"><input id="daily-enabled" type="checkbox" ${draft.daily?'checked':''}>每日更新</label><div class="settings-row"><label for="daily-time">执行时间</label><input id="daily-time" type="time" value="${esc(draft.dailyAt)}"></div><div class="settings-row"><label for="timezone">时区</label><select id="timezone"><option>Asia/Shanghai</option><option>UTC</option></select></div><p class="muted">原型只保存调度草稿，真实启用必须有调度器回执和下一次执行时间。</p><button class="primary" data-action="save-connector">更新草稿</button></div>`);
  }
  function applyDraft() {
    rememberText();
    if(scenario==='conflict'){showDrawer('项目有更新',`<div class="drawer-body"><p>当前项目有新修订，你的修改已保留。先查看差异，再重新确认应用。</p><pre>基础修订：12\n项目最新修订：13\n保留：你的指标、Skill 和调度草稿\n不自动覆盖：新来源与团队调整</pre><button class="primary" data-action="merge-demo">核对后合并草稿</button></div>`);return;}
    model=copy(draft);model.revision+=1;draft.revision=model.revision;write('.applied',model);snapshot();toast('演示：配置已应用到原项目。未派工、未取数、未启用真实定时任务。');
    document.querySelector('.preview-toolbar .end small').textContent='演示应用完成';
  }
  function renderTechnical() {
    frame(`<main class="technical"><article><h1>从对话开发，到持续运行</h1><p class="muted">设计提案 · 2026-11-05。原型数据和调度均为模拟；不代表未实现能力已经上线。</p><nav class="technical-index"><a href="#contract">目录与存储</a><a href="#skills">开发 Skill / 模板</a><a href="#execution">Skill 日更</a><a href="#identity">实例与消息隔离</a><a href="#delivery">实施顺序</a></nav><div class="flow"><section><strong>1. 聊目标</strong><small>固定 Main 加载 okr-development，读取现有定义。</small></section><section><strong>2. 看运行预览</strong><small>模板形成草稿；先验证，再确认应用。</small></section><section><strong>3. 持续执行</strong><small>Skill 采集；原团队追加任务，不重复建实例。</small></section><section><strong>4. 发布事实</strong><small>核对来源与修订，原子更新文件快照。</small></section></div><h2 id="contract">项目目录是产品定义</h2><pre>PROJECT/\n  AGENTS.md\n  .roami/okr/\n    okr.json / dashboard.json\n    agents/main.json / team.json / swarm.json\n    skills/collect-SOURCE/SKILL.md\n      scripts/collect.py           # 需要 Python 时\n      references/mcp.md            # 需要 MCP 时\n    connectors/SOURCE/connector.json\n    schedules/daily.json           # 提议中的调度输入\n    memory/team.md / decisions.md\n    memory/members/MEMBER/memory.md\n    data/observations.jsonl\n    state/current.json\n    state/confirmed-revisions/\n  YYYY/YYYYMM/YYYYMMDD/            # 产物与验收</pre><table><tr><th>内容</th><th>权威与用途</th></tr><tr><td>目标、看板、Skill、来源与调度定义</td><td>项目文件；编辑是草稿，保存/同步后成为确认版本。</td></tr><tr><td>有效指标与历史观测</td><td>确认快照为读取权威；JSONL 同次导出。最后原子推进 current.json。</td></tr><tr><td>计划与执行记录</td><td>运行时 SQLite 的任务、轮次、定时、去重与重试；不另建指标事实主库。</td></tr><tr><td>模型凭证与来源授权</td><td>既有凭证与权限系统；不进入模板、项目文件或日志。</td></tr></table><h2 id="skills">开发与编辑统一用 okr-development</h2><p>新建和编辑走同一个 Skill。先读项目和当前修订，复用用户已经给出的目标、来源和团队；输出草稿、运行预览与实际差异，再通过版本检查应用。Skill 不靠模板固定 KR 或成员数量。</p><table><tr><th>资源</th><th>设计</th><th>状态</th></tr><tr><td><code>skills/okr-development/SKILL.md</code></td><td>已有 canonical 入口；扩展草稿、模板和预览编排。</td><td>入口已合入，编辑预览待实现</td></tr><tr><td><code>references/bundle.md</code></td><td>已存在的文件/工具契约；补充 Skill Connector 与调度。</td><td>规范草稿</td></tr><tr><td><code>assets/templates/&lt;id&gt;/</code></td><td>预置目标/看板/职责/采集 Skill 种子；有版本，可按需覆盖目标，不含账号和实例 ID。</td><td>本轮提供示例模板</td></tr><tr><td>草稿与预览</td><td>新增 DraftStore，基于原 revision 隔离文件变更。复用运行态渲染器；预览不注册成员、不启用日更。</td><td>待实现</td></tr></table><h2 id="execution">Connector 本身就是 Skill</h2><p>Python 放在 Skill 的 scripts，MCP 通过已有连接和工具调用。connector.json 只绑定来源、指标与 Skill；不再发展一套任意命令插件协议。</p><div class="flow"><section><strong>调度到期</strong><small>持久 job 领取租约，按项目、Skill 版本和日期去重。</small></section><section><strong>受管执行 Skill</strong><small>绑定项目、来源与权限；执行 Python 或 MCP 的真实取数。</small></section><section><strong>校验候选结果</strong><small>指标、日期、单位、来源及证据，重新核对配置修订。</small></section><section><strong>发布 / 失败留旧值</strong><small>事实与快照落盘后推进指针；未知结果恢复同一 run。</small></section></div><p>复用 Python dispatch/jobs 与 Go 的项目文件发布能力。新增项目采集授权范围与批量结果提交；现有 Worker 不允许直接调用 Main 的 project_okr_update，不能用 shell 或 SQLite 绕过。工作目录限制不是 OS 沙箱；Python 执行的能力边界必须在宿主执行/授权层落实。</p><p>首版只读采集；不承载发布内容、转账或账号写入。凭证不可用时保持未知，重试不换账号。错过日期只采集当前真实口径，不补造历史。提醒不是执行器，Agent 存活不是定时器。</p><h2 id="identity">同一职责，同一个长期实例</h2><p>项目 Main 与首页 Main 独立；团队成员、原生实例、任务/轮次分层。Main、群聊、成员三种目标显式选择，切换不暗中转发。来源引用只跳回同项目同原对话；无派发或状态未知时先核对，禁止从名称后缀猜身份。</p><table><tr><th>操作</th><th>必须保留 / 检查</th></tr><tr><td>追加一轮</td><td>保留 memberId 与原 conversation；task/revision/run 各自记账。接收回执不等于完成。</td></tr><tr><td>进入 Codex / Claude 对话</td><td>owner/node/project/member、provider conversation、executor、workspace、当前 revision/run 与关闭状态。</td></tr><tr><td>旧会话消失</td><td>可信 provider 身份恢复原对话；证据不足显示待恢复，不新建替代。</td></tr><tr><td>旧重复职责收拢</td><td>用户可核对的显式映射与 CAS；保留任务、历史、产物和原来源。</td></tr></table><h2 id="delivery">实施顺序与验收</h2><table><tr><th>批次</th><th>交付</th><th>独立验收</th></tr><tr><td>一</td><td>对话/协作合页，移除重复列表</td><td>Main/群聊/成员直达，草稿不串，场景折叠释放空间；四档桌面和手机。</td></tr><tr><td>二</td><td>开发编辑 Skill + 预置模板 + 草稿预览</td><td>空目录生成、同项目修改、模板可调、冲突保留草稿，预览无运行副作用。</td></tr><tr><td>三</td><td>Skill 单次采集与文件发布</td><td>Python/MCP fixture 真正执行、证据与单位校验、批量 CAS、重放不重复、失败留旧值。</td></tr><tr><td>四</td><td>持久日更与可信实例恢复</td><td>重启、时区、跨日、去重、失败退避、未知执行恢复；原成员和对话保持。</td></tr></table><p>已有基础：#681 文件包/团队定义/开发入口；#682 Main 优先对话；成员与轮次账本已存在。待办：通用 Skill 日更、预览编辑工作台、模板装配及完整 provider attestation。未完成项留在 #656/#658/#679，不能按原型截图关闭。</p><p><a href="implementation.md">查看完整技术方案（Markdown）</a></p></article></main>`);
  }
  function bind(scope=root) {
    scope.querySelectorAll('[data-section]').forEach(button=>{if(button.tagName==='BUTTON')button.onclick=()=>{rememberText();section=button.dataset.section;fileSelected='';renderRuntime();};});
    scope.querySelectorAll('[data-team]').forEach(button=>button.onclick=()=>{rememberText();teamView=button.dataset.team;renderRuntime();});
    scope.querySelectorAll('[data-recipient],[data-scene-recipient]').forEach(button=>button.onclick=()=>{rememberText();recipient=button.dataset.recipient||button.dataset.sceneRecipient;closeDrawer();renderRuntime();});
    scope.querySelectorAll('[data-file]').forEach(button=>button.onclick=()=>{rememberText();fileSelected=button.dataset.file;page==='studio'?renderStudio():renderRuntime();});
    scope.querySelectorAll('[data-preview]').forEach(button=>button.onclick=()=>{rememberText();studioPreview=button.dataset.preview;renderStudio();});
    scope.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{rememberText();changeDraft(button.dataset.prompt);});
    scope.querySelectorAll('[data-template]').forEach(button=>button.onclick=()=>{
      const selected=templates.find(item=>item.id===button.dataset.template);draft.template=selected.id;draft.objective=selected.objective;
      draft.plannedRoles=selected.roles.map((name,i)=>({id:'role-'+selected.id+'-'+i,name,executor:'Roami',duty:({产品设计:'需求拆解、交互与验收标准',功能实现:'功能实现与专项回归',独立测试:'独立核验产物与关键流程',数据采集:'按授权来源取数，保留证据和口径',分析跟进:'复核异常并提出下一轮行动'})[name]||base.members.find(item=>item.name===name)?.duty||name}));
      if(selected.id!=='content-growth') draft.krs=selected.id==='product-delivery'?[{title:'完成可用版本',metric:'已验收里程碑',value:null,target:3,method:'分阶段实现与验收',description:'每个阶段有产物、测试和验收。'},{title:'验证关键流程',metric:'通过的关键流程',value:null,target:5,method:'真实场景回归',description:'根据实际风险调整流程数量。'}]:[{title:'每天有可信指标',metric:'来源覆盖',value:null,target:3,method:'Skill 日更',description:'按确认账号、来源和日期采集。'}];else draft.krs=copy(base.krs);
      studioMessages.push({by:'Main',at:'刚刚',text:`已以「${selected.name}」作为草稿起点，尚未应用。目标、成员和看板都可以继续聊着改。`});snapshot();closeDrawer();renderStudio();
    });
    scope.querySelectorAll('[data-action]').forEach(button=>{
      const action=button.dataset.action;
      if(action==='scenario'){button.value=scenario;button.onchange=()=>{rememberText();scenario=button.value;page==='runtime'?renderRuntime():renderStudio();};return;}
      button.onclick=()=>{
        if(action==='theme'){rememberText();html.dataset.theme=html.dataset.theme==='light'?'dark':'light';write('.theme',html.dataset.theme);render();}
        if(action==='scene'){rememberText();sceneChoice[phone()?'phone':'desktop']=!sceneOpen();renderRuntime();}
        if(action==='motion'){rememberText();motion=!motion;renderRuntime();}
        if(action==='contacts')showDrawer('切换对话',contacts());
        if(action==='close-drawer')closeDrawer();
        if(action==='member-detail')memberDetails();
        if(action==='ask-main'){rememberText();recipient='main';renderRuntime();toast('已回到本 OKR Main，请说明需要核对的会话。');}
        if(action==='artifact')showDrawer('介绍稿与来源说明',`<div class="drawer-body"><p>当日交付 · 待核对</p><pre>${esc(fileEntries().find(([n])=>n.endsWith('/intro.md'))[1])}</pre><h3>交付位置</h3><pre>roami-promotion/\n2026/202611/20261105/x-content/intro.md</pre><p class="muted">示例文件。真实产物以当前 run 的字节、来源和验收为准。</p></div>`);
        if(action==='task-detail')showDrawer('介绍稿与来源说明',`<div class="drawer-body"><p><span class="status-tag planned">等待验收</span></p><h3>交付物</h3><button class="quiet strong" data-action="artifact">介绍稿、ALT 与来源说明</button><h3>需要核对</h3><p>文字与实际产品行为一致；来源可打开；账号和发布范围正确。</p><p class="muted">交付收到不等于通过验收；当前没有发布回执。</p><details><summary>执行记录</summary><pre>固定成员：内容编辑\n第 3 轮任务，原 provider 对话继续\n执行器报告已交付，宿主等待独立验收</pre></details></div>`);
        if(action==='native'){const item=member();showDrawer(`${item?.name||'成员'} · ${item?.executor||'原生'} 对话`,`<div class="drawer-body"><p>原对话预览</p><p class="muted">原型未连接真实 Codex/Claude，不创建新实例。</p><h3>当前上下文</h3><p>保留前两轮来源核对、项目约定和当前交付。</p><pre>member: ${esc(item?.id)}\nprovider: demo-${esc(item?.id)}-original\n项目：${esc(liveModel().title)}</pre><button class="primary" data-action="close-drawer">返回项目对话</button></div>`);}
        if(action==='attachment')toast('原型附件入口；实际实现复用全局 ConversationComposer。');
        if(action==='templates')templatePicker();
        if(action==='connector')connectorSettings();
        if(action==='save-connector'){draft.source=document.getElementById('source-type').value;draft.daily=document.getElementById('daily-enabled').checked;draft.dailyAt=document.getElementById('daily-time').value||'09:00';draft.timezone=document.getElementById('timezone').value;snapshot();closeDrawer();studioMessages.push({by:'Main',at:'刚刚',text:'Skill 和调度草稿已更新。启用和取数的真实回执会在实现阶段单独核验。'});snapshot();renderStudio();}
        if(action==='changes')showDrawer('草稿变更',`<div class="drawer-body"><p>基础修订 ${model.revision}，原项目 Main 和成员历史保留。</p><pre>${esc(JSON.stringify({objective:draft.objective,template:draft.template,dashboard:{bilibili:draft.bili},collectorSkill:{implementation:draft.source},schedule:{enabled:draft.daily,at:draft.dailyAt,timezone:draft.timezone},roles:(draft.plannedRoles||draft.members).map(item=>item.name)},null,2))}</pre><p class="muted">保存定义不等于登记成员、启动执行或启用真实日更。</p></div>`);
        if(action==='apply')applyDraft();
        if(action==='merge-demo'){scenario='normal';draft.revision=13;snapshot();closeDrawer();renderStudio();toast('演示合并完成。草稿保留，请再次确认应用。');}
        if(action==='phone-preview'){rememberText();phonePane=phonePane==='chat'?'preview':'chat';renderStudio();}
      };
    });
    scope.querySelectorAll('[data-global]').forEach(button=>button.onclick=()=>toast('本原型聚焦 OKR；全局入口沿用 Roami 现有导航。'));
    scope.querySelectorAll('form[data-form]').forEach(form=>{
      const field=form.querySelector('textarea'),send=form.querySelector('.send');
      field.addEventListener('input',()=>{send.disabled=!field.value.trim();if(page==='studio')write('.studioInput',field.value);else{drafts[recipientKey()]=field.value;snapshot();}});
      field.addEventListener('focus',()=>{if(phone())html.dataset.designKeyboard='open';});field.addEventListener('blur',()=>delete html.dataset.designKeyboard);
      form.onsubmit=event=>{event.preventDefault();page==='studio'?changeDraft(field.value):sendChat(field);};
      field.addEventListener('keydown',event=>{if(!phone()&&event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(field.value.trim())form.requestSubmit();}});
    });
  }
  function render(){closeDrawer();page==='studio'?renderStudio():page==='technical'?renderTechnical():renderRuntime();}
  html.dataset.theme=read('.theme','dark');html.dataset.pointer=navigator.maxTouchPoints>0?'coarse':'fine';
  const observer=new ResizeObserver(entries=>{const width=entries[0].contentRect.width,size=width<600?'compact':width<905?'medium':width<1280?'expanded':'large';if(size!==html.dataset.size){rememberText();html.dataset.size=size;render();}});observer.observe(html);
  window.addEventListener('message',event=>{if(!embedded||event.source!==parent||(event.origin!==location.origin&&location.origin!=='null')||event.data?.kind!=='roami-okr-design-draft')return;draft=copy(event.data.draft);renderRuntime();});
  window.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer();});
  window.addEventListener('pagehide',()=>{if(!resetting)rememberText();observer.disconnect();});
  Object.defineProperty(window,'__okrDesign',{value:{state:()=>copy({page,section,recipient,model,draft,scenario,scene:sceneOpen()}),reset:()=>{resetting=true;Object.keys(localStorage).filter(k=>k.startsWith(key)).forEach(k=>localStorage.removeItem(k));location.reload();}},writable:false});
  render();
})();
