// 与后端 /api 通信的薄封装；401 时触发回调（跳登录）

import { nodeApi } from './components/cluster/node-url'

let onUnauth: () => void = () => {}
export function setUnauthorizedHandler(f: () => void) {
  onUnauth = f
}

// opts.signal 给「打字时连着问」的接口（⌘K 搜索）用：下一次请求发出前先掐掉上一次，
// 否则慢的那条后回来会把新结果盖掉。
export async function api(method: string, path: string, body?: any, opts?: { signal?: AbortSignal }): Promise<any> {
  const r = await fetch(nodeApi(path), {
    method,
    signal: opts?.signal,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    // 移动端(Safari/WebView)会对无 Cache-Control 的 GET 做启发式缓存，导致文件实时重载
    // 轮询的 /file/stat 一直拿到旧 mtime → 不刷新。强制不走缓存，每次真打网络。
    cache: 'no-store',
  })
  if (r.status === 401) {
    onUnauth()
    throw new Error('UNAUTHORIZED')
  }
  const ct = r.headers.get('content-type') || ''
  const data = ct.includes('json') ? await r.json() : await r.text()
  if (!r.ok) {
    const errObj = data?.error || {}
    const msg = errObj.message || errObj.code || 'HTTP ' + r.status
    const err = new Error(msg) as Error & { apiError?: Record<string, any> }
    err.apiError = errObj
    throw err
  }
  if (method === 'POST' && (body?.activity || (path === '/tasks' && body?.type === 'agent'))) {
    window.dispatchEvent(new Event('roam:footprints-updated'))
  }
  return data
}

// 上传文件到指定目录（multipart）。返回 { dir, saved: 绝对路径[] }。
export async function upload(dir: string, files: FileList | File[]): Promise<{ dir: string; saved: string[] }> {
  const form = new FormData()
  form.append('dir', dir)
  // Go 的 multipart 会用 filepath.Base 抹掉上传文件名里的路径，所以文件夹层级要靠
  // 独立的 paths 字段平行传：第 i 个 file 对应第 i 个 path(相对路径，普通文件为空)。
  Array.from(files).forEach((f) => {
    form.append('files', f)
    form.append('paths', (f as any).webkitRelativePath || '')
  })
  const r = await fetch(nodeApi('/upload'), { method: 'POST', body: form })
  if (r.status === 401) { onUnauth(); throw new Error('UNAUTHORIZED') }
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new Error(data?.error?.message || data?.error?.code || 'HTTP ' + r.status)
  return data.data
}

// 从剪贴板 Blob 创建带时间戳文件名的 File，用于粘贴图片后上传。
export function makeClipboardImageFile(blob: Blob, mime: string, index: number): File {
  const sub = mime.split('/')[1] || 'png'
  const ext = sub === 'jpeg' ? 'jpg' : sub === 'svg+xml' ? 'svg' : sub
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  const suffix = index > 0 ? `-${index + 1}` : ''
  // 末尾那截随机串是为了**让路径可以提前算出来**：
  // 后端 uniquePath 只在重名时才改名（改成 "xxx (1).png"），而终端粘贴那条路
  // 要在上传**开始前**就把 @路径 敲进去（见 TerminalPane.pasteImage 的注释）。
  // 只到秒的时间戳同一秒粘两次就会撞，一撞后端就改名、前端敲进去的路径就是错的。
  return new File([blob], `clipboard-${ts}${suffix}-${randomToken()}.${ext}`, { type: mime })
}

/** 4 字符 base36 随机串，够把同秒撞名压到可以忽略。 */
function randomToken(): string {
  const a = new Uint8Array(3)
  ;(globalThis.crypto || (globalThis as any).msCrypto)?.getRandomValues?.(a)
  return Array.from(a, (b) => b.toString(36).padStart(2, '0')).join('').slice(0, 4)
}

/** 上传后这个文件会落在哪。与后端 uniquePath 的「不重名就原样」约定配套。 */
export function uploadedPathOf(dir: string, file: File): string {
  return (dir.endsWith('/') ? dir.slice(0, -1) : dir) + '/' + file.name
}

// 上传录音(WAV)做语音识别，返回识别出的文本。服务商与密钥由后端配置。
export async function transcribe(audio: Blob): Promise<string> {
  const form = new FormData()
  form.append('audio', audio, 'audio.wav')
  const r = await fetch(nodeApi('/speech/transcribe'), { method: 'POST', body: form })
  if (r.status === 401) { onUnauth(); throw new Error('UNAUTHORIZED') }
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new Error(data?.error?.message || data?.error?.code || 'HTTP ' + r.status)
  return data?.data?.text || ''
}

export async function openEventStream(path: string, signal: AbortSignal): Promise<Response> {
  const response = await fetch(nodeApi(path), { signal, cache: 'no-store', headers: { Accept: 'text/event-stream' } })
  if (response.status === 401) { onUnauth(); throw new Error('UNAUTHORIZED') }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.error?.code || 'HTTP ' + response.status) as Error & { apiError?: Record<string, unknown> }
    error.apiError = body?.error
    throw error
  }
  return response
}
