import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { createRequire } from 'node:module'
const here = path.dirname(new URL(import.meta.url).pathname), root = path.resolve(here, '../../../..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { build } = require('esbuild'), ts = require('typescript'), { renderToStaticMarkup } = require('react-dom/server')
const work = await fs.mkdtemp(path.join(os.tmpdir(), 'roami-model-design-build-'))
try {
  await build({ entryPoints: [path.join(root, 'frontend/src/icons.tsx')], bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', loader: { '.svg': 'text' }, outfile: path.join(work, 'icons.cjs'), logLevel: 'silent' })
  const exported = require(path.join(work, 'icons.cjs')), names = ['PlusIcon','CloseIcon','CheckIcon','CopyIcon','ChevronLeft','ChevronRight','ChevronDown','LinkIcon','SearchIcon','DragHandleIcon','MoreIcon','ShieldIcon','ClockIcon','PencilIcon','MicrophoneIcon','MoonIcon','SunIcon','GearIcon','HomeIcon','BlockIcon']
  const icons = Object.fromEntries(names.map(name => [name, renderToStaticMarkup(exported[name]({ size: 18 }))]))
  const index = await fs.readFile(path.join(root, 'frontend/src/index.css'), 'utf8')
  const roots = [...index.matchAll(/:root\s*\{[^}]*\}/g)].map(match => match[0]).join('\n')
  const theme = ts.createSourceFile('theme.tsx', await fs.readFile(path.join(root, 'frontend/src/theme.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let themeObject
  function visit(node) { if (ts.isVariableDeclaration(node) && node.name.getText() === 'THEME_TOKENS') themeObject = node.initializer; ts.forEachChild(node, visit) }
  visit(theme)
  const light = themeObject.properties.find(row => row.name.getText() === 'light').initializer.properties.find(row => row.name.getText() === 'css').initializer
  const lightCss = light.properties.map(row => `${row.name.text}:${row.initializer.text};`).join('')
  const result = await build({ entryPoints: [path.join(here, 'entry.tsx')], bundle: true, write: false, platform: 'browser', format: 'iife', jsx: 'automatic', minify: true, define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent', nodePaths: [path.join(root, 'frontend/node_modules')] })
  const css = await fs.readFile(path.join(here, 'styles.css'), 'utf8'), script = result.outputFiles[0].text.replaceAll('</script', '<\\/script')
  const html = `<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Roami · Model interaction prototype</title><style>/* Tokens copied from frontend/src/index.css and theme.tsx; do not edit generated values. */${roots}html[data-theme="light"]{color-scheme:light;${lightCss}}${css}</style></head><body><div id="layout-observer" hidden></div><div id="app"></div><div id="notice" role="status" aria-live="polite"></div><script>/* Icons serialized from frontend/src/icons.tsx. */window.roamiDesignIcons=${JSON.stringify(icons)};</script><script>${script}</script></body></html>`
  await fs.writeFile(path.join(here, '../history/prototypes/interaction-prototype.html'), html)
  console.log(`Built offline prototype (${Math.round(Buffer.byteLength(html) / 1024)} KiB)`)
} finally { await fs.rm(work, { recursive: true, force: true }) }
