import { createRequire } from 'node:module'
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const directory = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(directory, '../../../frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { build } = require('esbuild')
for (const target of [{entry:'prototype.tsx',file:'prototype.html',title:'OKR 面板 · Roami 交互原型',styles:['prototype.css']},{entry:'interaction-book.tsx',file:'interaction-design.html',title:'从目标到每天的行动 · Roami 交互设计书',styles:['prototype.css','interaction-book.css']}]) {
  const result = await build({ entryPoints: [path.join(directory,target.entry)], bundle: true, minify: true, write: false, jsx: 'automatic', format: 'iife', target: 'es2022', define: { 'process.env.NODE_ENV': '"production"' }, nodePaths: [path.join(frontend, 'node_modules')], loader: { '.svg': 'dataurl' }, legalComments: 'inline' })
  const script = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script')
  const css = (await Promise.all(target.styles.map(file => readFile(path.join(directory,file),'utf8')))).join('\n')
  await writeFile(path.join(directory,target.file), `<!doctype html>
<html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=overlays-content"><meta name="color-scheme" content="dark light"><title>${target.title}</title><style>${css}</style></head><body><div id="root"></div><noscript>此交互设计需要启用 JavaScript。产品设计可从同目录 index.html 阅读。</noscript><script>${script}</script></body></html>`)
  console.log(`Built standalone ${target.file}; no network or API dependencies.`)
}
