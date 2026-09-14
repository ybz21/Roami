// 文件树展开到哪几层，按根目录各记一份。
//
// 树本来只把展开态放在组件 state 里：刷新一次、或者切到别的任务再切回来，整棵树重新收拢成
// 一层。而人在一个仓库里翻的就那么几条路径（`frontend/src/components/...`），每次都要一级级
// 再点开一遍。
//
// 按**根目录**记而不是按标签：右栏那棵树的根是当前任务的 worktree，同一个 worktree 的两个
// 标签看到的本来就是同一棵树；换任务换根，各记各的正好。
//
// 存 localStorage：这和「这台浏览器上那些标签长什么样」是同一类东西（见 term-tabs-store），
// 跟设备走不跟账号走。

const KEY = 'roam.treeExpanded'
/** 最多记几个根目录，超了按最后用到的时间淘汰 */
const MAX_ROOTS = 12
/** 每个根最多记几条展开路径：手滑把 node_modules 一层层点开也不至于把配额撑爆 */
const MAX_DIRS = 300

type Entry = { dirs: string[]; at: number }

function readAll(): Record<string, Entry> {
  try {
    const raw = localStorage.getItem(KEY)
    const v = raw ? JSON.parse(raw) : null
    if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
    const out: Record<string, Entry> = {}
    for (const [k, e] of Object.entries(v as Record<string, unknown>)) {
      const rec = e as { dirs?: unknown; at?: unknown }
      if (rec && Array.isArray(rec.dirs)) {
        out[k] = { dirs: rec.dirs.filter((d): d is string => typeof d === 'string' && !!d), at: typeof rec.at === 'number' ? rec.at : 0 }
      }
    }
    return out
  } catch { return {} }
}

function writeAll(all: Record<string, Entry>) {
  try { localStorage.setItem(KEY, JSON.stringify(all)) } catch { /* 隐私模式/配额满：记不住而已，不该崩 */ }
}

/** 取一个根目录上次展开的那些目录。只返回**还在这个根底下**的路径——换过机器、目录被移走的那些直接丢。 */
export function loadExpandedDirs(root: string): string[] {
  if (!root) return []
  const e = readAll()[root]
  if (!e) return []
  return e.dirs.filter((d) => d.startsWith(root))
}

export function saveExpandedDirs(root: string, dirs: string[]) {
  if (!root) return
  const all = readAll()
  // at 严格递增而不是直接取 Date.now()：一次展开会连着写好几笔，时间戳一撞，下面的淘汰
  // 就只能按 key 顺序瞎猜，可能把刚用过的那个根挤掉（同 term-tabs-store 的账）。
  const maxAt = Object.values(all).reduce((m, e) => Math.max(m, e.at || 0), 0)
  const kept = dirs.filter((d) => d && d.startsWith(root)).slice(0, MAX_DIRS)
  if (!kept.length) delete all[root]
  else all[root] = { dirs: kept, at: Math.max(Date.now(), maxAt + 1) }
  const others = Object.keys(all).filter((k) => k !== root)
  if (others.length > MAX_ROOTS - 1) {
    others.sort((a, b) => (all[b].at || 0) - (all[a].at || 0))
    for (const k of others.slice(MAX_ROOTS - 1)) delete all[k]
  }
  writeAll(all)
}
