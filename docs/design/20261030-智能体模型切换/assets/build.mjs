import { readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const directory = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(directory, '../../../..')
const frontend = path.join(root, 'frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { build } = await import(path.join(path.dirname(require.resolve('vite/package.json')), 'dist/node/index.js'))
const { default: react } = await import(path.join(path.dirname(require.resolve('@vitejs/plugin-react')), 'index.js'))
const result = await build({
  root: frontend, configFile: false, logLevel: 'warn', plugins: [react()],
  resolve: { alias: { react: path.dirname(require.resolve('react/package.json')), 'react-dom': path.dirname(require.resolve('react-dom/package.json')), antd: path.dirname(require.resolve('antd/package.json')) } },
  build: { write: false, target: 'es2020', cssCodeSplit: false, assetsInlineLimit: Infinity, rollupOptions: { input: path.join(directory, 'prototype.tsx'), output: { inlineDynamicImports: true } } },
})
const script = result.output.filter(item => item.type === 'chunk').map(item => item.code).join('\n').replace(/<\/script/gi, '<\\/script')
const styles = result.output.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n')
const baseCss = await readFile(path.join(frontend, 'src/index.css'), 'utf8')
const tokens = [...baseCss.matchAll(/:root\s*\{[^}]*\}/g)].slice(0, 2).map(match => match[0]).join('\n')
const baseColor = tokens.match(/--bg-base:\s*([^;]+);/)[1]
const output = path.join(directory, '../index.html')
await writeFile(output, `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=overlays-content"><meta name="theme-color" content="${baseColor}"><title>能力中心 · 大模型与智能体 · 第二版</title><style>${tokens}\n${styles}</style></head><body><div id="root"></div><script type="module">${script}</script></body></html>`)
console.log(`Built ${path.relative(root, output)}`)
