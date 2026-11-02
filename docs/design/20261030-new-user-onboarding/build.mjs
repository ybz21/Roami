import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const directory = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(directory, '../../../frontend')
const { build } = await import(path.join(frontend, 'node_modules/vite/dist/node/index.js'))
const { default: react } = await import(path.join(frontend, 'node_modules/@vitejs/plugin-react/dist/index.js'))
const result = await build({
  root: frontend, configFile: false, logLevel: 'warn', plugins: [react()],
  resolve: { alias: { react: path.join(frontend, 'node_modules/react'), 'react-dom': path.join(frontend, 'node_modules/react-dom'), antd: path.join(frontend, 'node_modules/antd') } },
  build: { write: false, target: 'es2020', assetsInlineLimit: Infinity, cssCodeSplit: false,
    chunkSizeWarningLimit: 3000, rollupOptions: { input: path.join(directory, 'prototype.tsx'), output: { inlineDynamicImports: true } } },
})
const css = result.output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')
const script = result.output.filter(item => item.type === 'chunk').map(item => item.code).join('\n').replace(/<\/script/gi, '<\\/script')
const base = await readFile(path.join(frontend, 'src/index.css'), 'utf8')
const tokens = [...base.matchAll(/:root \{[\s\S]*?\n\}/g)].slice(0, 2).map(match => match[0]).join('\n')
await writeFile(path.join(directory, 'index.html'), `<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=overlays-content"><meta name="theme-color" content="#0d1117"><title>新用户引导 · Roami 设计预览</title><style>${tokens}\n${css}</style></head><body><div id="root"></div><script type="module">${script}</script></body></html>`)
console.log('Built docs/design/20261030-new-user-onboarding/index.html')
