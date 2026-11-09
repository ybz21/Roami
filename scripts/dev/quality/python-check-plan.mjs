#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { appendFileSync } from 'node:fs'

const [mode = 'full', format = 'json'] = process.argv.slice(2)
if (!['quick', 'full', 'release'].includes(mode) || !['json', '--runtime', '--lines', '--github-output'].includes(format)) {
  throw new Error('Usage: python-check-plan.mjs quick|full|release [--runtime|--lines|--github-output]')
}
const suites = ['runtime', 'presentation', 'tabular', 'market', 'video']
const plan = Object.fromEntries(suites.map(name => [name, false]))
plan.go = false
const all = () => { suites.forEach(name => { plan[name] = true }); plan.go = true }
const git = (...args) => execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
const paths = text => text.split('\0').filter(Boolean)
let reason = mode

function changedPaths() {
  if (process.env.QUALITY_BASE_SHA) {
    return paths(git('diff', '--name-only', '--no-renames', '-z', process.env.QUALITY_BASE_SHA, process.env.QUALITY_HEAD_SHA || 'HEAD'))
  }
  const staged = paths(git('diff', '--cached', '--name-only', '--no-renames', '-z'))
  if (mode === 'quick' && staged.length) return staged
  let base
  for (const reference of ['refs/remotes/origin/main', 'refs/heads/main']) {
    try { base = git('merge-base', 'HEAD', reference).trim(); break } catch {}
  }
  if (!base) base = git('rev-parse', '--verify', 'HEAD^').trim()
  return [
    ...paths(git('diff', '--name-only', '--no-renames', '-z', base, 'HEAD')),
    ...paths(git('diff', '--name-only', '--no-renames', '-z', 'HEAD')),
    // Runtime tests create bytecode outside ignored directories; it is not new source.
    ...paths(git('ls-files', '--others', '--exclude-standard', '-z')).filter(path => !path.endsWith('.pyc') && !path.endsWith('.pyo')),
  ]
}

function select(path) {
  const skill = [
    ['skills/presentation-edit/', 'presentation'],
    ['skills/tabular-analysis/', 'tabular'],
    ['skills/market-series-report/', 'market'],
    ['skills/video-assembly/', 'video'],
  ].find(([prefix]) => path.startsWith(prefix))
  if (skill) { plan[skill[1]] = true; return }
  if (/^scripts\/dev\/quality\/|^scripts\/dev\/selftest\/python-check-/.test(path)
    || /^\.github\/workflows\/(?:quality|release[^/]*)\.ya?ml$/.test(path)) {
    // Quick exercises dispatch fixtures; full reenacts the entire changed pipeline.
    if (mode !== 'quick') all()
    return
  }
  // All four skill suites use the runtime environment and canonical case fixtures.
  if (/^cases\/|^skills\/|^scripts\/build\/|^scripts\/install\/|^\.githooks\/|^\.github\/actions\//.test(path)
    || /(^|\/)(?:pyproject\.toml|uv\.lock|uv\.toml|\.uv\.toml|pytest\.ini|tox\.ini|ruff\.toml|\.ruff\.toml|\.python-version|requirements[^/]*\.txt)$/.test(path)) {
    all(); return
  }
  if (path.startsWith('agent-runtime/')) {
    const prose = !/\.pyi?$/.test(path) && /^agent-runtime\/(?:docs\/|README(?:\.(?:md|rst|txt))?$)/.test(path)
    if (!prose) { plan.runtime = true; plan.go = true }
    return
  }
  if (/^(?:backend|internal|cmd|pkg|plugins)\//.test(path) || /(^|\/)go\.(?:mod|sum)$/.test(path)) { plan.go = true; return }
  if (/\.pyi?$/.test(path)) { all(); return }
  if (/^(?:frontend|docs)\//.test(path) || /\.(?:md|rst|txt)$/.test(path) || ['LICENSE', '.github/workflows/frontend-i18n.yml'].includes(path)) return
  all()
}

if (mode === 'release') all()
else {
  try { for (const path of changedPaths()) select(path) }
  catch { all(); reason = 'comparison-unavailable' }
}
// Go execution tests launch the Python harness even without a runtime pytest run.
plan.python = plan.go || suites.some(name => plan[name])
plan.reason = reason
const lines = Object.entries(plan).map(([key, value]) => key + '=' + value).join('\n') + '\n'
if (format === '--runtime') console.log(plan.runtime)
else if (format === '--lines') process.stdout.write(lines)
else {
  if (format === '--github-output') {
    if (!process.env.GITHUB_OUTPUT) throw new Error('GITHUB_OUTPUT is required')
    appendFileSync(process.env.GITHUB_OUTPUT, lines)
  }
  console.log(JSON.stringify(plan))
}
