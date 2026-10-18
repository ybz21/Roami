import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { browserIdentity, observePage, pngDimensions } from './browser-observation.mjs'

function image(width = 1600, height = 1200) {
  const body = Buffer.alloc(24)
  Buffer.from('89504e470d0a1a0a', 'hex').copy(body)
  body.writeUInt32BE(width, 16); body.writeUInt32BE(height, 20)
  return body
}
function fixture(changed = false) {
  let captures = 0, detached = 0
  const session = { send: async method => {
    if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'frame', loaderId: 'document' } } }
    if (method === 'Page.captureScreenshot') return { data: image().toString('base64') }
    throw new Error('Unexpected method')
  }, detach: async () => { detached++ } }
  return {
    page: { context: () => ({ newCDPSession: async () => session }), evaluate: async () => ({
      html: changed && captures++ ? '<body>changed</body>' : '<body>fixture</body>',
      values: ['private'], focused: { html: 'private' }, controls: [],
      url: 'about:blank', domText: 'Fixture', viewportSize: { width: 800, height: 600 }, deviceScale: 2,
    }) }, detached: () => detached,
  }
}

test('observation fingerprints private scene data without returning it', async () => {
  const { page, detached } = fixture()
  const first = await observePage(page), second = await observePage(page)
  assert.equal(first.signature, second.signature)
  assert(!JSON.stringify(first).includes('private'))
  assert.equal(first.domText, 'Fixture')
  assert.equal(detached(), 2)
})

test('screenshots retain exact viewport-to-pixel scale and use exclusive private files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-observe-'))
  try {
    const { page } = fixture(), path = join(root, 'capture.png')
    const observed = await observePage(page, path)
    assert.equal(observed.screenshot.scaleX, 2)
    assert.equal(observed.screenshot.scaleY, 2)
    assert.deepEqual(await readFile(path), image())
    assert.equal((await stat(path)).mode & 0o077, 0)
    await assert.rejects(observePage(page, path), error => error.code === 'EEXIST')
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('scene changes during screenshot capture discard the mixed observation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-observe-'))
  try {
    const { page, detached } = fixture(true), path = join(root, 'capture.png')
    await assert.rejects(observePage(page, path), /CHROME_SCENE_CHANGED/)
    await assert.rejects(stat(path), error => error.code === 'ENOENT')
    assert.equal(detached(), 1)
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('browser identity uses the discovery browser endpoint across CDP connections', async () => {
  const endpoint = 'http://127.0.0.1:9222'
  const discovery = async (url, options) => {
    assert.equal(url, endpoint + '/json/version')
    assert.equal(options.redirect, 'error')
    return new Response(JSON.stringify({ webSocketDebuggerUrl: 'ws://127.0.0.1:9222/devtools/browser/browser-instance' }))
  }
  assert.equal(await browserIdentity(endpoint, discovery), 'browser-instance')
  assert.equal(await browserIdentity('ws://127.0.0.1:9222/devtools/browser/browser-instance'), 'browser-instance')
  await assert.rejects(browserIdentity(endpoint, async () => new Response(JSON.stringify({ webSocketDebuggerUrl: 'ws://127.0.0.1:9222/devtools/page/wrong' }))), /CHROME_BROWSER_IDENTITY_UNAVAILABLE/)
})

test('invalid and zero-sized screenshot headers cannot provide coordinate transforms', () => {
  assert.throws(() => pngDimensions(Buffer.from('not an image')), /CHROME_SCREENSHOT_INVALID/)
  assert.throws(() => pngDimensions(image(0, 100)), /CHROME_SCREENSHOT_INVALID/)
})

test('a stalled screenshot releases the observation queue without writing late evidence', async () => {
  let detached = false, release
  const screenshot = new Promise(resolve => { release = resolve })
  const original = fixture().page
  const page = { ...original, context: () => ({ newCDPSession: async () => ({
    send: method => method === 'Page.captureScreenshot' ? screenshot : Promise.resolve({ frameTree: { frame: { id: 'f', loaderId: 'l' } } }),
    detach: async () => { detached = true },
  }) }) }
  const root = await mkdtemp(join(tmpdir(), 'roami-observe-'))
  try {
    const path = join(root, 'late.png')
    await assert.rejects(observePage(page, path, { timeoutMs: 20 }), /CHROME_OBSERVATION_TIMEOUT/)
    assert(detached)
    release({ data: image().toString('base64') })
    await new Promise(resolve => setImmediate(resolve))
    await assert.rejects(stat(path), error => error.code === 'ENOENT')
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('read-only observations expose resolved navigation links without executable or credential URLs', async () => {
  const { runInNewContext } = await import('node:vm')
  const anchor = href => ({
    id: 'link', tagName: 'A', innerText: 'Source', type: '',
    getAttribute: name => name === 'href' ? href : null,
    getBoundingClientRect: () => ({ width: 20, height: 20, top: 0, left: 0, bottom: 20, right: 20 }),
  })
  const anchors = ['../correction.html#final', 'https://docs.example/source', 'javascript:alert(1)', 'data:text/html,secret', 'https://user:password@example.com/private'].map(anchor)
  const original = fixture().page
  const page = { ...original, evaluate: async fn => runInNewContext('(' + fn.toString() + ')()', {
    URL, CSS: { escape: value => value }, innerWidth: 800, innerHeight: 600,
    devicePixelRatio: 1, scrollX: 0, scrollY: 0,
    location: { href: 'https://example.com/reports/index.html' },
    window: { getSelection: () => '' },
    getComputedStyle: () => ({ visibility: 'visible', display: 'inline' }),
    document: {
      baseURI: 'https://example.com/reports/index.html', title: 'Sources',
      documentElement: { outerHTML: '<body>Sources</body>' }, body: { innerText: 'Sources' },
      querySelectorAll: selector => selector.startsWith('a,') ? anchors : [],
      hasFocus: () => false,
    },
  }) }
  const observed = await observePage(page)
  assert.deepEqual(Array.from(observed.controls.slice(0, 2), item => item.href), ['https://example.com/correction.html#final', 'https://docs.example/source'])
  assert(observed.controls.slice(2).every(item => !('href' in item)))
  assert(!JSON.stringify(observed).includes('password'))
})
