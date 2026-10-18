import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseArgs, pickPage, targetIdentity, daemonRequestWithRetry, Session, navigationWait } from './driver.mjs'

const fail = (code) => { throw new Error(code) }
function page(id, broken = false) {
  const state = { detached: 0 }
  return {
    state,
    context: () => ({ newCDPSession: async () => ({
      send: async (method) => {
        assert.equal(method, 'Target.getTargetInfo')
        if (broken) throw new Error('closed')
        return { targetInfo: { targetId: id } }
      },
      detach: async () => { state.detached++ },
    }) }),
  }
}

test('stable target survives tab reordering without using the old index', async () => {
  const first = page('first'), selected = page('selected'), inserted = page('inserted')
  assert.equal(await pickPage([first, selected], { target: 'selected' }, fail), selected)
  assert.equal(await pickPage([inserted, selected, first], { target: 'selected' }, fail), selected)
  assert.equal(selected.state.detached, 2)
})

test('missing, malformed and conflicting targets never fall back to another tab', async () => {
  const first = page('first')
  await assert.rejects(pickPage([first], { target: 'missing' }, fail), /CHROME_TARGET_NOT_FOUND/)
  await assert.rejects(pickPage([first], { target: '../invalid' }, fail), /CHROME_TARGET_INVALID/)
  await assert.rejects(pickPage([first], { target: 'first', tab: 0 }, fail), /CHROME_TARGET_SELECTION_CONFLICT/)
  await assert.rejects(pickPage([first], { target: 'first', url: 'site' }, fail), /CHROME_TARGET_SELECTION_CONFLICT/)
})

test('closed pages cannot steal selection and every temporary CDP session detaches', async () => {
  const broken = page('closed', true), selected = page('selected')
  assert.equal(await pickPage([broken, selected], { target: 'selected' }, fail), selected)
  assert.equal(broken.state.detached, 1)
  await assert.rejects(targetIdentity(broken), /closed/)
  assert.equal(broken.state.detached, 2)
})

test('no-retry is a boolean and does not consume the next argument', () => {
  assert.deepEqual(parseArgs(['fill', '--no-retry', '#title', 'hello', '--target', 'stable']), {
    verb: 'fill', flags: { 'no-retry': true, target: 'stable' }, pos: ['#title', 'hello'],
  })
})


test('no-retry never repeats even an otherwise retryable transient response', async () => {
  let calls = 0
  const request = async (argv) => { assert.equal(argv[0], '_managed'); calls++; return { resp: { code: 1, stderr: 'Page crashed' } } }
  const result = await daemonRequestWithRetry(['tabs', '--no-retry'], 1000, 'tabs', request, async () => {})
  assert.equal(result.code, 1)
  assert.equal(calls, 1)
  calls = 0
  const missing = async () => { calls++; return { resp: null, sentBeforeFailure: true } }
  assert.equal(await daemonRequestWithRetry(['new', '--no-retry'], 1000, 'new', missing, async () => {}), null)
  assert.equal(calls, 1)
})


test('stable selection uses a verb an old daemon rejects before performing an action', async () => {
  let received
  const oldDaemon = async argv => {
    received = argv
    return { resp: { code: 1, stderr: 'unknown command: ' + argv[0] } }
  }
  const result = await daemonRequestWithRetry(['fill', '#name', 'hello', '--target', 'stable'], 1000, 'fill', oldDaemon)
  assert.equal(received[0], '_managed')
  assert.equal(result.code, 1)
})


test('scene and browser guards require a daemon version that understands them', async () => {
  for (const flag of ['--expected-scene', '--expected-browser']) {
    let received
    const request = async argv => { received = argv; return { resp: { code: 1, stderr: 'unsupported' } } }
    await daemonRequestWithRetry(['fill', '#name', 'hello', flag, 'expected', '--no-retry'], 1000, 'fill', request)
    assert.equal(received[0], '_scene')
  }
})

test('reusing a CDP port for another browser invalidates the cached connection', async () => {
  let current = 'first', closed = 0
  const connections = []
  const session = new Session({
    discover: async () => ({ id: current, websocketUrl: 'ws://fixture/devtools/browser/' + current }),
    connect: async url => { connections.push(url); return { isConnected: () => true, close: async () => { closed++ } } },
  })
  const first = await session.browserFor('http://fixture')
  assert.equal(await session.browserFor('http://fixture'), first)
  current = 'replacement'
  assert.notEqual(await session.browserFor('http://fixture'), first)
  assert.equal(session.browserId, 'replacement')
  assert.equal(closed, 1)
  assert.deepEqual(connections, ['ws://fixture/devtools/browser/first', 'ws://fixture/devtools/browser/replacement'])
})


test('navigation preserves load default and accepts bounded DOM-ready observation', () => {
  assert.equal(navigationWait({}), 'load')
  assert.equal(navigationWait({ 'wait-until': 'domcontentloaded' }), 'domcontentloaded')
  assert.throws(() => navigationWait({ 'wait-until': 'networkidle' }), /CHROME_NAVIGATION_WAIT_INVALID/)
})
