import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import { cdpScreenshot, withInsecureTLS, Session } from './driver.mjs'

const desktop = {
  width: 1440, height: 900, deviceScaleFactor: 2,
  screenWidth: 1920, screenHeight: 1080, mobile: false,
  userAgent: 'desktop', touchPoints: 0,
}

function fixture(original = desktop, failure = '') {
  const calls = []
  let detached = 0
  let created = 0
  const page = Object.assign(new EventEmitter(), {
    context: () => ({ newCDPSession: async () => ({
      send: async (method, params) => {
        calls.push({ method, params })
        if (method === failure) throw new Error('CDP failure')
        if (method === 'Target.getTargetInfo') return { targetInfo: { targetId: 'owned' } }
        if (method === 'Runtime.evaluate') return { result: { value: original } }
        if (method === 'Page.captureScreenshot') return { data: Buffer.from('image').toString('base64') }
        return {}
      },
      detach: async () => { detached++ },
    }) }),
  })
  const context = page.context()
  page.context = () => context
  const open = context.newCDPSession
  context.newCDPSession = async () => { created++; return open() }
  return { page, calls, detached: () => detached, created: () => created }
}

test('temporary screenshot restores the mirror viewport and DPR after success or failure', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'roami-screenshot-test-'))
  try {
    for (const failure of ['', 'Page.captureScreenshot', 'Emulation.setDeviceMetricsOverride']) {
      const state = fixture(desktop, failure)
      const capture = cdpScreenshot(state.page, { viewport: '800x600' }, join(dir, 'shot.png'), 500)
      if (failure) await assert.rejects(capture, /CDP failure/)
      else await capture
      const metrics = state.calls.filter(call => call.method === 'Emulation.setDeviceMetricsOverride')
      assert.deepEqual(metrics.at(-1).params, {
        width: 1440, height: 900, deviceScaleFactor: 2,
        screenWidth: 1920, screenHeight: 1080, mobile: false,
      })
      assert.equal(state.detached(), 0)
      state.page.emit('close')
      assert.equal(state.detached(), 1)
    }
  } finally { await rm(dir, { recursive: true, force: true }) }
})

test('device screenshot restores mobile emulation, user agent and touch after a capture error', async () => {
  const original = { ...desktop, width: 980, height: 2121, screenWidth: 390, screenHeight: 844,
    deviceScaleFactor: 3, mobile: true, userAgent: 'iPhone', touchPoints: 5 }
  const state = fixture(original, 'Page.captureScreenshot')
  await assert.rejects(cdpScreenshot(state.page, { device: 'pixel' }, '/unused.png', 500), /CDP failure/)
  const params = method => state.calls.filter(call => call.method === method).at(-1).params
  assert.deepEqual(params('Emulation.setDeviceMetricsOverride'), {
    width: 390, height: 844, deviceScaleFactor: 3,
    screenWidth: 390, screenHeight: 844, mobile: true,
  })
  assert.deepEqual(params('Emulation.setUserAgentOverride'), { userAgent: 'iPhone' })
  assert.deepEqual(params('Emulation.setTouchEmulationEnabled'), { enabled: true, maxTouchPoints: 5 })
  assert.equal(state.detached(), 0)
  state.page.emit('close')
  assert.equal(state.detached(), 1)
})

test('repeated sized screenshots reuse one viewport owner until the tab closes', async () => {
  const state = fixture(desktop, 'Page.captureScreenshot')
  for (let i = 0; i < 20; i++) {
    await assert.rejects(cdpScreenshot(state.page, { viewport: '800x600' }, '/unused.png', 500), /CDP failure/)
  }
  assert.equal(state.created(), 1)
  assert.equal(state.detached(), 0)
  state.page.emit('close')
  assert.equal(state.detached(), 1)
})

test('plain fast screenshots reuse their session without changing the viewport', async () => {
  const state = fixture(desktop, 'Page.captureScreenshot')
  await assert.rejects(cdpScreenshot(state.page, {}, '/unused.png', 500), /CDP failure/)
  assert.equal(state.detached(), 0)
  assert.deepEqual(state.calls.map(call => call.method), ['Page.captureScreenshot'])
  state.page.emit('close')
  assert.equal(state.detached(), 1)
})

test('navigation releases the TLS session on success, navigation failure and security failure', async () => {
  for (const failure of ['', 'navigation', 'Security.enable']) {
    const state = fixture(desktop, failure)
    const navigation = withInsecureTLS(state.page.context(), state.page, async () => {
      if (failure === 'navigation') throw new Error('navigation failed')
      return 'loaded'
    })
    if (failure === 'navigation') await assert.rejects(navigation, /navigation failed/)
    else assert.equal(await navigation, 'loaded')
    assert.equal(state.detached(), 1)
  }
})

test('failed new-tab navigation closes only the newly created page', async () => {
  const state = fixture()
  let closed = 0
  state.page.url = () => 'about:blank'
  state.page.bringToFront = async () => {}
  state.page.goto = async () => { throw new Error('navigation failed') }
  state.page.close = async () => { closed++ }
  const ctx = { pages: () => [state.page], newPage: async () => state.page }
  const browser = { contexts: () => [ctx], isConnected: () => true }
  const session = new Session({
    discover: async () => ({ id: 'browser', websocketUrl: 'ws://fixture/devtools/browser/browser' }),
    control: async () => ({ request: async method => {
      if (method === 'Target.getTargets') return { targetInfos: [{ type: 'page', targetId: 'owned', url: 'https://example.com/news' }] }
      if (method === 'Target.createTarget') return { targetId: 'owned' }
      if (method === 'Target.closeTarget') { closed++; return {} }
      return {}
    }, close: () => {} }), connect: async () => browser,
  })
  ctx.newCDPSession = state.page.context().newCDPSession
  await assert.rejects(session.run('new', {}, ['http://fixture'], 500, {}), /navigation failed/)
  assert.equal(closed, 1)
  assert.equal(state.detached(), 2)
})
