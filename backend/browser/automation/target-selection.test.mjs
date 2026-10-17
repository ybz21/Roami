import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseArgs, pickPage, targetIdentity, daemonRequestWithRetry } from './driver.mjs'

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
