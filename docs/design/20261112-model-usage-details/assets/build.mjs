import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const directory = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(directory, '../../../..')
const dependencyRoot = process.env.ROAMI_PROTOTYPE_DEPS || path.join(root, 'frontend')
const require = createRequire(path.join(dependencyRoot, 'package.json'))
const { build } = require('esbuild')
const entry = process.argv[2] === 'interaction-review' ? 'interaction-review' : 'prototype'
const result = await build({
  entryPoints: [path.join(directory, entry + '.tsx')], bundle: true, write: false,
  minify: true, jsx: 'automatic', target: 'es2020', format: 'iife',
  nodePaths: [path.join(dependencyRoot, 'node_modules')], loader: { '.svg': 'dataurl' },
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{name:'prototype-local-preferences', setup(build) {
    build.onResolve({filter:/^\.\.\/preferences$/}, args => args.importer.endsWith('/i18n/index.tsx') ? {path:'prototype-preferences',namespace:'prototype'} : undefined)
    build.onLoad({filter:/.*/,namespace:'prototype'}, () => ({contents:'const defaults={locale:""}; export const usePreferences=()=>[defaults,savePreferences]; export const savePreferences=()=>Promise.resolve(true);'}))
  }}],
})
const base = await readFile(path.join(root,'frontend/src/index.css'),'utf8')
const rootBlocks = [...base.matchAll(/:root \{[\s\S]*?\n\}/g)].slice(0,2).map(match=>match[0]).join('\n')
const theme = await readFile(path.join(root,'frontend/src/theme.tsx'),'utf8')
const themes = ['dark','light'].map(mode => {
  const section=theme.split(`  ${mode}: {\n    css: {`)[1].split('\n    },')[0]
  return `html[data-theme="${mode}"]{${[...section.matchAll(/'(--[^']+)': '([^']*)'/g)].map(([,key,value])=>`${key}:${value};`).join('')}}`
}).join('\n')
const css = await readFile(path.join(directory,entry + '.css'),'utf8')
const html = `<!doctype html><html lang="zh-CN" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=overlays-content"><meta name="theme-color" content="#f6f8fa"><title>概况与审计 · Roami</title><style>${rootBlocks}\n${themes}\n${css}</style></head><body><div id="root"></div><script>${result.outputFiles[0].text.replace(/<\/script/gi,'<\\/script')}</script></body></html>`
const output=path.join(directory,'../' + entry + '.html')
await writeFile(output,html)
console.log(`${output} (${Math.round(Buffer.byteLength(html)/1024)} KiB)`)
