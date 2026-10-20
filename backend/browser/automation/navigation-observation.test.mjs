import assert from 'node:assert/strict'
import test from 'node:test'
import { observePage } from './browser-observation.mjs'
import { Session } from './driver.mjs'

function fixture() {
  const state = { html: '<body>news</body>', values: [['draft', false]], focused: { html: '<body>news</body>', identity: ['BODY'], hasFocus: false }, url: 'https://example.com/news', loader: 'document' }
  const moves = [], clicks = []
  const context = { pages: () => [page], newCDPSession: async () => ({ send: async method => {
    if (method === 'Target.getTargetInfo') return { targetInfo: { targetId: 'owned' } }
    if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'frame', loaderId: state.loader } } }
    throw Error(method)
  }, detach: async () => {} }) }
  const page = { context: () => context, url: () => state.url, evaluate: async () => ({ html: state.html, values: state.values, focused: state.focused, url: state.url, controls: [], title: 'News', domText: state.html, viewportSize: { width: 800, height: 600 }, deviceScale: 1 }), goto: async url => { moves.push(url); state.url = url }, title: async () => 'News', click: async selector => clicks.push(selector) }
  const browser = { contexts: () => [context], isConnected: () => true, close: async () => {} }
  const session = new Session({ discover: async () => ({ id: 'browser', websocketUrl: 'ws://fixture' }), connect: async () => browser })
  const run = (verb, signature) => session.run(verb, { target: 'owned', 'expected-browser': 'browser', 'expected-scene': signature, 'no-focus': true }, [verb === 'goto' ? 'https://example.com/source' : '#button'], 0, { log: () => {} })
  return { state, page, moves, clicks, run }
}

test('dynamic news text does not prevent navigation or weaken click checks', async () => {
  const f = fixture(), before = await observePage(f.page)
  assert.match(before.navigationSignature, /^[a-f0-9]{64}$/)
  f.state.html = '<body>ad updated</body>'; f.state.focused.html = f.state.html
  const after = await observePage(f.page)
  assert.notEqual(before.signature, after.signature)
  assert.equal(before.navigationSignature, after.navigationSignature)
  await assert.rejects(f.run('click', before.navigationSignature), /CHROME_SCENE_CHANGED/)
  assert.deepEqual(f.clicks, [])
  await f.run('goto', before.navigationSignature)
  assert.deepEqual(f.moves, ['https://example.com/source'])
})

for (const change of [s => { s.values = [['changed input', false]] }, s => { s.focused.hasFocus = true }, s => { s.focused.identity = ['INPUT', 'name'] }, s => { s.loader = 'reloaded-document' }, s => { s.url = 'https://example.com/other' }, s => { s.focused.selection = 'selected text' }]) {
  test('navigation rejects changed document or user interaction state', async () => {
    const f = fixture(), before = await observePage(f.page)
    change(f.state)
    await assert.rejects(f.run('goto', before.navigationSignature), /CHROME_SCENE_CHANGED/)
    assert.deepEqual(f.moves, [])
  })
}

test('legacy exact scene navigation remains supported', async () => {
  const f = fixture(), before = await observePage(f.page)
  await f.run('goto', before.signature)
  assert.equal(f.moves.length, 1)
})
