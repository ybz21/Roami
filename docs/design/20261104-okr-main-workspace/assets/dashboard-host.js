(async () => {
  const script=new URL(document.currentScript.src), frame=document.querySelector('iframe');
  document.documentElement.dataset.pointer=navigator.maxTouchPoints?'coarse':'fine';
  const layout=new ResizeObserver(entries=>{const width=entries[0].contentRect.width;document.documentElement.dataset.size=width<600?'compact':width<905?'medium':width<1280?'expanded':'large';});layout.observe(document.documentElement);
  const fixture={revision:12,asOf:'2026-11-05',quality:'fresh',datasets:{'github-stars':{latest:{value:11,unit:'个'},points:[6,8,8,9,10,11,11].map((value,index)=>({date:['2026-10-30','2026-10-31','2026-11-01','2026-11-02','2026-11-03','2026-11-04','2026-11-05'][index],value}))},'github-forks':{latest:{value:5,unit:'个'},points:[2,3,3,4,4,5,5].map((value,index)=>({date:['2026-10-30','2026-10-31','2026-11-01','2026-11-02','2026-11-03','2026-11-04','2026-11-05'][index],value}))},'x-views':{latest:{value:null,unit:'次'},points:[]}}};
  const allowed=new Set(Object.keys(fixture.datasets)), subscribed=new Set();
  const nonce=crypto.randomUUID(), origin=location.origin;
  let port;
  const value=dataset=>structuredClone({...fixture.datasets[dataset],revision:fixture.revision,snapshotId:'demo-r'+fixture.revision,asOf:dataset==='x-views'?null:fixture.asOf,capturedAt:dataset==='x-views'?null:'2026-11-05T09:00:00+08:00',source:{service:dataset.startsWith('github-')?'github':'x',resource:dataset.startsWith('github-')?'ybz21/Roami':null},quality:dataset==='x-views'?'unavailable':fixture.quality,lastError:dataset==='x-views'?'来源未连接':fixture.quality==='stale'?'示例采集失败':null});
  const state=()=>{document.querySelector('[data-snapshot]').textContent='数据版本 '+fixture.revision;document.querySelector('[data-json]').textContent=JSON.stringify(fixture,null,2);};
  const push=()=>{state();for(const dataset of subscribed)port?.postMessage({type:'update',dataset,data:value(dataset)});};
  window.addEventListener('message',event=>{
    if(port || event.source!==frame.contentWindow || event.origin!=='null' || event.data?.type!=='okr:ready' || event.data?.nonce!==nonce)return;
    const channel=new MessageChannel();port=channel.port1;
    port.onmessage=event=>{
      const request=event.data;
      if(!request || !allowed.has(request.dataset)) {port.postMessage({type:'result',id:request?.id,error:'DATASET_NOT_ALLOWED'});return;}
      if(request.type==='read')port.postMessage({type:'result',id:request.id,data:value(request.dataset)});
      if(request.type==='subscribe')subscribed.add(request.dataset);
      if(request.type==='unsubscribe')subscribed.delete(request.dataset);
    };
    port.start();frame.contentWindow.postMessage({type:'okr:channel',nonce},'*',[channel.port2]);
  });
  const [sdk,html]=await Promise.all([fetch(new URL('dashboard-sdk.js',script)).then(r=>r.text()),fetch(new URL('../../20261104-okr-studio-project-ownership/dashboard-user.html',script)).then(r=>r.text())]);
  const style=getComputedStyle(document.documentElement),names=['bg-base','bg-container','border-subtle','text-bright','text-dim','accent','accent-soft','warn','fs-meta','fs-sm','fs-body','fs-lg','fs-title','r-xs','r-card','sp-1','sp-2','sp-3','sp-4','sp-5'];
  const tokens=':root{'+names.map(name=>'--'+name+':'+style.getPropertyValue('--'+name)+';').join('')+'}';
  const policy=`default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'`;
  const prefix=`<meta http-equiv="Content-Security-Policy" content="${policy}"><style>${tokens}</style><script nonce="${nonce}">window.__okrDashboardBootstrap=${JSON.stringify({origin,nonce})};${sdk}<\/script>`;
  frame.srcdoc=html.replace('</head>',prefix+'</head>').replace(/<script>/g,`<script nonce="${nonce}">`);
  document.querySelector('[data-update]').onclick=()=>{fixture.revision++;fixture.quality='fresh';fixture.datasets['github-stars'].latest.value++;fixture.datasets['github-forks'].latest.value++;for(const dataset of ['github-stars','github-forks'])fixture.datasets[dataset].points.at(-1).value=fixture.datasets[dataset].latest.value;push();};
  document.querySelector('[data-fail]').onclick=()=>{fixture.quality='stale';push();};
  document.querySelector('[data-source]').onclick=()=>{document.querySelector('[data-code]').hidden=!document.querySelector('[data-code]').hidden;};
  window.addEventListener('pagehide',()=>{port?.close();subscribed.clear();layout.disconnect();});
  window.__okrHtmlDemo={snapshot:()=>structuredClone(fixture),subscribers:()=>[...subscribed]};state();
})();
