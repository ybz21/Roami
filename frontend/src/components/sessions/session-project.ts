// 会话 → 项目 的归属表（14 设计 §6.3）。
//
// 终端标签是跨页常驻的：你在概览页开了 roam 的会话，切到别的项目页，标签还在那儿。
// 标签上只写会话名的话，第三个标签是哪个项目的就得靠记。所以标签统一写
// `项目 · 会话`，分支进 Tooltip——而不是再加一条 context strip（14 §6.3.2）。
//
// 和 session-label 一样是模块级小表 + useSyncExternalStore：要用它的地方（终端标签、
// 会话胶囊、标签右键菜单）散在各处，数据源却只有 App 那一份轮询。
import { nativeSessionName, type NativeSessionRecord } from './session-record'
import { useSyncExternalStore } from 'react'

export type SessionProject = { key: string; name: string; dir: string; branch?: string; worktree?: string }

let table: Record<string, SessionProject> = {}
const listeners = new Set<() => void>()

/** 内容没变就不触发重渲染——这张表 15s 刷一次，绝大多数时候是一样的。 */
export function setSessionProjects(next: Record<string, SessionProject>) {
  const keys = Object.keys(next)
  const same = keys.length === Object.keys(table).length && keys.every((k) => {
    const a = table[k], b = next[k]
    return a && b && a.key === b.key && a.name === b.name && a.branch === b.branch && a.worktree === b.worktree
  })
  if (same) return
  table = next
  listeners.forEach((fn) => fn())
}

export function sessionProject(name?: string | null): SessionProject | undefined {
  return name ? table[name] : undefined
}

/**
 * 会话的「位置」——桌面列表里那一列（图纸 14-desktop-workspace/desktop-ia.html §一）。
 *
 * 优先给 worktree 分支：同名会话散在两个 worktree 上时，分支是唯一能分辨它们的东西。
 * 没有分支就给工作目录（只留末两段）。**与项目目录相同时返回空**：那一行左边的项目列
 * 已经说过一遍，再写一次是重复不是信息。
 */
export function sessionLocation(ann: any, cwd?: string, projectDir?: string):
  { branch?: string; path?: string; title?: string } {
  const branch = ann?.primary?.branch
  if (branch) return { branch, title: ann?.primary?.worktree || branch }
  const dir = cwd || ann?.home || ''
  if (!dir || dir === projectDir) return {}
  const parts = dir.split('/').filter(Boolean)
  return { path: (parts.length > 2 ? '…/' : '/') + parts.slice(-2).join('/'), title: dir }
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useSessionProject(name?: string | null): SessionProject | undefined {
  return useSyncExternalStore(subscribe, () => sessionProject(name), () => sessionProject(name))
}

/** 整张表——会话列表要按行取项目名，一个个 hook 取不现实。 */
export function useSessionProjects(): Record<string, SessionProject> {
  return useSyncExternalStore(subscribe, () => table, () => table)
}

/**
 * 从 `/projects` 与 `/sessions/annotations` 两条现成接口拼归属表。
 *
 * Git 按 repo 匹配，普通目录按已保存 home 的最长前缀匹配；top 只作旧节点兜底。
 */
export function buildSessionProjects(
  projects: { key: string; name: string; dir: string; git: boolean; top?: { name: string }[] | null }[],
  annotations: Record<string, any>,
  native: NativeSessionRecord[] = [],
): Record<string, SessionProject> {
  const byDir = new Map<string, { key: string; name: string; dir: string }>()
  for (const p of projects) if (p.git) byDir.set(p.dir, { key: p.key, name: p.name, dir: p.dir })

  const out: Record<string, SessionProject> = {}
  for (const [session, ann] of Object.entries(annotations || {})) {
    const primary = (ann as any)?.primary
    const hit = primary?.repo && byDir.get(primary.repo)
    // worktree 绝对路径就是任务的 key（22 设计 §3.2）：annotation 里本来就带着，多抄一个字段
    if (hit) out[session] = { ...hit, branch: primary.branch || undefined, worktree: primary.worktree || undefined }
    else if (ann?.home) {
      const home = String(ann.home).replace(/\/+$/, '')
      const project = projects.filter(p => !p.git && (home === p.dir.replace(/\/+$/, '') || home.startsWith(p.dir.replace(/\/+$/, '') + '/'))).sort((a, b) => b.dir.length - a.dir.length)[0]
      if (project) out[session] = { key: project.key, name: project.name, dir: project.dir }
    }
  }
  // 非 git 项目兜底：已经有归属的不覆盖（annotation 比 top 名单准）
  for (const p of projects) {
    if (p.git) continue
    for (const s of p.top || []) if (!out[s.name]) out[s.name] = { key: p.key, name: p.name, dir: p.dir }
  }
  for (const session of native) {
    const project = projects.find(project => project.key === session.projectId)
    if (project) out[nativeSessionName(session.nativeSessionId)] = { key: project.key, name: project.name, dir: project.dir, branch: session.branch, worktree: session.directory || project.dir }
  }
  return out
}
