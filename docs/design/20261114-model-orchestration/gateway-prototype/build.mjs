import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { gzipSync } from 'node:zlib'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(here, '../../../../frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { build } = require('esbuild')
const { outputFiles } = await build({
  entryPoints: [path.join(here, 'entry.tsx')],
  outfile: path.join(here, 'prototype.js'),
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'iife',
  minify: true,
  jsx: 'automatic',
  loader: { '.svg': 'dataurl', '.woff': 'dataurl', '.woff2': 'dataurl', '.png': 'dataurl' },
  define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false', localStorage: 'prototypeStorage' },
  inject: [path.join(here, 'storage.ts')],
  nodePaths: [path.join(frontend, 'node_modules')],
})
const script = outputFiles.find(file => file.path.endsWith('.js')).contents
const bundle = gzipSync(script).toString('base64').match(/.{1,120}/g).join('\n')
const css = outputFiles.find(file => file.path.endsWith('.css')).text
const html = `<!doctype html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<title>Roami · 大模型工作台原型</title>
<style>${css}</style>
</head>
<body>
<div id="root"></div>
<script id="prototype-bundle" type="application/octet-stream">
${bundle}
</script>
<script>
(async () => {
  const bundle = document.getElementById('prototype-bundle')
  const bytes = Uint8Array.from(atob(bundle.textContent), character => character.charCodeAt(0))
  bundle.remove()
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))
  const app = document.createElement('script')
  app.textContent = await new Response(stream).text()
  document.body.appendChild(app)
})().catch(() => {
  document.getElementById('root').textContent = '页面加载失败，请使用最新版 Chrome 或 Edge。'
})
</script>
</body>
</html>
`
await fs.writeFile(path.join(here, '../gateway-prototype.html'), html)
console.log('Built gateway-prototype.html')
