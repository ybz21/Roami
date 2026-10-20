import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import react from '@vitejs/plugin-react'

const root = fileURLToPath(new URL('../../', import.meta.url))
const frontend = path.join(root, 'frontend')
const outputPath = path.resolve(process.argv[2] || '/tmp/capabilities-design.html')
const prototypePath = path.join(path.dirname(outputPath), 'capabilities-prototype.html')
const result = await build({
  root: frontend, configFile: false, logLevel: 'warn',
  plugins: [{ name: 'prototype-markdown', enforce: 'pre', resolveId(source) { if (source.endsWith('/markdown/Markdown')) return path.join(frontend, 'prototypes/prototype-markdown.tsx') } }, react()],
  build: { write: false, target: 'es2020', assetsInlineLimit: Infinity, cssCodeSplit: false, chunkSizeWarningLimit: 2500, rollupOptions: { input: path.join(frontend, 'prototypes/capabilities.tsx'), output: { inlineDynamicImports: true } } },
})
const chunks = result.output
const js = chunks.filter(item => item.type === 'chunk').map(item => item.code).join('\n').replace(/<\/script/gi, '<\\/script')
const css = chunks.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')
const prototype = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,interactive-widget=overlays-content"><title>能力中心 · 交互原型</title><style>${css}</style></head><body><div id="root"></div><script type="module">${js}</script></body></html>`
await writeFile(prototypePath, prototype)
const agents = await readFile(path.join(root, 'AGENTS.md'), 'utf8')
const section = agents.slice(agents.indexOf('<section id="capabilities-hub-design"'), agents.lastIndexOf('</section>') + 10)
const product = section.slice(section.indexOf('<h2 id="capability-product-design"'), section.indexOf('<h2 id="capability-user-stories"')).replace(/<div id="capability-prototype-embed">[\s\S]*?<\/div>/, '')
const stories = section.slice(section.indexOf('<h2 id="capability-user-stories"'), section.indexOf('<h2 id="capability-technical-design"'))
const technical = section.slice(section.indexOf('<h2 id="capability-technical-design"'), section.lastIndexOf('</section>'))
const baseCss = await readFile(path.join(frontend, 'src/index.css'), 'utf8')
const tokenStart = baseCss.indexOf(':root {')
const tokens = baseCss.slice(tokenStart, baseCss.indexOf('\n}', tokenStart) + 2)
const serialized = JSON.stringify(prototype).replace(/</g, '\\u003c')
const html = `<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>能力中心 · 设计与交互原型</title><style>
${tokens}
:root{--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:24px;--fs-meta:12px;--fs-sm:13px;--fs-body:14px;--fs-lg:16px;--fs-title:22px;--r-xs:6px;--r-sm:10px;--r-card:14px;--tap:44px;--content-form:920px}
*{box-sizing:border-box}html,body{height:100%;margin:0;overflow:hidden}body{display:flex;flex-direction:column;font:var(--fs-body)/1.6 Inter,system-ui,sans-serif;background:var(--bg-base);color:var(--text-bright)}
html[data-theme="light"]{--bg-base:#f6f8fa;--bg-container:#fff;--bg-elevated:#fff;--text-bright:#1f2328;--text-dim:#57606a;--text-dimmer:#8c959f;--border:#d0d7de;--border-subtle:#e6e9ec;--accent:#0969da;--sel-bg:rgb(27 31 36 / 5.5%)}
header{display:flex;align-items:center;gap:var(--sp-4);flex-wrap:wrap;padding:var(--sp-4) var(--sp-5);border-bottom:1px solid var(--border-subtle)}header strong{font-size:var(--fs-lg)}header span{font-size:var(--fs-meta);color:var(--text-dim)}nav{display:flex;align-items:center;gap:var(--sp-1);flex-wrap:wrap;margin-left:auto}
button,a{font:inherit}button{min-height:var(--tap);padding:var(--sp-2) var(--sp-3);border:1px solid transparent;border-radius:var(--r-xs);color:var(--text-dim);background:transparent;cursor:pointer}button[aria-pressed="true"]{color:var(--accent);background:var(--sel-bg)}button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:var(--sp-1)}
main{flex:1;min-height:0;display:flex;flex-direction:column}.view{display:none;min-height:0;flex:1}.view.active{display:flex;flex-direction:column}.controls{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;padding:var(--sp-2) var(--sp-5);border-bottom:1px solid var(--border-subtle)}.controls small{color:var(--text-dim);font-size:var(--fs-meta);margin-right:auto}.controls a{color:var(--accent);font-size:var(--fs-sm);padding:var(--sp-2)}
.stage{flex:1;min-height:0;display:flex;justify-content:center;padding:var(--sp-4);overflow:hidden}iframe{height:100%;width:100%;border:1px solid var(--border-subtle);background:var(--bg-base)}.stage.phone iframe{width:390px;max-width:100%;border-radius:var(--r-card)}.document{flex:1;min-height:0;overflow:auto;padding:var(--sp-5)}article{max-width:var(--content-form);margin:auto}h2{font-size:var(--fs-title);margin:0 0 var(--sp-5)}h3{font-size:var(--fs-lg);margin:var(--sp-5) 0 var(--sp-3)}p,li{color:var(--text-dim)}li{margin:var(--sp-2) 0}pre{padding:var(--sp-4);background:var(--bg-container);border:1px solid var(--border-subtle);border-radius:var(--r-sm);overflow:auto;font-size:var(--fs-sm)}a{color:var(--accent)}
</style></head><body><header><strong>能力中心</strong><span>设计与交互原型 · 2026.10.21</span><nav aria-label="设计章节"><button type="button" data-view="prototype" aria-pressed="true">交互原型</button><button type="button" data-view="product" aria-pressed="false">产品设计</button><button type="button" data-view="stories" aria-pressed="false">用户故事</button><button type="button" data-view="technical" aria-pressed="false">技术设计</button></nav></header><main>
<section class="view active" id="prototype"><div class="controls"><small>可切换分类、上传文件、新建、编辑与保存；数据仅供本页演示。</small><button type="button" data-device="desktop" aria-pressed="true">桌面</button><button type="button" data-device="phone" aria-pressed="false">手机</button><button type="button" id="theme">切换浅色</button><button type="button" id="language">English</button><a href="${path.basename(prototypePath)}" download>下载独立原型</a></div><div class="stage"><iframe title="能力中心可交互原型" sandbox="allow-scripts allow-forms allow-downloads"></iframe></div></section>
<section class="view" id="product"><div class="document"><article>${product}</article></div></section><section class="view" id="stories"><div class="document"><article>${stories}</article></div></section><section class="view" id="technical"><div class="document"><article>${technical}</article></div></section></main><script>
const frame=document.querySelector('iframe');const settings={theme:'dark',locale:'zh-CN'};frame.srcdoc=${serialized};function send(tab){frame.contentWindow.postMessage({type:'capability-prototype-settings',...settings,...(tab?{tab}:{})},'*')}window.addEventListener('message',e=>{if(e.source===frame.contentWindow&&e.data?.type==='capability-prototype-ready')send(new URLSearchParams(location.search).get('tab'))});
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-view]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));document.querySelectorAll('.view').forEach(view=>view.classList.toggle('active',view.id===button.dataset.view))});document.querySelectorAll('[data-device]').forEach(button=>button.onclick=()=>{document.querySelector('.stage').classList.toggle('phone',button.dataset.device==='phone');document.querySelectorAll('[data-device]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)))});document.querySelector('#theme').onclick=()=>{settings.theme=settings.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=settings.theme;document.querySelector('#theme').textContent=settings.theme==='dark'?'切换浅色':'切换深色';send()};document.querySelector('#language').onclick=()=>{settings.locale=settings.locale==='zh-CN'?'en-US':'zh-CN';document.querySelector('#language').textContent=settings.locale==='zh-CN'?'English':'中文';send()};
</script></body></html>`
await writeFile(outputPath, html)
console.log(`Design: ${outputPath}\nPrototype: ${prototypePath}\nSingle-file prototype: ${Math.round(Buffer.byteLength(prototype) / 1024)} KiB`)
