import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import { ScopedCDP, selectTarget } from './scoped-cdp.mjs'
import { Session } from './driver.mjs'

function transport(timeoutMs = 1000) {
  const sent = [], delivered = []
  const socket = new EventEmitter()
  socket.send = data => sent.push(JSON.parse(data))
  socket.close = () => socket.emit('close')
  const connection = new ScopedCDP(socket, { timeoutMs })
  connection.targetId = 'owned'
  connection.onmessage = message => delivered.push(message)
  return { socket, connection, sent, delivered }
}

test('cold connection attaches exactly the selected target before acknowledging readiness', async () => {
  const f = transport()
  f.connection.send({ id: 1, method: 'Target.setAutoAttach', params: { autoAttach: true, flatten: true, waitForDebuggerOnStart: true } })
  assert.deepEqual(f.sent[0].params.filter, [{ exclude: true }])
  assert.equal(f.sent[0].params.waitForDebuggerOnStart, false)
  const readiness = f.connection.receive({ id: 1, result: {} })
  const attach = f.sent[1]
  assert.equal(attach.method, 'Target.attachToTarget')
  assert.deepEqual(attach.params, { targetId: 'owned', flatten: true })
  assert.deepEqual(f.delivered, [])
  const event = { method: 'Target.attachedToTarget', params: { sessionId: 'selected', targetInfo: { targetId: 'owned' } } }
  await f.connection.receive(event)
  await f.connection.receive({ id: attach.id, result: { sessionId: 'selected' } })
  await readiness
  assert.deepEqual(f.delivered, [event, { id: 1, result: {} }])
  f.connection.close()
})

test('selected-page iframe sessions keep their original auto-attach behavior', () => {
  const f = transport()
  const request = { id: 10, sessionId: 'selected-page', method: 'Target.setAutoAttach', params: { autoAttach: true, flatten: true, waitForDebuggerOnStart: true } }
  f.connection.send(request)
  assert.deepEqual(f.sent, [request])
  f.connection.close()
})

test('a vanished target fails connection and never falls back to another page', async () => {
  const f = transport()
  f.connection.send({ id: 1, method: 'Target.setAutoAttach', params: { autoAttach: true } })
  const readiness = f.connection.receive({ id: 1, result: {} })
  await f.connection.receive({ id: f.sent[1].id, error: { message: 'No target with given id found' } })
  await readiness
  assert.match(f.delivered[0].error.message, /No target/)
  assert.equal(f.sent.filter(r => r.method === 'Target.attachToTarget').length, 1)
  f.connection.close()
})

test('control requests stop on disconnect or timeout, without replay or late replies', async () => {
  const f = transport(20)
  const pending = f.connection.request('Target.createTarget', { url: 'about:blank' })
  const rejected = assert.rejects(pending, /CHROME_CONNECTION_CLOSED/)
  f.connection.close()
  await rejected
  const g = transport(20)
  await assert.rejects(g.connection.request('Target.createTarget'), /CHROME_CONNECTION_TIMEOUT/)
  await g.connection.receive({ id: g.sent[0].id, result: { targetId: 'late' } })
  assert.equal(g.sent.length, 1)
  assert.deepEqual(g.delivered, [])
  g.connection.close()
})

test('stable target selection rejects conflicts, disappearance and malformed IDs', () => {
  const targets = [{ targetId: 'first', url: 'https://one.test' }, { targetId: 'second', url: 'https://two.test' }]
  assert.equal(selectTarget(targets, { target: 'second' }).targetId, 'second')
  assert.equal(selectTarget([...targets].reverse(), { target: 'second' }).targetId, 'second')
  assert.equal(selectTarget(targets, { tab: 1 }).targetId, 'second')
  assert.equal(selectTarget(targets, { url: 'two.test' }).targetId, 'second')
  assert.throws(() => selectTarget(targets, { target: 'missing' }), /CHROME_TARGET_NOT_FOUND/)
  assert.throws(() => selectTarget(targets, { target: '../bad' }), /CHROME_TARGET_INVALID/)
  assert.throws(() => selectTarget(targets, { target: 'first', tab: 0 }), /CHROME_TARGET_SELECTION_CONFLICT/)
})

test('capabilities and new background tabs do not initialize existing renderers', async () => {
  const requests = [], output = []
  const session = new Session({
    discover: async () => ({ id: 'browser', websocketUrl: 'ws://fixture' }),
    connect: async () => { throw new Error('unrelated renderer must not be initialized') },
    control: async () => ({ close: () => {}, request: async (method, params) => {
      requests.push({ method, params })
      if (method === 'Target.getTargets') return { targetInfos: [{ type: 'page', targetId: 'busy', url: 'https://busy.test', title: 'Busy' }] }
      if (method === 'Target.createTarget') return { targetId: 'new-owned' }
      return {}
    } }),
  })
  try {
    const io = { log: value => output.push(value) }
    await session.run('capabilities', {}, [], 0, io)
    await session.run('tabs', {}, [], 0, io)
    await session.run('new', { 'no-focus': true }, [], 0, io)
    assert.equal(output[0].browserId, 'browser')
    assert.equal(output[1][0].targetId, 'busy')
    assert.equal(output[2].targetId, 'new-owned')
    assert.equal(requests.filter(r => r.method === 'Target.createTarget').length, 1)
  } finally { await session.close() }
})

test('closing during selected-target initialization does not deliver messages after disconnect', async () => {
  const f = transport()
  f.connection.send({ id: 1, method: 'Target.setAutoAttach', params: { autoAttach: true } })
  const readiness = f.connection.receive({ id: 1, result: {} })
  f.connection.close()
  await readiness
  assert.deepEqual(f.delivered, [])
})

test('switching targets retains and reuses page connections until the browser changes', async () => {
  let current = 'first-browser', closed = 0
  const opened = []
  const session = new Session({
    discover: async () => ({ id: current, websocketUrl: 'ws://fixture/' + current }),
    connect: async (_url, targetId) => {
      opened.push(targetId)
      return { isConnected: () => true, close: async () => { closed++ } }
    },
  })
  try {
    const first = await session.browserFor('http://fixture', 'first-page')
    await session.browserFor('http://fixture', 'second-page')
    assert.equal(closed, 0)
    assert.equal(await session.browserFor('http://fixture', 'first-page'), first)
    assert.deepEqual(opened, ['first-page', 'second-page'])
    current = 'replacement-browser'
    assert.notEqual(await session.browserFor('http://fixture', 'first-page'), first)
    assert.equal(closed, 2)
  } finally { await session.close() }
})

test('background-only recycling preserves foreground pages and closes only its stable target', async () => {
  const closed = [], fronts = []
  let foreground = true
  const context = { pages: () => [page], newCDPSession: async () => ({
    send: async () => ({ targetInfo: { targetId: 'owned' } }), detach: async () => {},
  }) }
  const page = { context: () => context, url: () => 'https://owned.test',
    evaluate: async () => foreground, close: async () => closed.push('owned'),
    bringToFront: async () => fronts.push('owned'),
  }
  const browser = { contexts: () => [context], isConnected: () => true, close: async () => {} }
  const session = new Session({
    discover: async () => ({ id: 'browser', websocketUrl: 'ws://fixture' }),
    connect: async () => browser,
    control: async () => ({ close: () => {}, request: async () => ({ targetInfos: [
      { type: 'page', targetId: 'user', url: 'https://user.test' },
      { type: 'page', targetId: 'owned', url: 'https://owned.test' },
    ] }) }),
  })
  const flags = { target: 'owned', 'no-focus': true, 'only-if-background': true, 'expected-browser': 'browser' }
  try {
    await assert.rejects(session.run('close', flags, [], 1000, { log: () => {} }), /CHROME_TARGET_IN_USE/)
    assert.deepEqual(closed, [])
    foreground = false
    await session.run('close', flags, [], 1000, { log: () => {} })
    assert.deepEqual(closed, ['owned'])
    assert.deepEqual(fronts, [])
    await assert.rejects(session.run('close', { ...flags, 'no-focus': false }, [], 1000, { log: () => {} }), /CHROME_TARGET_SELECTION_CONFLICT/)
  } finally { await session.close() }
})
