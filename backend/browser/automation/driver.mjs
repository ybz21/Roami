// chrome driver — Playwright over CDP。
// 与 launcher.sh 一起内嵌到 roami；本文件是真源。
// 用法: node driver.mjs <verb> [args] [--tab N|--url 子串] [--timeout ms] [--cdp 地址]
//
// 常驻 daemon：每条命令原本要付一次 ~0.5s 的 playwright 连接冷启动，agent 高频调用（测试
// 循环里几十条命令很常见）时这笔开销累加起来很扎眼。改成 unix socket 常驻daemon 复用同一条
// CDP 连接，热路径缩到几十毫秒；daemon 空闲一段时间自杀（见 DAEMON_IDLE_MS），不会常驻占用。
// 单条命令本身仍是一次性冷启动 `node driver.mjs <verb>` 进程（无状态，好调试）；这层进程
// 内部把请求转发给 daemon（连不上就现拉起一个），daemon 才是真正持有 CDP 连接、执行动作的
// 地方。daemon 侧还挂了看门狗（单条命令处理超时就把整个 daemon 进程杀掉重来，见
// handleConnection）——防的是 CDP 连接在 Chrome 被内存压力杀掉/重启期间可能陷入不带退避的
// 忙等死循环（不依赖出问题的那段代码自己配合退出，直接从外面强杀更可靠）。
import { writeFile, mkdir, mkdtemp, rm, copyFile, rename } from 'node:fs/promises'
import { existsSync, unlinkSync, writeFileSync, openSync, realpathSync } from 'node:fs'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve, extname, join } from 'node:path'
import { tmpdir } from 'node:os'
import net from 'node:net'
import { OperationReceipts } from './operation-receipts.mjs'
import { discoverBrowser, observePage } from './browser-observation.mjs'
import { ScopedCDP, connectTarget, selectTarget } from './scoped-cdp.mjs'

const SELF_PATH = fileURLToPath(import.meta.url)
const SOCK_PATH = (process.env.TTMUX_CHROME_SOCK || '/tmp/ttmux-chrome-cli.sock') + '.scoped-v2'
const DAEMON_LOG = process.env.TTMUX_CHROME_DAEMON_LOG || '/tmp/ttmux-chrome-cli.log'
const DAEMON_IDLE_MS = Number(process.env.TTMUX_CHROME_DAEMON_IDLE || 300) * 1000

class ChromeError extends Error {}
const OPERATION_VERBS = new Set(['new', 'goto', 'url', 'title', 'click', 'fill', 'type', 'press', 'close', 'screenshot', 'shot', 'text', 'html', 'attr', 'wait', 'pdf', 'observe'])

// ── 纯工具函数：不依赖某一次调用的 flags/pos，daemon 内多条请求共用也安全 ──────────────

function parseArgs(argv) {
  const verb = argv[0] || 'help'
  const rest = argv.slice(1)
  const flags = {}
  const pos = []
  const booleanFlags = new Set(['full', 'fast', 'fresh', 'mobile', 'no-retry', 'no-focus'])
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i]
    if (a.startsWith('--')) {
      const name = a.slice(2)
      if (booleanFlags.has(name)) flags[name] = true
      else flags[name] = rest[++i]
    }
    else pos.push(a)
  }
  return { verb, flags, pos }
}
const num = (x, d) => {
  const n = Number(x)
  return Number.isFinite(n) ? n : d
}
const parseViewport = (value) => {
  const m = String(value || '').match(/^(\d+)x(\d+)$/)
  return m ? { width: Number(m[1]), height: Number(m[2]) } : null
}
const parseClip = (value) => {
  const m = String(value || '').match(/^(\d+),(\d+),(\d+),(\d+)$/)
  return m ? { x: Number(m[1]), y: Number(m[2]), width: Number(m[3]), height: Number(m[4]) } : null
}
const imageType = (file) => /\.(jpe?g)$/i.test(file) ? 'jpeg' : 'png'
// 手机模式设备档（与 Web 镜像 BrowserView.tsx 保持一致）。--device <名> 选机型，
// --mobile 等价于 --device iphone。维度为 CSS 像素视口，scale=dpr，ua 触发移动版站点。
const DEVICES = {
  iphone: { width: 390, height: 844, scale: 3, ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' },
  'iphone-se': { width: 375, height: 667, scale: 2, ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' },
  pixel: { width: 412, height: 915, scale: 2.625, ua: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36' },
  ipad: { width: 820, height: 1180, scale: 2, ua: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' },
}
const resolveDevice = (flags, fail) => {
  if (flags.device) return DEVICES[flags.device] || fail('未知设备: ' + flags.device + '（可选: ' + Object.keys(DEVICES).join(', ') + '）')
  if (flags.mobile) return DEVICES.iphone
  return null
}
const withTimeout = async (promise, ms, label) => {
  if (!ms) return promise
  let timer
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timeout after ${ms}ms`)), ms)
    })])
  } finally { clearTimeout(timer) }
}
const settleMs = (flags) => num(flags.wait || flags.settle, 0)
const chromeExecutable = () => {
  const candidates = [
    process.env.CHROME_BIN,
    '/opt/google/chrome/chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ].filter(Boolean)
  return candidates.find((p) => existsSync(p))
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// Explicit zero disables operation and encoding deadlines; transport connection probes stay bounded.
const effectiveTimeoutMs = (verb, timeoutMs) => timeoutMs === 0 ? 0 : verb === 'record' ? Math.max(timeoutMs, 60000) : timeoutMs

// 选中目标标签后把它前置（真实 CDP Target.activateTarget，不只是选中）——Web 镜像面板的
// 「前台标签跟随」（见 backend/browser/screencast.go 的 /json 顺序兜底）靠的正是标签被前置
// 这件事本身，agent 操作到哪，面板就跟到哪。前置失败（标签刚好被关掉等）不影响后续真正的
// 操作，吞掉即可。
// Chrome 自己的界面也是一个 page：地址栏下拉 chrome://omnibox-popup.top-chrome/、
// 标签搜索、侧边栏。它们混在 ctx.pages() 里，chrome tabs 会多列几行，更要命的是
// pages[0] 可能就是其中一个——那 chrome goto/text 就操作到浏览器界面上去了。
// 与后端 isUserTab（backend/browser/browser.go）同一条规矩。
function userPages(pages) {
  return pages.filter((p) => {
    const u = (p.url() || '').toLowerCase()
    if (u.startsWith('devtools://') || u.startsWith('chrome-untrusted://')) return false
    return !(u.startsWith('chrome://') && u.slice('chrome://'.length).split('/')[0].includes('top-chrome'))
  })
}

async function pick(pages, flags, fail) {
  const p = await pickPage(pages, flags, fail)
  await p.bringToFront().catch(() => {})
  return p
}
async function targetIdentity(page) {
  const session = await page.context().newCDPSession(page)
  try {
    const { targetInfo } = await session.send('Target.getTargetInfo')
    return targetInfo.targetId
  } finally {
    await session.detach().catch(() => {})
  }
}
async function pickPage(pages, flags, fail) {
  if (flags.target != null) {
    if (flags.tab != null || flags.url) return fail('CHROME_TARGET_SELECTION_CONFLICT')
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(flags.target)) return fail('CHROME_TARGET_INVALID')
    for (const page of pages) {
      if (await targetIdentity(page).catch(() => null) === flags.target) return page
    }
    return fail('CHROME_TARGET_NOT_FOUND')
  }
  if (flags.tab != null) return pages[Number(flags.tab)] || fail('无此 tab #' + flags.tab)
  if (flags.url) return pages.find((x) => x.url().includes(flags.url)) || fail('无匹配 url 的 tab: ' + flags.url)
  return pages[0] || fail('当前没有打开的 tab（先 chrome new <url>）')
}

// ── --fresh 截图：临时干净 Chrome，与共享 daemon/CDP 连接无关，不占 daemon ──────────────

async function freshScreenshot(flags, pos, timeoutMs, io) {
  const fail = (m) => { throw new ChromeError(m) }
  const to = timeoutMs
  const f = pos[0] || 'screenshot.png'
  const target = flags.goto || flags.open || flags.url || pos[1] || 'about:blank'
  const device = resolveDevice(flags, fail)
  const vp = parseViewport(flags.viewport) || (device ? { width: device.width, height: device.height } : { width: 1280, height: 800 })
  const type = imageType(f)
  const quality = type === 'jpeg' ? num(flags.quality, 85) : undefined
  let fresh
  try {
    const { chromium } = await import('playwright-core')
    const chromeBin = chromeExecutable()
    const launch = chromeBin ? { executablePath: chromeBin } : { channel: 'chrome' }
    fresh = await chromium.launch({ ...launch, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'], timeout: to })
    const context = await fresh.newContext({
      viewport: vp,
      ignoreHTTPSErrors: true, // 同 withInsecureTLS：自签 HTTPS（含 ttmux 自己）不该停在拦截页
      deviceScaleFactor: num(flags.scale, device ? device.scale : 1),
      ...(device ? { userAgent: device.ua, isMobile: true, hasTouch: true } : {}),
    })
    const p = await context.newPage()
    await p.goto(target, { waitUntil: flags.waitUntil || 'domcontentloaded', timeout: to })
    if (settleMs(flags) > 0) await p.waitForTimeout(settleMs(flags))
    await withTimeout(p.screenshot({ path: f, fullPage: !!flags.full, type, quality, timeout: to }), to ? to + 1000 : 0, 'fresh screenshot')
    io.log(f)
    await fresh.close()
  } catch (e) {
    await fresh?.close().catch(() => {})
    throw new ChromeError(e.message)
  }
}

// 自签证书：ttmux 自己就跑在自签 HTTPS 上，不放过证书错误就会停在「您的连接不是私密连接」
// 拦截页上，连自己的 Web UI 都驱动不了。按 CDP 逐标签放行（Security 域是会话级的），而不是给
// Chrome 加启动开关——那台 Chrome 可能是后端起的，启动开关这时根本轮不到我们加，
// 而且它一加就是整个浏览器全站放行，把镜像里的正常上网也一起松掉了。
async function withInsecureTLS(ctx, page, action) {
  let session
  try {
    session = await ctx.newCDPSession(page)
    await session.send('Security.enable') // 少这一句 setIgnoreCertificateErrors 会静默无效（返回 {} 但照拦）
    await session.send('Security.setIgnoreCertificateErrors', { ignore: true })
  } catch {} // 老版本 Chrome 不支持就算了，导航照走（顶多停在拦截页）
  try { return await action() } finally { if (session) await Promise.race([session.detach().catch(() => {}), sleep(250)]) }
}

const screenshotSessions = new WeakMap()

async function cdpScreenshot(page, flags, file, timeoutMs) {
  const device = resolveDevice(flags, message => { throw new ChromeError(message) })
  const viewport = device || parseViewport(flags.viewport)
  let session = screenshotSessions.get(page)
  if (!session) {
    session = await page.context().newCDPSession(page)
    // Full-page capture also overrides metrics; retain one owner per live page.
    screenshotSessions.set(page, session)
    page.once('close', () => {
      screenshotSessions.delete(page)
      session.detach().catch(() => {})
    })
  }
  let original
  try {
    if (viewport || flags.full) {
      const { result } = await session.send('Runtime.evaluate', {
        expression: `({width:innerWidth,height:innerHeight,deviceScaleFactor:devicePixelRatio,
          screenWidth:screen.width,screenHeight:screen.height,userAgent:navigator.userAgent,
          touchPoints:navigator.maxTouchPoints,mobile:/Android|iPhone|iPad|Mobile/i.test(navigator.userAgent)})`,
        returnByValue: true,
      })
      original = result.value
    }
    if (viewport) {
      await session.send('Emulation.setDeviceMetricsOverride', {
        width: viewport.width, height: viewport.height,
        deviceScaleFactor: device ? num(flags.scale, device.scale) : original.deviceScaleFactor,
        mobile: !!device, screenWidth: viewport.width, screenHeight: viewport.height,
      })
      if (device) {
        await session.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })
        await session.send('Emulation.setUserAgentOverride', { userAgent: device.ua })
      }
    }
    if (settleMs(flags) > 0) await page.waitForTimeout(settleMs(flags))
    const params = { format: imageType(file), fromSurface: true, captureBeyondViewport: !!flags.full }
    if (params.format === 'jpeg') params.quality = num(flags.quality, 85)
    const clip = parseClip(flags.clip)
    if (clip) params.clip = { ...clip, scale: 1 }
    else if (flags.full) {
      const metrics = await session.send('Page.getLayoutMetrics')
      const size = metrics.cssContentSize || metrics.contentSize
      params.clip = { x: 0, y: 0, width: Math.ceil(size.width), height: Math.ceil(size.height), scale: 1 }
    }
    const out = await withTimeout(session.send('Page.captureScreenshot', params), timeoutMs, 'CDP screenshot')
    await writeFile(file, Buffer.from(out.data, 'base64'))
  } finally {
    if (original) {
      // Restore the rendered viewport, including overrides owned by a live mirror connection.
      const { userAgent, touchPoints, ...metrics } = original
      if (metrics.mobile) { metrics.width = metrics.screenWidth; metrics.height = metrics.screenHeight }
      await session.send('Emulation.setDeviceMetricsOverride', metrics).catch(() => {})
      if (device) {
        await session.send('Emulation.setTouchEmulationEnabled', { enabled: touchPoints > 0, ...(touchPoints > 0 ? { maxTouchPoints: touchPoints } : {}) }).catch(() => {})
        await session.send('Emulation.setUserAgentOverride', { userAgent }).catch(() => {})
      }
    }
  }
}

// ── 主动词分发：操作一条已连好的 CDP browser。daemon 与一次性冷启动路径共用 ─────────────

function navigationWait(flags) {
  const value = flags['wait-until'] || 'load'
  if (!['load', 'domcontentloaded', 'commit'].includes(value)) throw new ChromeError('CHROME_NAVIGATION_WAIT_INVALID')
  return value
}

async function navigate(page, url, options) {
  try { return await page.goto(url, options) } catch (error) {
    // A rejected network request is known; cancellation or a lost CDP connection is not.
    const failure = /^page\.goto: net::ERR_(NAME_NOT_RESOLVED|CONNECTION_TIMED_OUT|CONNECTION_REFUSED|CONNECTION_RESET|CONNECTION_CLOSED|ADDRESS_UNREACHABLE|INTERNET_DISCONNECTED|NETWORK_CHANGED|PROXY_CONNECTION_FAILED|TUNNEL_CONNECTION_FAILED|EMPTY_RESPONSE|SSL_PROTOCOL_ERROR|CERT_AUTHORITY_INVALID|CERT_DATE_INVALID) at /.exec(error.message)
    if (failure) throw new ChromeError('CHROME_NAVIGATION_' + failure[1])
    throw error
  }
}

async function executeVerb(browser, verb, flags, pos, timeoutMs, io, browserId) {
  const fail = (m) => { throw new ChromeError(m) }
  const to = timeoutMs
  if (flags['expected-browser'] != null && browserId !== flags['expected-browser']) fail('CHROME_BROWSER_CHANGED')
  const settle = () => settleMs(flags)
  const ctx = browser.contexts()[0] || (await browser.newContext())
  const pages = userPages(ctx.pages())
  let selected
  const pickHere = async () => {
    if (selected) return selected
    if (flags['expected-scene'] != null) {
      if (!/^[a-f0-9]{64}$/.test(flags['expected-scene'])) fail('CHROME_SCENE_INVALID')
      selected = await pickPage(pages, flags, fail)
      const current = await observePage(selected, undefined, { timeoutMs: to })
      const expected = flags['expected-scene']
      if (current.signature !== expected && !(verb === 'goto' && current.navigationSignature === expected)) fail('CHROME_SCENE_CHANGED')
      if (!flags['no-focus']) await selected.bringToFront().catch(() => {})
    } else selected = flags['no-focus'] ? await pickPage(pages, flags, fail) : await pick(pages, flags, fail)
    return selected
  }

  switch (verb) {
    case 'goto': { const p = await pickHere(); await withInsecureTLS(ctx, p, () => navigate(p, pos[0], { waitUntil: navigationWait(flags), timeout: to })); io.log({ url: p.url(), title: await withTimeout(p.title(), 3000, 'navigation title').catch(() => '') }); break }
    case 'url': io.log((await pickHere()).url()); break
    case 'title': io.log(await (await pickHere()).title()); break
    case 'click': await (await pickHere()).click(pos[0], { timeout: to }); io.log('ok'); break
    case 'fill': await (await pickHere()).fill(pos[0], pos[1] ?? '', { timeout: to }); io.log('ok'); break
    case 'type': await (await pickHere()).type(pos[0], pos[1] ?? '', { timeout: to }); io.log('ok'); break
    case 'press': { const p = await pickHere(); if (pos.length > 1) await p.press(pos[0], pos[1], { timeout: to }); else await p.keyboard.press(pos[0]); io.log('ok'); break }
    case 'text': io.log(await (await pickHere()).innerText(pos[0] || 'body', { timeout: to })); break
    case 'attr': io.log(await (await pickHere()).getAttribute(pos[0], pos[1], { timeout: to })); break
    case 'html': { const p = await pickHere(); io.log(pos[0] ? await p.locator(pos[0]).first().evaluate((e) => e.outerHTML) : await p.content()); break }
    case 'eval': { const r = await (await pickHere()).evaluate(pos[0]); io.log(r === undefined ? 'undefined' : r); break }
    case 'wait': await (await pickHere()).waitForSelector(pos[0], { timeout: to }); io.log('ok'); break
    case 'screenshot': case 'shot': {
      const f = pos[0] || 'screenshot.png'
      const p = await pickHere()
      const sized = !!(flags.viewport || flags.device || flags.mobile)
      if (flags.fast || sized) {
        await cdpScreenshot(p, flags, f, to)
      } else {
        if (settle() > 0) await p.waitForTimeout(settle())
        const type = imageType(f)
        const quality = type === 'jpeg' ? num(flags.quality, 85) : undefined
        try {
          await withTimeout(p.screenshot({ path: f, fullPage: !!flags.full, clip: parseClip(flags.clip), type, quality, timeout: to }), to ? to + 1000 : 0, 'screenshot')
        } catch {
          await cdpScreenshot(p, flags, f, to)
        }
      }
      io.log(f)
      break
    }
    case 'pdf': { const f = pos[0] || 'page.pdf'; await (await pickHere()).pdf({ path: f }); io.log(f); break }
    case 'observe': io.log(await observePage(await pickHere(), flags.screenshot, { timeoutMs: to })); break
    case 'close': await (await pickHere()).close(); io.log('ok'); break
    default: fail('未知命令: ' + verb)
  }
}

// 虚拟光标：往被录制页注入轻量脚本，画一个跟随 mousemove 的光点 + mousedown 涟漪。与 Web
// 镜像面板注入的是同一份脚本（见 backend/browser/screencast.go 的 cursorScript），靠
// window.__bladeCur 幂等守卫——面板和录制同时挂在同一页面时不会重复注入。单独录制（没人开着
// 镜像面板围观）时，这份注入让产出的视频里依然能看清点在哪、有没有反应。
const cursorScript = `(() => {
  if (window.__bladeCur) return; window.__bladeCur = 1;
  const cur = document.createElement('div');
  cur.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;width:14px;height:14px;' +
    'margin:-7px 0 0 -7px;border-radius:50%;background:radial-gradient(circle,#4d9bff 0%,#1f6feb 60%,rgba(31,111,235,0) 100%);' +
    'box-shadow:0 0 10px 3px rgba(31,111,235,.6);pointer-events:none;opacity:0;transition:opacity .3s;will-change:transform';
  const style = document.createElement('style');
  style.textContent = '@keyframes __bladeRip{from{transform:scale(.35);opacity:.95}to{transform:scale(2.4);opacity:0}}';
  const mount = () => {
    (document.head || document.documentElement).appendChild(style);
    (document.body || document.documentElement).appendChild(cur);
  };
  if (document.body) mount(); else addEventListener('DOMContentLoaded', mount);
  let hideTimer;
  let suppressUntil = 0;
  window.__bladeCurHide = (ms) => { suppressUntil = Date.now() + (ms || 1200); cur.style.opacity = '0'; };
  const show = (x, y) => {
    if (Date.now() < suppressUntil) return;
    cur.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    cur.style.opacity = '1';
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { cur.style.opacity = '0'; }, 2000);
  };
  addEventListener('mousemove', (e) => show(e.clientX, e.clientY), { capture: true, passive: true });
  addEventListener('mousedown', (e) => {
    if (Date.now() < suppressUntil) return;
    show(e.clientX, e.clientY);
    const rip = document.createElement('div');
    rip.style.cssText = 'position:fixed;z-index:2147483646;left:' + (e.clientX - 12) + 'px;top:' + (e.clientY - 12) +
      'px;width:24px;height:24px;border-radius:50%;border:3px solid #1f6feb;pointer-events:none;' +
      'animation:__bladeRip .5s ease-out forwards';
    (document.body || document.documentElement).appendChild(rip);
    setTimeout(() => rip.remove(), 600);
  }, { capture: true, passive: true });
})()`

// ── Recorder：把某个标签的画面录成 mp4。daemon 里跨 `record start`/`record stop` 两次独立
// 调用持有状态（这两条命令是两个分开的一次性冷启动进程，靠 daemon 常驻才能把状态接起来）。
//
// 帧来自独立的 CDP screencast 会话（固定质量/分辨率，不受镜像面板自适应码率影响，也不影响
// 它——两条会话各自独立）。CDP 是变化驱动：画面静止时不吐帧，所以按「下一帧到达间隔」给上一
// 帧定时长（超过 500ms 的间隔截断到 500ms，压掉「等页面加载」的死时间，不然一段静止 10 秒的
// 页面会占掉 10 秒视频却什么信息量都没有）。最后用 ffmpeg 的 concat 变时长图片序列一次性编码，
// 每帧过一遍 scale+pad 滤镜统一画布尺寸——录制过程中如果镜像面板改了这个标签的视口大小（同一
// 个 CDP target，视口覆盖是后写者赢），各帧原始尺寸可能不一致，统一到画布尺寸后 concat 才能正
// 常编码，不需要按尺寸分段再拼接。
const RECORD_FRAME_GAP_CAP_MS = 500
const RECORD_STOP_GRACE_MS = 500 // 停止后再等一下，把最后一个动作的异步渲染截进去，不掐在半截
const RECORD_WIDTH = 1280
const RECORD_HEIGHT = 800

class Recorder {
  constructor() { this.active = false; this.cs = null; this.tmpDir = null; this.frames = []; this.outPath = null }
  isActive() { return this.active }
  async handle(browser, flags, pos, fail, io) {
    const sub = pos[0]
    if (sub === 'start') {
      if (this.active) fail('已经在录制：' + this.outPath + '（先 record stop）')
      const outPath = resolveRecordPath(pos[1], fail)
      const ctx = browser.contexts()[0] || (await browser.newContext())
      const page = await pick(userPages(ctx.pages()), flags, fail)
      await this._start(ctx, page, outPath, fail)
      io.log({ recording: true, path: outPath })
      return
    }
    if (sub === 'stop') {
      if (!this.active) fail('当前没有在录制')
      const outPath = await this._stop(fail, num(flags.timeout, 15000))
      io.log({ recording: false, path: outPath })
      return
    }
    if (sub === 'status') {
      io.log({ recording: this.active, path: this.active ? this.outPath : null, frames: this.frames.length })
      return
    }
    fail('record 用法: record start <path.mp4> | record stop | record status')
  }
  async _start(ctx, page, outPath, fail) {
    this.tmpDir = await mkdtemp(join(tmpdir(), 'ttmux-record-'))
    this.frames = []
    this.outPath = outPath
    try {
      this.cs = await ctx.newCDPSession(page)
    } catch (e) {
      throw new ChromeError('录制会话建立失败: ' + e.message)
    }
    this.cs.on('Page.screencastFrame', (frame) => this._onFrame(frame).catch(() => {}))
    await this.cs.send('Page.addScriptToEvaluateOnNewDocument', { source: cursorScript }).catch(() => {})
    await this.cs.send('Runtime.evaluate', { expression: cursorScript }).catch(() => {})
    await this.cs.send('Page.startScreencast', {
      format: 'jpeg', quality: 50, maxWidth: RECORD_WIDTH, maxHeight: RECORD_HEIGHT, everyNthFrame: 2,
    })
    this.active = true
  }
  async _onFrame(frame) {
    const idx = this.frames.length
    const file = join(this.tmpDir, `f${String(idx).padStart(6, '0')}.jpg`)
    writeFileSync(file, Buffer.from(frame.data, 'base64'))
    this.frames.push({ file, ts: Date.now() })
    await this.cs.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {})
  }
  async _stop(fail, timeoutMs = 0) {
    this.active = false
    const cs = this.cs
    const frames = this.frames
    const tmpDir = this.tmpDir
    const outPath = this.outPath
    this.cs = null
    try { await cs.send('Page.stopScreencast') } catch {}
    await sleep(RECORD_STOP_GRACE_MS) // 让最后一个动作的异步渲染多来一帧
    // screencast 是变化驱动：整段录制期间页面如果一直没有重绘（开始录制后立刻就 stop、或者
    // 就是在盯着一个静态页面看），可能一帧都没有——实测确会出现。与其报错让这段录制白录，
    // 不如退化成单帧兜底：录制结束时截一张当前画面权当只有一帧的视频，好过什么都没有。
    if (frames.length === 0) {
      try {
        const shot = await cs.send('Page.captureScreenshot', { format: 'jpeg', quality: 50 })
        const file = join(tmpDir, 'f000000.jpg')
        writeFileSync(file, Buffer.from(shot.data, 'base64'))
        frames.push({ file, ts: Date.now() })
      } catch {}
    }
    try { await cs.detach() } catch {}
    if (frames.length === 0) {
      await rm(tmpDir, { recursive: true, force: true }).catch(() => {})
      fail('没有捕获到任何画面帧（标签一直静止/不可见？）')
    }
    const listPath = join(tmpDir, 'list.txt')
    const lines = []
    for (let i = 0; i < frames.length; i++) {
      const next = frames[i + 1]
      const gapMs = next ? next.ts - frames[i].ts : RECORD_STOP_GRACE_MS
      const durS = Math.min(gapMs, RECORD_FRAME_GAP_CAP_MS) / 1000
      lines.push(`file '${frames[i].file.replace(/'/g, "'\\''")}'`, `duration ${durS.toFixed(3)}`)
    }
    lines.push(`file '${frames[frames.length - 1].file.replace(/'/g, "'\\''")}'`) // ffmpeg concat 的最后一帧要再列一次，否则最后一条 duration 不生效
    writeFileSync(listPath, lines.join('\n') + '\n')

    const finalOut = join(tmpDir, 'out.mp4')
    const vf = `scale=${RECORD_WIDTH}:${RECORD_HEIGHT}:force_original_aspect_ratio=decrease,pad=${RECORD_WIDTH}:${RECORD_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p`
    await runFFmpeg(['-y', '-f', 'concat', '-safe', '0', '-i', listPath, '-vf', vf, '-vsync', 'vfr', '-movflags', '+faststart', finalOut], fail, timeoutMs)

    await mkdir(dirname(outPath), { recursive: true }).catch(() => {})
    // 原子写入：先落到目标同目录的临时文件（ffmpeg 输出在系统临时目录，与 outPath 大概率不同
    // 文件系统，rename 会因 EXDEV 失败，所以先 copy 到同目录再 rename）再 rename，中途失败/被
    // 杀不会留一个半成品占住最终路径。
    const stagedOut = outPath + '.tmp'
    await rm(stagedOut, { force: true }).catch(() => {})
    await copyFile(finalOut, stagedOut)
    await rename(stagedOut, outPath)
    await rm(tmpDir, { recursive: true, force: true }).catch(() => {})
    return outPath
  }
}

function resolveRecordPath(raw, fail) {
  if (!raw) fail('record start 需要输出文件路径，如: record start out.mp4')
  let p = resolve(raw) // 相对路径按 daemon 已 chdir 到的客户端 cwd 解析，与截图的路径语义一致
  if (extname(p).toLowerCase() !== '.mp4') p += '.mp4'
  return p
}

function runFFmpeg(args, fail, timeoutMs) {
  return new Promise((resolvePromise, reject) => {
    let proc
    try {
      proc = spawn('ffmpeg', args, { stdio: ['ignore', 'ignore', 'pipe'] })
    } catch (e) {
      reject(new ChromeError('未找到 ffmpeg，录制需要系统装有 ffmpeg: ' + e.message))
      return
    }
    let stderr = ''
    proc.stderr.on('data', (c) => { stderr += c.toString('utf8'); if (stderr.length > 8192) stderr = stderr.slice(-8192) })
    proc.on('error', (e) => reject(new ChromeError('ffmpeg 启动失败（是否已安装？）: ' + e.message)))
    const watchdog = timeoutMs ? setTimeout(() => { proc.kill('SIGKILL') }, Math.max(timeoutMs, 60000)) : null
    proc.on('close', (code) => {
      clearTimeout(watchdog)
      if (code === 0) resolvePromise()
      else reject(new ChromeError('ffmpeg 编码失败(code ' + code + '): ' + stderr.slice(-500)))
    })
  })
}

// ── Session：daemon 里跨请求复用的 CDP 连接（一次性冷启动路径也走它，只是活不过一条命令） ──

class Session {
  constructor({ discover = discoverBrowser, connect = connectTarget, control = ScopedCDP.connect } = {}) {
    this.browser = null; this.cdp = ''; this.browserId = ''; this.recorder = new Recorder()
    this.discover = discover
    this.connect = connect
    this.control = control
    this.controlSocket = null
    this.controlUrl = ''
    this.targetId = ''
    this.recordingBrowser = null
    this.connections = new Map()
  }
  async browserFor(cdp, targetId = '') {
    const discovered = await this.discover(cdp)
    for (const [key, cached] of this.connections) {
      if (!cached.browser.isConnected() || cached.cdp !== cdp || cached.browserId !== discovered.id) {
        if (cached.browser === this.recordingBrowser && cached.browser.isConnected()) continue
        this.connections.delete(key)
        try { await cached.browser.close() } catch {}
      }
    }
    const key = JSON.stringify([cdp, discovered.id, targetId])
    let cached = this.connections.get(key)
    if (!cached) {
      try {
        const browser = await this.connect(discovered.websocketUrl, targetId)
        cached = { browser, cdp, browserId: discovered.id, targetId }
        this.connections.set(key, cached)
      } catch (e) {
        throw new ChromeError('连不上 Chrome (' + cdp + '): ' + e.message)
      }
    }
    this.browser = cached.browser
    this.cdp = cdp
    this.browserId = discovered.id
    this.targetId = targetId
    return this.browser
  }
  async run(verb, flags, pos, timeoutMs, io) {
    const cdp = flags.cdp || process.env.TTMUX_CHROME_CDP || 'http://127.0.0.1:9222'
    const fail = message => { throw new ChromeError(message) }
    if (verb === 'record' && pos[0] !== 'start') {
      await this.recorder.handle(this.recordingBrowser, flags, pos, fail, io)
      if (!this.recorder.isActive()) this.recordingBrowser = null
      return
    }
    const discovered = await this.discover(cdp)
    if (flags['expected-browser'] != null && flags['expected-browser'] !== discovered.id) throw new ChromeError('CHROME_BROWSER_CHANGED')
    if (!this.controlSocket || this.controlUrl !== discovered.websocketUrl) {
      this.controlSocket?.close()
      const control = await this.control(discovered.websocketUrl)
      this.controlSocket = control
      this.controlUrl = discovered.websocketUrl
      control.onclose = () => { if (this.controlSocket === control) this.controlSocket = null }
    }
    const control = this.controlSocket
    if (verb === 'capabilities') {
      await control.request('Browser.getVersion')
      io.log({ version: 'roami-browser-v1', browserId: discovered.id, features: ['target_id', 'operation_receipts', 'scene_observation', 'expected_scene'] })
      return
    }
    const listTargets = async () => (await control.request('Target.getTargets')).targetInfos
      .filter(t => t.type === 'page' && userPages([{ url: () => t.url }]).length)
    const targets = await listTargets()
    const liveTargets = new Set(targets.map(t => t.targetId))
    for (const [key, cached] of this.connections) {
      if (cached.cdp === cdp && cached.browserId === discovered.id && !liveTargets.has(cached.targetId) && cached.browser !== this.recordingBrowser) {
        this.connections.delete(key)
        try { await cached.browser.close() } catch {}
      }
    }
    if (verb === 'tabs') { io.log(targets.map((t, i) => ({ i, targetId: t.targetId, title: t.title, url: t.url }))); return }
    let created
    if (verb === 'new') {
      created = await control.request('Target.createTarget', { url: 'about:blank', background: !!flags['no-focus'] })
      if (!pos[0]) {
        const i = (await listTargets()).findIndex(t => t.targetId === created.targetId)
        io.log({ ...(i >= 0 ? { i } : {}), targetId: created.targetId, url: 'about:blank' })
        return
      }
    }
    const targetId = created?.targetId || selectTarget(targets, flags).targetId
    const scopedFlags = { ...flags, target: targetId }
    delete scopedFlags.tab; delete scopedFlags.url
    const browser = await this.browserFor(cdp, targetId)
    try {
      // record 的状态（进行中的 CDP screencast 会话）要跨 start/stop 两次独立调用存活，
      // 不能像其它动词那样是一次性的 executeVerb 调用，得单独路由到常驻的 recorder 实例。
      if (verb === 'record') {
        await this.recorder.handle(browser, scopedFlags, pos, fail, io)
        if (this.recorder.isActive()) this.recordingBrowser = browser
        return
      }
      if (created) {
        try { await executeVerb(browser, 'goto', scopedFlags, pos, timeoutMs, { log: () => {} }, this.browserId) }
        catch (error) { await control.request('Target.closeTarget', { targetId }).catch(() => {}); throw error }
        const i = (await listTargets()).findIndex(t => t.targetId === targetId)
        io.log({ ...(i >= 0 ? { i } : {}), targetId, url: pos[0] })
      } else await executeVerb(browser, verb, scopedFlags, pos, timeoutMs, io, this.browserId)
    } catch (e) {
      // Chrome 死在命令中途（被回收/重启）：丢弃缓存连接，下条命令干净重连；
      // 页面级错误（选择器超时等）原样往上抛，daemon_request_with_retry 据此判断要不要重试。
      if (this.browser && !this.browser.isConnected()) this.browser = null
      throw e
    }
  }
  async close() {
    // daemon 被杀（空闲自杀/SIGTERM/看门狗）时若正巧在录制，尽力落盘一份而不是丢掉——
    // 半途而废的录制总比什么都没有强，agent 至少能看到"进行到哪一步"。
    if (this.recorder.isActive()) {
      await this.recorder._stop(() => { throw new ChromeError('') }).catch(() => {})
    }
    const browsers = new Set([...this.connections.values()].map(entry => entry.browser))
    if (this.recordingBrowser) browsers.add(this.recordingBrowser)
    await Promise.allSettled([...browsers].map(browser => browser.close()))
    this.connections.clear()
    this.recordingBrowser = null
    this.browser = null
    this.controlSocket?.close()
    this.controlSocket = null
  }
}

// ── daemon：unix socket 常驻，串行处理（同一时刻只处理一条请求，chdir 才安全） ──────────

// 压测实测过的、明确是"瞬时性"而非"真错误"的失败特征：内存紧张/高并发时 Chrome/CDP 连接
// 被打断的典型报错。命中这些且动词在 IDEMPOTENT_VERBS 里才会被自动重试；其它错误（选择器
// 超时、URL 无效等）原样报给调用方，不能被这里的重试悄悄吞掉。
const TRANSIENT_ERROR_MARKERS = ['Page crashed', 'has been closed', 'Connection closed while reading from the driver', 'ERR_ABORTED']
// click/press/fill/type/eval/close 有副作用，"命令发出去了但没等到回复"这种不确定状态下
// 重试可能悄悄重复执行（比如表单重复提交）——不放进这个白名单，交给 agent 自己判断要不要
// 手动重试。其余只读或"重复执行等效于一次"的动词才安全自动重试。
const IDEMPOTENT_VERBS = new Set(['goto', 'url', 'title', 'text', 'attr', 'html', 'wait', 'screenshot', 'shot', 'pdf', 'tabs', 'new', 'fill'])
const isTransientError = (stderr) => TRANSIENT_ERROR_MARKERS.some((m) => stderr.includes(m))

function operationPayload(verb, flags, pos) {
  return [verb, pos, Object.entries(flags).filter(([key]) => !['operation-id', 'receipt-root'].includes(key)).sort(([a], [b]) => a.localeCompare(b))]
}

function makeIO() {
  const lines = []
  return { lines, log: (x) => { if (x !== undefined) lines.push(typeof x === 'string' ? x : JSON.stringify(x, null, 2)) } }
}

async function probeAlive(sockPath) {
  return new Promise((resolve) => {
    const s = net.connect(sockPath)
    const done = (ok) => { s.destroy(); resolve(ok) }
    s.once('connect', () => done(true))
    s.once('error', () => done(false))
    setTimeout(() => done(false), 1000)
  })
}

async function handleConnection(conn, session) {
  if (conn.destroyed) return // A queued liveness probe may have disconnected before its turn.
  // 看门狗兜底：内存紧张期间 Chrome/driver 被杀死后，playwright 客户端内部的重连逻辑可能
  // 陷入不带退避的忙等（不依赖那段代码自己配合退出，直接从外面强杀整个 daemon 进程更可靠）。
  // 下条命令的 daemonRequest() 连不上旧 socket 会自动重新拉起一个新 daemon，不需要人工介入。
  //
  // 定时值 = timeoutS，比客户端 daemonRequestWithRetry 里首次尝试的 fullTimeoutS(=timeoutMs/
  // 1000+35) 正好少 5 秒——看门狗总先于客户端自己的超时触发：daemon 被强杀时客户端第一次
  // 尝试的连接会立刻收到断连（而不是干等到自己超时），第二次重试就能连上刚重建的新 daemon。
  let buf = ''
  let req
  try {
    req = await new Promise((resolve, reject) => {
      conn.setTimeout(10000)
      conn.on('data', (chunk) => {
        buf += chunk.toString('utf8')
        const nl = buf.indexOf('\n')
        if (nl !== -1) resolve(JSON.parse(buf.slice(0, nl)))
      })
      conn.on('timeout', () => reject(new Error('recv timeout')))
      conn.on('error', reject)
      conn.on('close', () => reject(new Error('connection closed before request complete')))
    })
  } catch {
    conn.destroy()
    return
  }
  let argv = Array.isArray(req.argv) ? req.argv : []
  // Older daemons reject this verb before touching a page instead of ignoring new flags.
  const operationBound = argv[0] === '_operation' || argv[0] === '_scene'
  if (argv[0] === '_managed' || operationBound) argv = argv.slice(1)
  if (req.cwd && existsSync(req.cwd)) { try { process.chdir(req.cwd) } catch {} }
  const { verb, flags, pos } = parseArgs(argv)
  const timeoutMs = num(flags.timeout, 15000)
  const timeoutS = timeoutMs === 0 ? 0 : effectiveTimeoutMs(verb, timeoutMs) / 1000 + 30
  conn.setTimeout(timeoutS * 1000)
  const io = makeIO()
  let code = 0
  let stderr = ''
  const watchdog = timeoutS ? setTimeout(() => { process.exit(1) }, timeoutS * 1000) : null
  try {
    if (flags['operation-id']) {
      if (!operationBound || !OPERATION_VERBS.has(verb)) throw new ChromeError('CHROME_OPERATION_UNSUPPORTED')
      const receipts = new OperationReceipts(flags['receipt-root'])
      const record = await receipts.execute(flags['operation-id'], OperationReceipts.hash(operationPayload(verb, flags, pos)), async () => {
        const output = makeIO()
        await session.run(verb, flags, pos, timeoutMs, output)
        return { stdout: output.lines.length ? output.lines.join('\n') + '\n' : '' }
      })
      io.log(record)
    } else {
      await session.run(verb, flags, pos, timeoutMs, io)
    }
  } catch (e) {
    code = 1
    stderr = 'chrome: ' + (e?.message || String(e)) + '\n'
  } finally {
    clearTimeout(watchdog)
  }
  const stdout = io.lines.length ? io.lines.join('\n') + '\n' : ''
  try { conn.end(JSON.stringify({ code, stdout, stderr })) } catch {}
}

async function daemonMain() {
  // OOM 牺牲顺序：daemon 常驻但体量小，配额吃紧时希望先于用户的 dev server 被杀
  // （Linux-only；其它平台 /proc 不存在，写失败静默忽略即可）。
  try { writeFileSync('/proc/self/oom_score_adj', '900') } catch {}

  if (existsSync(SOCK_PATH)) {
    if (await probeAlive(SOCK_PATH)) return // 已有活 daemon，本次是重复拉起，直接退出
    try { unlinkSync(SOCK_PATH) } catch {} // 连不上的残留 socket 文件，清掉重建
  }

  const session = new Session()
  let queue = Promise.resolve() // 串行队列：同一时刻只处理一条请求（chdir 是全进程状态，必须串行）
  let idleTimer = null
  let pendingConnections = 0
  // 录制中不能空闲自杀：录制期间 agent 可能在做别的事，daemon 收不到新命令，但录制本身要
  // 一直挂着（CDP screencast 会话）——空闲计时器到点先看是不是还在录，是就顺延，不能真杀掉。
  const scheduleIdleCheck = () => {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      if (session.recorder.isActive() || pendingConnections > 0) { scheduleIdleCheck(); return }
      shutdown()
    }, DAEMON_IDLE_MS)
  }
  const server = net.createServer((conn) => {
    pendingConnections++
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
    queue = queue
      .then(() => handleConnection(conn, session))
      .catch(() => {})
      .finally(() => { pendingConnections--; if (pendingConnections === 0) scheduleIdleCheck() })
  })
  const shutdown = async () => {
    server.close()
    await session.close()
    try { unlinkSync(SOCK_PATH) } catch {}
    process.exit(0)
  }
  process.on('SIGTERM', shutdown)
  process.on('SIGINT', shutdown)

  await mkdir(dirname(SOCK_PATH), { recursive: true }).catch(() => {})
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(SOCK_PATH, resolve)
  })
  scheduleIdleCheck() // 空闲自杀：释放 CDP 连接，daemon 不常驻占用（录制中会顺延，见上）
}

// ── 客户端：一次性冷启动进程，把命令转发给 daemon（连不上就现拉起） ─────────────────────

function spawnDaemon() {
  return new Promise((resolve) => {
    let logFd
    try { logFd = openSync(DAEMON_LOG, 'a') } catch { resolve(false); return }
    let child
    try {
      child = spawn(process.execPath, [SELF_PATH, '_daemon'], {
        detached: true, stdio: ['ignore', logFd, logFd],
      })
    } catch { resolve(false); return }
    child.unref()
    ;(async () => {
      for (let i = 0; i < 100; i++) {
        if (existsSync(SOCK_PATH) && await probeAlive(SOCK_PATH)) { resolve(true); return }
        await sleep(50)
      }
      resolve(false)
    })()
  })
}

// 把命令转发给 daemon；daemon 不在则拉起。返回 {resp, sentBeforeFailure}。resp 为 null 表示
// 失败；sentBeforeFailure 标记失败发生在"命令已经发给 daemon 之后"——这种情况下命令有没有
// 真的执行到一半是不确定的，daemonRequestWithRetry 据此判断非幂等动词能不能安全重试（见
// IDEMPOTENT_VERBS）。连不上 daemon（还没写过 socket）永远是 sentBeforeFailure=false，零副
// 作用，随便重试。
async function daemonRequest(argv, timeoutS) {
  for (let attempt = 0; attempt < 2; attempt++) {
    let client
    try {
      client = await new Promise((resolve, reject) => {
        const s = net.connect(SOCK_PATH)
        s.once('connect', () => resolve(s))
        s.once('error', reject)
      })
    } catch {
      if (attempt === 1) return { resp: null, sentBeforeFailure: false }
      if (!(await spawnDaemon())) return { resp: null, sentBeforeFailure: false }
      continue
    }
    try {
      const respText = await new Promise((resolve, reject) => {
        let out = ''
        client.setTimeout(timeoutS * 1000)
        client.on('data', (c) => { out += c.toString('utf8') })
        client.on('end', () => resolve(out))
        client.on('timeout', () => reject(new Error('daemon request timeout')))
        client.on('error', reject)
        client.write(JSON.stringify({ argv, cwd: process.cwd() }) + '\n')
      })
      return { resp: JSON.parse(respText), sentBeforeFailure: false }
    } catch {
      return { resp: null, sentBeforeFailure: true } // 已经写过 socket，副作用不确定
    } finally {
      client.destroy()
    }
  }
  return { resp: null, sentBeforeFailure: false }
}

// daemonRequest 的重试外壳。压测发现内存紧张、或高并发时 daemon 偶发因瞬时故障（连不上、
// 命令执行到一半断连、Chrome/CDP 连接被打断）失败——这些原本会直接暴露成 agent 可见的一次
// 调用失败，但下一次调用往往就恢复正常（daemon 有看门狗兜底不会永久卡死）。与其让 agent 自
// 己发现失败再决定要不要重试，这里把"已知大概率会自愈"的失败自动重试掉，只把重试耗尽后仍然
// 失败的、或本来就不安全重试的情况（见 IDEMPOTENT_VERBS）暴露给调用方。
//
// 超时预算：只有第一次尝试给足调用方指定的完整超时（保留"就是要等一个慢页面"这种合法场景
// 的语义）；重试是在"上一次大概率是撞见了 daemon/Chrome 瞬时故障"的前提下再搏一次，不该再
// 陪等一整个完整预算——重试如果每次都用完整预算，最坏情况会从单次调用的 ~50s 叠加到 3 次共
// ~150s，对 agent 来说是明显的可感知卡顿。重试专用超时给一个较短的固定上限。
async function daemonRequestWithRetry(argv, timeoutMs, verb, request = daemonRequest, pause = sleep) {
  const fullTimeoutS = timeoutMs === 0 ? 0 : effectiveTimeoutMs(verb, timeoutMs) / 1000 + 35
  const retryTimeoutS = Math.min(fullTimeoutS, 20)
  const flags = parseArgs(argv).flags
  const attempts = flags['no-retry'] || flags['operation-id'] ? 1 : 3
  const requestArgv = flags['expected-scene'] != null || flags['expected-browser'] != null || flags['no-focus'] ? ['_scene', ...argv]
    : flags['operation-id'] ? ['_operation', ...argv]
    : flags.target != null || flags['no-retry'] ? ['_managed', ...argv] : argv
  let resp = null
  for (let i = 0; i < attempts; i++) {
    const r = await request(requestArgv, i === 0 ? fullTimeoutS : retryTimeoutS)
    resp = r.resp
    const last = i === attempts - 1
    if (resp === null) {
      if (r.sentBeforeFailure && !IDEMPOTENT_VERBS.has(verb)) return null
      if (last) return null
      await pause(300 * (i + 1))
      continue
    }
    const transient = resp.code && IDEMPOTENT_VERBS.has(verb) && isTransientError(resp.stderr || '')
    if (transient && !last) { await pause(300 * (i + 1)); continue }
    return resp
  }
  return resp
}

// ── 入口 ──────────────────────────────────────────────────────────────────────────────

async function main() {
  const argv = process.argv.slice(2)
  const { verb, flags, pos } = parseArgs(argv)
  // help/setup 正常经 launcher.sh 拦截，不会走到这里；留个兜底给直接 `node driver.mjs` 调用。
  if (verb === 'help' || verb === '-h' || verb === '--help') { console.log('chrome help 见 launcher.sh 或 README'); return }
  if (verb === '-v' || verb === '--version') { console.log('chrome (ttmux) v0.2.0'); return }
  if (verb === '_daemon') { await daemonMain(); return }

  const timeoutMs = num(flags.timeout, 15000)

  if (verb === 'operation-status' || verb === 'operation-cancel') {
    const receipts = new OperationReceipts(flags['receipt-root'])
    const record = verb === 'operation-cancel' ? await receipts.cancel(flags['operation-id']) : await receipts.read(flags['operation-id'])
    console.log(JSON.stringify(record))
    return
  }
  if (flags['operation-id'] || flags['receipt-root']) {
    if (!OPERATION_VERBS.has(verb) || flags.fresh) throw new ChromeError('CHROME_OPERATION_UNSUPPORTED')
    const receipts = new OperationReceipts(flags['receipt-root'])
    const planned = await receipts.begin(flags['operation-id'], operationPayload(verb, flags, pos))
    if (!planned.dispatch) { console.log(JSON.stringify(planned.record)); return }
  }

  if ((verb === 'screenshot' || verb === 'shot') && flags.fresh) {
    // 私有实例与共享 Chrome 无关，不占 daemon
    const io = makeIO()
    try {
      await freshScreenshot(flags, pos, timeoutMs, io)
      process.stdout.write(io.lines.length ? io.lines.join('\n') + '\n' : '')
    } catch (e) {
      console.error('chrome: ' + (e?.message || String(e)))
      process.exitCode = 1
    }
    return
  }

  const resp = await daemonRequestWithRetry(argv, timeoutMs, verb)
  if (resp === null) {
    console.error(`chrome: daemon 不可用（拉起失败或通信异常，日志见 ${DAEMON_LOG}）`)
    process.exitCode = 1
    return
  }
  if (resp.stdout) process.stdout.write(resp.stdout)
  if (resp.stderr) process.stderr.write(resp.stderr)
  process.exitCode = resp.code || 0
}

export { parseArgs, pickPage, targetIdentity, daemonRequestWithRetry, Session, navigationWait, handleConnection, cdpScreenshot, withInsecureTLS }

if (process.argv[1] && realpathSync(process.argv[1]) === SELF_PATH) {
  main().catch((e) => { console.error('chrome: ' + (e?.message || String(e))); process.exitCode = 1 })
}
