import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { spawn, execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, mkdir, symlink, writeFile, readFile, rm, stat } from 'node:fs/promises'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { once } from 'node:events'
import { executeVerb, targetIdentity } from './driver.mjs'
import { observePage } from './browser-observation.mjs'
import { OperationReceipts } from './operation-receipts.mjs'

const enabled = process.env.ROAMI_BROWSER_UPLOAD_ACCEPTANCE === '1'
const hash = body => createHash('sha256').update(body).digest('hex')
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
const form = `<!doctype html><meta charset="utf-8"><title>Private upload fixture</title>
<form id="form"><label>Video<input id="video" name="video" type="file"></label><input id="text" type="text"></form><pre id="result">Waiting for file</pre>
<script>document.querySelector('#video').addEventListener('change',async()=>{try{const r=await fetch('/upload',{method:'POST',body:new FormData(document.querySelector('#form'))});document.querySelector('#result').textContent=await r.text()}catch(e){document.querySelector('#result').textContent='FAILED:'+e.message}})</script>`
const deferredForm = `<!doctype html><meta charset="utf-8"><title>Deferred file reader</title>
<form id="form"><input id="video" name="video" type="file"><button id="send" type="button">Read selected file</button></form><pre id="result">Waiting</pre>
<script>document.querySelector('#send').onclick=async()=>{try{await document.querySelector('#video').files[0].arrayBuffer();const r=await fetch('/upload',{method:'POST',body:new FormData(document.querySelector('#form'))});document.querySelector('#result').textContent=await r.text()}catch(e){document.querySelector('#result').textContent='FAILED:'+e.name}}</script>`

async function waitFor(read, description) {
  const until = Date.now() + 15000
  while (Date.now() < until) {
    try { const result = await read(); if (result) return result } catch { /* Wait for the owned fixture. */ }
    await delay(50)
  }
  throw new Error('Timed out: ' + description)
}

function uploadedFile(body, contentType) {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(contentType)
  assert(boundary, 'multipart boundary missing')
  const start = body.indexOf(Buffer.from('\r\n\r\n')) + 4
  const end = body.indexOf(Buffer.from('\r\n--' + (boundary[1] || boundary[2])), start)
  assert(start > 3 && end > start, 'multipart file missing')
  const header = body.subarray(0, start).toString('utf8')
  return { body: body.subarray(start, end), name: /filename="([^"]+)"/.exec(header)?.[1], mimeType: /Content-Type: ([^\r\n]+)/i.exec(header)?.[1] }
}

test('private CDP Chrome selects and uploads exact bytes to a local form; repeated/unknown actions never replay', { skip: !enabled, timeout: 90000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-upload-browser-'))
  const uploads = [], requests = [], chromeErrors = []
  const server = createServer(async (request, response) => {
    requests.push(request.method + ' ' + request.url)
    if (request.url === '/upload' && request.method === 'POST') {
      const chunks = []
      for await (const chunk of request) chunks.push(chunk)
      const file = uploadedFile(Buffer.concat(chunks), request.headers['content-type'] || '')
      const receipt = { name: file.name, sizeBytes: file.body.length, sha256: hash(file.body), mimeType: file.mimeType }
      uploads.push(receipt); response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(receipt)); return
    }
    response.writeHead(200, { 'Content-Type': 'text/html' }); response.end(request.url === '/deferred' ? deferredForm : form)
  })
  let chrome, browser
  try {
    server.listen(0, '127.0.0.1'); await once(server, 'listening')
    const address = `http://127.0.0.1:${server.address().port}`
    const profile = join(root, 'private-profile')
    const chromeEnv = { ...process.env }; for (const key of Object.keys(chromeEnv)) if (/proxy/i.test(key)) delete chromeEnv[key]
    chrome = spawn(process.env.ROAMI_TEST_CHROME_BIN || '/usr/bin/google-chrome', ['--headless=new', '--disable-gpu', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-features=HttpsUpgrades,MediaRouter,OptimizationHints,NetworkTimeServiceQuerying,PaintHolding,AvoidCorsURLLoaderRestartOnRedirect', '--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server', '--disable-component-extensions-with-background-pages', '--disable-component-update', '--no-default-browser-check', '--disable-default-apps', '--disable-sync', '--metrics-recording-only', '--disable-search-engine-choice-screen', '--password-store=basic', '--use-mock-keychain', '--disable-field-trial-config', '--disable-background-networking', '--disable-extensions', '--no-first-run', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { env: chromeEnv, stdio: ['ignore', 'ignore', 'pipe'] })
    chrome.stderr.on('data', data => { if (chromeErrors.join('').length < 4000) chromeErrors.push(data.toString()) })
    const port = await waitFor(async () => (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0], 'private Chrome CDP port')
    assert((await (await fetch(address)).text()).includes('Private upload fixture'))
    const { chromium } = await import(process.env.ROAMI_PLAYWRIGHT_MODULE || 'playwright-core')
    browser = await chromium.connectOverCDP('http://127.0.0.1:' + port)
    const context = browser.contexts()[0], page = await context.newPage()
    await page.bringToFront()
    await page.goto(address, { waitUntil: 'domcontentloaded', timeout: 10000 })
    const other = await context.newPage()
    await other.goto(address + '/untouched', { waitUntil: 'domcontentloaded', timeout: 10000 })
    const otherTarget = await targetIdentity(other), target = await targetIdentity(page)
    assert.notEqual(target, otherTarget)
    const source = join(root, 'demo clip.mp4'), body = process.env.ROAMI_UPLOAD_ACCEPTANCE_FILE ? await readFile(process.env.ROAMI_UPLOAD_ACCEPTANCE_FILE) : Buffer.concat([Buffer.from('000000186674797069736f6d0000020069736f6d69736f32', 'hex'), Buffer.alloc(128 * 1024, 37)])
    await writeFile(source, body)
    const observed = await observePage(page), flags = { target, 'no-focus': true, 'expected-browser': 'private-fixture', 'expected-scene': observed.signature, 'file-root': root, 'expected-file-sha256': hash(body) }
    const receipts = new OperationReceipts(join(root, 'receipts')), id = '1'.repeat(32), payload = ['upload', '#video', source, flags]
    const first = await receipts.begin(id, payload), output = []
    const select = () => executeVerb(browser, 'upload', flags, ['#video', source], 10000, { log: value => output.push(value) }, 'private-fixture')
    const selected = await receipts.execute(id, first.record.payloadHash, async () => { await select(); return output[0] })
    assert.equal(selected.state, 'succeeded'); assert.equal(selected.result.selected, true); assert.equal(selected.result.needsVerification, true)
    assert.equal('uploaded' in selected.result, false)
    await waitFor(() => uploads.length === 1, 'server received original file after snapshot cleanup')
    assert.deepEqual(uploads[0], { name: 'demo clip.mp4', sizeBytes: body.length, sha256: hash(body), mimeType: 'video/mp4' })
    assert.equal(await other.locator('#video').evaluate(input => input.files.length), 0)
    assert.equal((await receipts.begin(id, payload)).dispatch, false)
    await receipts.execute(id, first.record.payloadHash, select)
    assert.equal(uploads.length, 1)

    const delayed = await context.newPage(); await delayed.goto(address + '/delayed', { waitUntil: 'domcontentloaded', timeout: 10000 })
    const delayedFlags = { ...flags, target: await targetIdentity(delayed), 'expected-scene': (await observePage(delayed)).signature }
    const unknownId = '2'.repeat(32), unknownPayload = ['upload', delayedFlags.target], unknown = await receipts.begin(unknownId, unknownPayload)
    const result = await receipts.execute(unknownId, unknown.record.payloadHash, async () => {
      await executeVerb(browser, 'upload', delayedFlags, ['#video', source], 10000, { log: () => {} }, 'private-fixture')
      throw new Error('lost acknowledgement after file selection')
    })
    assert.equal(result.state, 'unknown'); assert.equal(result.outcomeKnown, false)
    await waitFor(() => uploads.length === 2, 'server received unknown-outcome upload once')
    assert.equal((await receipts.begin(unknownId, unknownPayload)).dispatch, false)
    await receipts.execute(unknownId, unknown.record.payloadHash, () => { throw new Error('must not replay unknown') })
    assert.equal(uploads.length, 2)

    const changed = { ...flags, 'expected-scene': 'a'.repeat(64) }
    await assert.rejects(executeVerb(browser, 'upload', changed, ['#video', source], 10000, { log: () => {} }, 'private-fixture'), /CHROME_SCENE_CHANGED/)
    const fresh = { ...flags, 'expected-scene': (await observePage(page)).signature }
    await assert.rejects(executeVerb(browser, 'upload', fresh, ['#text', source], 10000, { log: () => {} }, 'private-fixture'), /CHROME_UPLOAD_INPUT_INVALID/)
    assert.equal(uploads.length, 2)
    let cliReceipt, selectDeferred
    if (process.env.ROAMI_TEST_ROAMI_BIN) {
      const data = join(root, 'cli-data'), cache = join(data, 'cache/chrome-runtime')
      await mkdir(cache, { recursive: true })
      assert(process.env.ROAMI_PLAYWRIGHT_MODULE, 'CLI acceptance requires an explicit dependency module')
      await symlink(dirname(dirname(process.env.ROAMI_PLAYWRIGHT_MODULE)), join(cache, 'node_modules'))
      const env = { ...process.env, ROAMI_HOME: data, ROAMI_DATA: data, TTMUX_CHROME_SOCK: join(root, 'cli.sock'), TTMUX_CHROME_DAEMON_LOG: join(root, 'cli.log'), TTMUX_CHROME_DAEMON_IDLE: '0.2' }
      delete env.ROAMI_AGENT_TURN_ID
      const cli = async (...args) => JSON.parse((await promisify(execFile)(process.env.ROAMI_TEST_ROAMI_BIN, ['chrome', ...args, '--cdp', 'http://127.0.0.1:' + port, '--no-start'], { env, timeout: 20000, maxBuffer: 1024 * 1024 })).stdout)
      const capabilities = await cli('capabilities')
      assert(capabilities.features.includes('file_upload'))
      assert.deepEqual(capabilities.fileUpload, { maxBytes: 52428799, limitSource: 'playwright-cdp', confirmation: 'selected' })
      const cliFlags = ['--target', target, '--expected-browser', capabilities.browserId, '--expected-scene', (await observePage(page)).signature, '--file-root', root, '--expected-file-sha256', hash(body), '--operation-id', '3'.repeat(32), '--receipt-root', join(root, 'cli-receipts'), '--no-focus', '--no-retry']
      cliReceipt = await cli('upload', '#video', source, ...cliFlags)
      assert.equal(cliReceipt.state, 'succeeded')
      assert.deepEqual(JSON.parse(cliReceipt.result.stdout), { selected: true, needsVerification: true, file: { name: 'demo clip.mp4', sizeBytes: body.length, sha256: hash(body) } })
      await waitFor(() => uploads.length === 3, 'embedded CLI uploaded original bytes')
      assert.deepEqual(await cli('upload', '#video', source, ...cliFlags), cliReceipt)
      assert.deepEqual(await cli('operation-status', '--operation-id', cliReceipt.id, '--receipt-root', join(root, 'cli-receipts')), cliReceipt)
      assert.equal(uploads.length, 3)
      selectDeferred = (target, scene) => cli('upload', '#video', source, '--target', target, '--expected-browser', capabilities.browserId, '--expected-scene', scene, '--file-root', root, '--expected-file-sha256', hash(body), '--operation-id', '4'.repeat(32), '--receipt-root', join(root, 'cli-receipts'), '--no-focus', '--no-retry')
      await delay(500)
    }
    const deferred = await context.newPage(); await deferred.goto(address + '/deferred')
    const deferredTarget = await targetIdentity(deferred), previousUploads = uploads.length
    const deferredScene = (await observePage(deferred)).signature
    if (selectDeferred) await selectDeferred(deferredTarget, deferredScene)
    else await executeVerb(browser, 'upload', { ...flags, target: deferredTarget, 'expected-scene': deferredScene }, ['#video', source], 10000, { log: () => {} }, 'private-fixture')
    assert.equal(uploads.length, previousUploads, 'selection must not submit the form')
    // Read only after upload returned and its private temporary snapshot was removed.
    await executeVerb(browser, 'click', { target: deferredTarget, 'no-focus': true }, ['#send'], 10000, { log: () => {} }, 'private-fixture')
    await waitFor(async () => !(await deferred.locator('#result').innerText()).startsWith('Waiting'), 'deferred file read')
    const screenshot = process.env.ROAMI_UPLOAD_ACCEPTANCE_SCREENSHOT
    if (screenshot) { await deferred.bringToFront(); await deferred.screenshot({ path: screenshot, fullPage: true, timeout: 10000 }) }
    assert.equal((await deferred.locator('#result').innerText()).startsWith('FAILED:'), false, await deferred.locator('#result').innerText())
    await waitFor(() => uploads.length === previousUploads + 1, 'deferred form received stable file bytes')
    assert.deepEqual(uploads.at(-1), { name: 'demo clip.mp4', sizeBytes: body.length, sha256: hash(body), mimeType: 'video/mp4' })
    console.log(JSON.stringify({ browser: 'dedicated headless CDP', source: 'local HTTP fixture', upload: uploads[0], untouchedTarget: otherTarget, selectedTarget: target, duplicateUploadCount: uploads.length, knownReceipt: selected.state, lostAcknowledgement: result.state, cliReceipt }))
    assert.equal((await stat(source)).size, body.length)
  } catch (error) {
    console.error(JSON.stringify({ requests, chromeErrors }))
    throw error
  } finally {
    await browser?.close().catch(() => {})
    if (chrome && chrome.exitCode === null) { chrome.kill('SIGTERM'); await Promise.race([once(chrome, 'exit'), delay(3000)]) }
    await new Promise(resolve => server.close(resolve))
    server.closeAllConnections()
    await rm(root, { recursive: true, force: true })
  }
})
