// Read old browser tabs once when initializing the server workspace.
const KEY = 'roam.terms'

/** 文件标签：task 是从哪个任务（worktree）开的——路径条的根、右栏跟着它走 */
export type FileTab = { path: string; preview: boolean; mode: 'source' | 'preview' | 'changes'; task: string }
/** 标签条不按任务隔离（用户拍板）：会话标签全显示，文件标签一条平铺列表；diff 类标签不存 */
export type TabSet = {
  terms: string[]; active: string
  files: FileTab[]
  activeFile: string
}
type Entry = TabSet & { at: number }

/** 单机（没有 nodeId）也占一格，键是空串——单机与多机走同一条路径，不写分支 */
function slot(nodeId: string | null): string {
  return nodeId || ''
}

function readAll(): Record<string, Entry> {
  try {
    const raw = localStorage.getItem(KEY)
    const v = raw ? JSON.parse(raw) : null
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

export function forgetTabs(nodeId: string | null) {
  const all = readAll()
  delete all[slot(nodeId)]
  try {
    if (Object.keys(all).length) localStorage.setItem(KEY, JSON.stringify(all))
    else localStorage.removeItem(KEY)
  } catch { /* Migration can be retried safely. */ }
}

/** 取一台机器上次开着的标签；没记过就是空。 */
export function loadTabs(nodeId: string | null): TabSet {
  const e = readAll()[slot(nodeId)]
  if (!e || !Array.isArray(e.terms)) return { terms: [], active: '', files: [], activeFile: '' }
  // 老数据没有 files 字段：照常读。files 曾按任务分片存成 {任务: [...]}（22 设计第一版），
  // 现在是一条平铺列表；老形状摊平、把分片键写进 task
  const one = (f: any, task: string): FileTab | null => (f && typeof f.path === 'string')
    ? { path: f.path, preview: !!f.preview, mode: f.mode === 'preview' || f.mode === 'changes' ? f.mode : 'source', task: typeof f.task === 'string' ? f.task : task }
    : null
  const files: FileTab[] = []
  const rawFiles: unknown = e.files
  if (Array.isArray(rawFiles)) {
    for (const f of rawFiles) { const t = one(f, ''); if (t) files.push(t) }
  } else if (rawFiles && typeof rawFiles === 'object') {
    for (const [k, v] of Object.entries(rawFiles as Record<string, unknown>)) {
      if (!Array.isArray(v)) continue
      for (const f of v) { const t = one(f, k); if (t) files.push(t) }
    }
  }
  const rawActive: unknown = e.activeFile
  let activeFile = ''
  if (typeof rawActive === 'string') activeFile = rawActive
  else if (rawActive && typeof rawActive === 'object') activeFile = Object.values(rawActive as Record<string, unknown>).find((v): v is string => typeof v === 'string' && !!v) || ''
  if (activeFile && !files.some((f) => f.path === activeFile)) activeFile = ''
  return { terms: e.terms.filter((x) => typeof x === 'string' && x), active: typeof e.active === 'string' ? e.active : '', files, activeFile }
}

/** 会话 id 的形状（后端 internal/id：YYYY-MMDD-HHMM-rand4）。 */
const ID_RE = /^\d{4}-\d{4}-\d{4}-[a-z0-9]{4}$/

/**
 * 还原前先滤一遍：**长得像 id 但在这台机器上查无此会话**的一律丢掉。
 *
 * 不丢就会长出打不开的空标签——切机器、或者会话在别处被关掉，都会走到这。
 * 不像 id 的 token 是老链接里存的会话名（那时 URL 写的是名字），照旧放行：
 * 名字查不到可能只是列表还没刷到。
 */
export function dropDeadTokens(tokens: string[], knownIds: Record<string, string>): string[] {
  return tokens.filter((tok) => !ID_RE.test(tok) || !!knownIds[tok])
}
