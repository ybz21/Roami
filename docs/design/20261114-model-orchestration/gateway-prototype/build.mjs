import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
const here = path.dirname(new URL(import.meta.url).pathname)
const root = path.resolve(here, '../../../..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { build } = require('esbuild'), ts = require('typescript')
const index = await fs.readFile(path.join(root, 'frontend/src/index.css'), 'utf8')
const roots = [...index.matchAll(/:root\s*\{[^}]*\}/g)].map(match => match[0]).join('\n')
const theme = ts.createSourceFile('theme.tsx', await fs.readFile(path.join(root, 'frontend/src/theme.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let themeObject
function visit(node) { if (ts.isVariableDeclaration(node) && node.name.getText() === 'THEME_TOKENS') themeObject = node.initializer; ts.forEachChild(node, visit) }
visit(theme)
const light = themeObject.properties.find(row => row.name.getText() === 'light').initializer.properties.find(row => row.name.getText() === 'css').initializer
const lightCss = light.properties.map(row => `${row.name.text}:${row.initializer.text};`).join('')
const result = await build({ entryPoints: [path.join(here, 'entry.tsx')], bundle: true, write: false, platform: 'browser', loader: { '.svg': 'dataurl', '.template': 'text' }, format: 'iife', jsx: 'automatic', minify: true, define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent', nodePaths: [path.join(root, 'frontend/node_modules')] })
const css = await fs.readFile(path.join(here, 'styles.css'), 'utf8')
const sampleCss = await fs.readFile(path.join(here, 'workspace-samples.css'), 'utf8')
const script = result.outputFiles[0].text.replaceAll('</script', '<\\/script')
await fs.writeFile(path.join(here, '../gateway-prototype.html'), `<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content"><title>Roami · 大模型工作台原型</title><style>/* Generated tokens from index.css and theme.tsx. */${roots}html[data-theme="light"]{color-scheme:light;${lightCss}}${css}
${sampleCss}</style></head><body><div id="app"></div><script>${script}</script></body></html>`)
console.log('Built gateway-prototype.html')
