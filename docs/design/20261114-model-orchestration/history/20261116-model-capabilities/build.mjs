import { createRequire } from 'node:module'
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const directory = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(directory, '../../../../../frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { build } = require('esbuild')
const css = await readFile(path.join(directory, 'proposal.css'), 'utf8')
for (const kind of ['technical', 'prototype']) {
  const result = await build({
    absWorkingDir: directory,
    entryPoints: [kind === 'prototype' ? 'product-prototype.tsx' : 'proposal.tsx'],
    bundle: true,
    write: false,
    minify: true,
    jsx: 'automatic',
    nodePaths: [path.join(frontend, 'node_modules')],
    loader: { '.svg': 'dataurl' },
    define: { 'process.env.NODE_ENV': '"production"', __DOCUMENT_KIND__: JSON.stringify(kind) },
  })
  const script = result.outputFiles[0].text.replaceAll('</script', '<\\/script')
  const name = kind === 'technical' ? 'technical-design.html' : 'prototype.html'
  const title = kind === 'technical' ? '技术设计' : '原型设计'
  const styles = kind === 'prototype' ? css + '\n' + await readFile(path.join(directory, 'product-prototype.css'), 'utf8') + '\n' + await readFile(path.join(directory, 'prototype-gateway.css'), 'utf8') : css
  const html = `<!doctype html>
  <html lang="zh-CN" data-theme="dark" data-size="large" data-pointer="fine">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=overlays-content">
  <title>${title} · 模型能力与 Auto 调度 · Roami</title><style>${styles}</style></head>
  <body><div id="root"></div><script>${script}</script></body></html>\n`
  await writeFile(path.join(directory, name), html)
  if (kind === 'prototype') await writeFile(path.join(directory, 'index.html'), html)
  console.log(`Built docs/design/20261114-model-orchestration/history/20261116-model-capabilities/${name}`)
}
