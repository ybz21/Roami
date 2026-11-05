import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(new URL('../quality/python-check-plan.mjs', import.meta.url))
const suites = ['runtime', 'presentation', 'tabular', 'market', 'video']
const gitVariables = execFileSync('git', ['rev-parse', '--local-env-vars'], { encoding: 'utf8' }).trim().split('\n')
const environment = { ...process.env }
for (const key of [...gitVariables, 'QUALITY_BASE_SHA', 'QUALITY_HEAD_SHA', 'GITHUB_OUTPUT']) delete environment[key]

function fixture(t) {
  const directory = mkdtempSync(path.join(tmpdir(), 'roami-python-plan-'))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  const git = (...args) => execFileSync('git', args, { cwd: directory, env: environment, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
  const write = (name, value = 'changed\n') => { mkdirSync(path.dirname(path.join(directory, name)), { recursive: true }); writeFileSync(path.join(directory, name), value) }
  git('init', '-q', '-b', 'main')
  git('config', 'user.name', 'Scope Fixture'); git('config', 'user.email', 'scope@example.invalid'); git('config', 'core.hooksPath', '/dev/null')
  for (const name of ['README.md', 'frontend/page.tsx', 'agent-runtime/src/agent.py', 'agent-runtime/src/commands.json', 'agent-runtime/migrations/0001.sql', 'agent-runtime/uv.lock', 'tools/contract.py', '.github/workflows/quality.yml', 'scripts/dev/quality/check.sh', ...['presentation-edit', 'tabular-analysis', 'market-series-report', 'video-assembly'].map(skill => 'skills/' + skill + '/scripts/main.py')]) write(name, 'initial\n')
  git('add', '.'); git('commit', '-qm', 'initial'); git('update-ref', 'refs/remotes/origin/main', 'HEAD')
  const base = git('rev-parse', 'HEAD')
  const invoke = (mode = 'full', extra = {}, format) => spawnSync(process.execPath, [script, mode, ...(format ? [format] : [])], { cwd: directory, env: { ...environment, ...extra }, encoding: 'utf8' })
  const plan = (mode, extra) => { const value = invoke(mode, extra); assert.equal(value.status, 0, value.stderr); return JSON.parse(value.stdout) }
  return { directory, git, write, base, invoke, plan }
}
function expect(plan, enabled, go = enabled.includes('runtime')) {
  assert.deepEqual(Object.fromEntries(suites.map(key => [key, plan[key]])), Object.fromEntries(suites.map(key => [key, enabled.includes(key)])))
  assert.equal(plan.go, go)
  assert.equal(plan.python, go || enabled.length > 0)
}

for (const [name, selected] of [
  ['frontend/page.tsx', []], ['README.md', []],
  ['agent-runtime/src/agent.py', ['runtime']], ['agent-runtime/src/commands.json', ['runtime']], ['agent-runtime/migrations/0001.sql', ['runtime']],
  ['agent-runtime/README.md', []], ['agent-runtime/README.py', ['runtime']], ['agent-runtime/docs/example.py', ['runtime']],
  ['skills/presentation-edit/SKILL.md', ['presentation']], ['skills/tabular-analysis/input/schema.json', ['tabular']],
  ['skills/market-series-report/scripts/main.py', ['market']], ['skills/video-assembly/pyproject.toml', ['video']],
  ['agent-runtime/uv.lock', suites], ['requirements-dev.txt', suites], ['pytest.ini', suites], ['cases/case-99/input.csv', suites],
  ['skills/unmapped/input.png', suites], ['tools/contract.py', suites],
]) {
  test('selects complete affected suites for ' + name, t => {
    const f = fixture(t); f.write(name); f.git('add', '--', name)
    expect(f.plan('quick'), selected); expect(f.plan('full'), selected)
  })
}
for (const name of ['.github/workflows/quality.yml', 'scripts/dev/quality/check.sh', 'scripts/dev/selftest/python-check-plan.test.mjs']) {
  test('quick validates dispatch fixtures; full exercises pipeline changes: ' + name, t => {
    const f = fixture(t); f.write(name); f.git('add', '--', name)
    expect(f.plan('quick'), []); expect(f.plan('full'), suites)
  })
}
for (const [skill, selected] of [['presentation-edit', 'presentation'], ['tabular-analysis', 'tabular'], ['market-series-report', 'market'], ['video-assembly', 'video']]) {
  test('deleted skill program still selects ' + skill, t => {
    const f = fixture(t); f.git('rm', '--', 'skills/' + skill + '/scripts/main.py'); expect(f.plan('quick'), [selected])
  })
}
test('renaming a resource across skills tests both the deleted and added path', t => {
  const f = fixture(t); f.git('mv', 'skills/presentation-edit/scripts/main.py', 'skills/video-assembly/scripts/moved.py')
  expect(f.plan('quick'), ['presentation', 'video'])
})
test('renaming Python to text cannot hide the removed runtime program', t => {
  const f = fixture(t); f.git('mv', 'agent-runtime/src/agent.py', 'agent-runtime/src/agent.txt'); expect(f.plan('quick'), ['runtime'])
})
test('untracked and unstaged changes enter full but not an unrelated staged commit', t => {
  const f = fixture(t); f.write('frontend/page.tsx'); f.git('add', 'frontend/page.tsx'); f.write('agent-runtime/src/agent.py'); f.write('skills/video-assembly/input/new.json')
  expect(f.plan('quick'), []); expect(f.plan('full'), ['runtime', 'video'])
})
test('committed PR range is complete while a later frontend-only push is narrow', t => {
  const f = fixture(t); f.write('agent-runtime/src/agent.py'); f.git('add', '.'); f.git('commit', '-qm', 'runtime')
  const prior = f.git('rev-parse', 'HEAD'); f.write('frontend/page.tsx'); f.git('add', '.'); f.git('commit', '-qm', 'frontend')
  expect(f.plan('full'), ['runtime'])
  expect(f.plan('full', { QUALITY_BASE_SHA: f.base, QUALITY_HEAD_SHA: 'HEAD' }), ['runtime'])
  expect(f.plan('full', { QUALITY_BASE_SHA: prior, QUALITY_HEAD_SHA: 'HEAD' }), [])
})
test('paths with newlines do not corrupt the NUL-delimited comparison', t => {
  const f = fixture(t); const name = 'skills/presentation-edit/input/new\nslide.json'; f.write(name); f.git('add', '--', name); expect(f.plan('quick'), ['presentation'])
})
for (const extra of [{ QUALITY_BASE_SHA: 'missing' }, { QUALITY_BASE_SHA: 'HEAD', QUALITY_HEAD_SHA: 'missing' }, { PATH: '/path-without-git' }]) {
  test('unavailable comparison selects every check: ' + JSON.stringify(extra), t => {
    const f = fixture(t); const value = f.plan('full', extra); expect(value, suites); assert.equal(value.reason, 'comparison-unavailable')
  })
}
test('new repository without commit history never silently skips', t => {
  const f = fixture(t); f.git('update-ref', '-d', 'refs/heads/main'); f.git('update-ref', '-d', 'refs/remotes/origin/main'); expect(f.plan('full'), suites)
})
test('release runs every suite even on a clean tree', t => {
  const f = fixture(t); expect(f.plan('full'), []); expect(f.plan('release'), suites)
})
test('Go-only changes retain Python-backed Go regressions without the runtime pytest suite', t => {
  const f = fixture(t); f.write('internal/agentexecution/service.go'); f.git('add', '.')
  expect(f.plan('quick'), [], true); expect(f.plan('full'), [], true)
})
test('GitHub outputs use the same plan as local checks', t => {
  const f = fixture(t); f.write('skills/video-assembly/scripts/main.py'); f.git('add', '.')
  const output = path.join(f.directory, 'github output.txt'); const value = f.invoke('full', { GITHUB_OUTPUT: output }, '--github-output')
  assert.equal(value.status, 0, value.stderr); expect(JSON.parse(value.stdout), ['video'])
  const lines = readFileSync(output, 'utf8'); assert.match(lines, /^video=true$/m); assert.match(lines, /^runtime=false$/m); assert.match(lines, /^python=true$/m)
})
test('invalid mode or missing GitHub output is an error, never a skip receipt', t => {
  const f = fixture(t); assert.notEqual(f.invoke('skip').status, 0); assert.notEqual(f.invoke('full', {}, '--github-output').status, 0)
})
