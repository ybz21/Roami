// 「当前机器」与它的 URL 前缀——多机的全部寻址收口在这一个文件。
//
// 单机与多机走**同一份代码**：没有 currentNodeId 时 nodePath() 返回今天的路径，
// 一个字节都不差。这就是「没连中心 就零变化」在实现层面的保证——不是靠两条分支，
// 是靠一个恒等式。所以别在调用处写 `isHub ? … : …`，那等于把分支散回去。
//
// 寻址只用**稳定 nodeId**，显示名可重命名、可重复，永不参与路由（见
// docs/design/cluster/architecture.html §4）。
import { useSyncExternalStore } from 'react'

export type ClusterNode = {
  id: string
  name: string
  hostname: string
  os: string
  version: string
  group?: string
  capabilities?: string[]
  sessionCount: number
  load: number
  latencyMs: number
  online: boolean
}

const MIRROR = 'roam.nodeId'

// 首帧就要有值，否则第一批请求会打到错的机器上——偏好是异步到的，靠不住
// （AGENTS.md「Preferences Arrive Late」）。所以当前机器**先读本地镜像**，
// 中心的推荐值只在本地没有或已失效时才用。
function readMirror(): string | null {
  try {
    return localStorage.getItem(MIRROR) || null
  } catch {
    return null
  }
}

let nodeId: string | null = readMirror()
let nodes: ClusterNode[] = []
let hub = false
const subs = new Set<() => void>()

function emit() {
  subs.forEach((f) => f())
}

function subscribe(f: () => void) {
  subs.add(f)
  return () => {
    subs.delete(f)
  }
}

/** 当前机器 id；null = 单机（或直连某台节点的本机口）。 */
export function currentNodeId(): string | null {
  return nodeId
}

/** 是否连着中心。单机时为 false，此时所有多机 UI 都不渲染。 */
export function isHubMode(): boolean {
  return hub
}

export function clusterNodes(): ClusterNode[] {
  return nodes
}

export function currentNode(): ClusterNode | null {
  return nodes.find((n) => n.id === nodeId) || null
}

export function setCurrentNode(id: string | null) {
  if (nodeId === id) return
  nodeId = id
  try {
    if (id) localStorage.setItem(MIRROR, id)
    else localStorage.removeItem(MIRROR)
  } catch { /* 无痕模式：内存里仍然对，只是刷新后回到推荐节点 */ }
  emit()
}

/**
 * 中心自己处理、**永远不能加节点前缀**的路径。
 *
 * 认证是最要命的一条：登录发到 /n/<id>/api/login 会被转发到那台**节点**，校验的是
 * 节点的口令而不是中心的——于是「用中心的口令登不进去，用某台机器的口令反而能进」，
 * 而且这个错法完全看不出来。踩过：全新 profile 没有 nodeId，测试一路不带前缀全绿，
 * 真实浏览器里存着上次的 nodeId 就必炸。
 *
 * /version 与 /update-check 同理：它们说的是「你正连着的这个入口」的版本。
 */
const HUB_LOCAL = ['/login', '/logout', '/setup', '/pubconfig', '/me', '/version', '/update-check']

function isHubLocal(path: string): boolean {
  const p = path.split('?')[0]
  return HUB_LOCAL.some((x) => p === x || p.startsWith(x + '/')) || p.startsWith('/hub/')
}

/**
 * 给路径加上机器前缀。**所有**业务 HTTP / WS / 原生资源 URL 都要过这里——
 * 包括 <img src>、<iframe src>、<a download>、window.open 这些加不了 header 的，
 * 这也正是身份走路径而不走 header 的原因。认证类路径除外，见 HUB_LOCAL。
 */
export function nodePath(path: string, originNode: string | null = nodeId): string {
  if (!originNode) return path
  // path 形如 /api/login；这里比的是去掉 /api 之后的那一段
  const rel = path.startsWith('/api') ? path.slice(4) : path
  if (isHubLocal(rel)) return path
  return `/n/${encodeURIComponent(originNode)}${path}`
}

/** `/api/...` 的简写；传的 p 以 / 开头，如 nodeApi('/sessions')。 */
export function nodeApi(p: string): string {
  return nodePath('/api' + p)
}

/** WebSocket 绝对地址（Terminal / 镜像 / 信令都用它拼）。 */
export function nodeWs(p: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${nodePath('/api' + p)}`
}

/** 镜像页要把「host + 路径」塞进查询参数（DevTools 的 wss= 就是这么要的）。 */
export function nodeWsHostPath(p: string): string {
  return `${location.host}${nodePath('/api' + p)}`
}

export function useCurrentNodeId(): string | null {
  return useSyncExternalStore(subscribe, currentNodeId, () => null)
}

export function useClusterNodes(): ClusterNode[] {
  return useSyncExternalStore(subscribe, clusterNodes, () => [])
}

export function useHubMode(): boolean {
  return useSyncExternalStore(subscribe, isHubMode, () => false)
}

/**
 * 启动引导。**必须在应用发出第一条业务请求之前跑完**，否则那几条会打到 /api/*，
 * 在 中心上是 404。它只打一个 中心本地 端点，不依赖 current node
 * ——反过来就是死循环：要读偏好得先知道去哪台机器读。
 *
 * 单机后端没有这个路由，404 即判定为单机，此后一切照旧。
 */
export async function bootstrapCluster(): Promise<void> {
  try {
    const r = await fetch('/api/hub/bootstrap', { cache: 'no-store' })
    if (!r.ok) return // 404 = 单机；401 = 未登录，登录后 App 会再引导一次
    const data = (await r.json())?.data || {}
    nodes = data.nodes || []
    hub = true
    const online = nodes.filter((n) => n.online)
    // 顺序：URL 深链 > 本地镜像 > Hub 推荐。前两者不发请求，所以首帧就定得下来。
    const fromUrl = new URLSearchParams(location.hash.split('?')[1] || '').get('node')
    const candidates = [fromUrl, nodeId, data.recommended]
    const pick = candidates.find((id) => id && online.some((n) => n.id === id))
      || online[0]?.id || null
    setCurrentNode(pick)
    emit()
  } catch {
    // 网络抖动：当单机处理。真连着中心 的话，下一次刷新会自愈，
    // 而误判成多机（把请求打到 /n/<不存在>）反而会让整个应用不可用。
  }
}

/** 刷新节点列表（切换器打开、掉线重连后调）。 */
export async function refreshClusterNodes(): Promise<void> {
  if (!hub) return
  try {
    const r = await fetch('/api/hub/nodes', { cache: 'no-store' })
    if (!r.ok) return
    nodes = (await r.json())?.data || []
    emit()
  } catch { /* 保留上一批，不要闪成空 */ }
}
