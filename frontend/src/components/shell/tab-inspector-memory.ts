// 每个标签各记一份右栏状态：这个标签上次是开着还是收着、停在哪个面板。
//
// 右栏（文件 / Git / Worktree）原本是整个工作区一份状态：在 A 标签里开了 Git 看改动，
// 切到 B 标签写代码把它收起来，再切回 A——它还是收着的，得重开一次。可「开不开右栏」
// 本来就是跟着手头这件事走的：读代码的标签要文件树，收尾的标签要 Git。
//
// 存 localStorage 而不是服务端偏好，理由同 term-tabs-store：这是「这台浏览器上那些标签
// 长什么样」，跟设备走不跟账号走，而且偏好是异步回来的，切标签等不起（见 AGENTS.md
// 「Preferences Arrive Late」）。

import type { InspectorPanelKind } from './InspectorPanels'

const KEY = 'roam.tabInspector'

export type TabInspector = { collapsed: boolean; panel: InspectorPanelKind }

/**
 * 标签的身份。文件标签用路径、会话标签用会话名，前缀区分——
 * 两者同处一条标签条，一个叫 `/a/b` 一个叫 `2026-0914-1030-ab12`，不加前缀也撞不上，
 * 但前缀让存下来的东西自解释，翻 localStorage 时一眼知道那条是什么。
 */
export function tabKey(o: { active: string; activeFile: string }): string {
  if (o.activeFile) return `f:${o.activeFile}`
  return o.active ? `s:${o.active}` : ''
}

const isPanel = (v: unknown): v is InspectorPanelKind => v === 'files' || v === 'git' || v === 'worktree'

function readAll(): Record<string, TabInspector> {
  try {
    const raw = localStorage.getItem(KEY)
    const v = raw ? JSON.parse(raw) : null
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
    const out: Record<string, TabInspector> = {}
    for (const [k, rec] of Object.entries(v as Record<string, unknown>)) {
      const r = rec as { collapsed?: unknown; panel?: unknown }
      if (r && typeof r.collapsed === 'boolean') out[k] = { collapsed: r.collapsed, panel: isPanel(r.panel) ? r.panel : 'files' }
    }
    return out
  } catch { return {} }
}

function writeAll(all: Record<string, TabInspector>) {
  try { localStorage.setItem(KEY, JSON.stringify(all)) } catch { /* 隐私模式/配额满：记不住而已，不该崩 */ }
}

export function rememberTabInspector(key: string, rec: TabInspector) {
  if (!key) return
  const all = readAll()
  const cur = all[key]
  if (cur && cur.collapsed === rec.collapsed && cur.panel === rec.panel) return
  all[key] = rec
  writeAll(all)
}

/** 没记过就返回 null——调用方据此「保持现状」，而不是把它当成收起 */
export function recallTabInspector(key: string): TabInspector | null {
  if (!key) return null
  return readAll()[key] || null
}

/**
 * 切到新标签时该摆成什么样。没记过就**保持现状**——新开一个标签不该把右栏弹开，
 * 也不该把正开着的收掉；它自己被切走时才留下第一笔。
 */
export function nextInspector(rec: TabInspector | null, cur: TabInspector): TabInspector {
  return rec || cur
}

/**
 * 只留还开着的那些标签。关掉的标签没人会再切回去，留着就是一张只涨不消的表；
 * 而文件标签的键是路径，同一个仓库翻上几百个文件，一年后这张表比标签本身大得多。
 *
 * **一个键都没有时什么也不做**：那不是「一个标签都没开」，而是「还没还原完」。刷新后
 * id↔名字的映射一到，标签还原和 URL 回写会在同一轮里跑，回写那次手里的标签还是空的——
 * 照着清一遍，等于每次刷新都把这张表抹平（第一版就是这么丢的，刷新后全部忘光）。
 */
export function pruneTabInspector(keys: string[]) {
  const live = new Set(keys.filter(Boolean))
  if (!live.size) return
  const all = readAll()
  let changed = false
  for (const k of Object.keys(all)) {
    if (live.has(k)) continue
    delete all[k]
    changed = true
  }
  if (changed) writeAll(all)
}
