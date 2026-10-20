import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { buildSessionProjects, setSessionProjects } from '../components/sessions/session-project'
import { loadTreeSrc, saveTreeSrc, type TreeSrc } from '../components/shell/task-tree-snapshot'

export function useProjectDirectory(hasSider: boolean, gitDir: string) {
  const [treeSrc, setTreeSrc] = useState<TreeSrc>(() => {
    const s = loadTreeSrc()
    if (s.placement && Object.keys(s.placement).length) setSessionProjects(s.placement)
    return s
  })
  const treeSrcRef = useRef(treeSrc)
  treeSrcRef.current = treeSrc
  const treeReload = useRef<(() => void) | null>(null)
  const [unfinished, setUnfinished] = useState(0)
  const [swarmCount, setSwarmCount] = useState(0)
  const [git, setGit] = useState<{ branch: string; ahead: number; behind: number; files: number; state: string; conflicts: number } | null>(null)
  const gitDirRef = useRef(gitDir)
  gitDirRef.current = gitDir
  const loadGit = async () => {
    if (document.hidden) return
    const dir = gitDirRef.current
    if (!dir) { setGit(null); return }
    try {
      const d = (await api('GET', `/git/status?dir=${encodeURIComponent(dir)}`))?.data
      const len = (v: unknown) => (Array.isArray(v) ? v.length : Number(v) || 0)
      setGit(d?.repo ? {
        branch: d.branch || '', ahead: d.ahead || 0, behind: d.behind || 0,
        files: len(d.files), state: d.state || '', conflicts: len(d.conflicts),
      } : null)
    } catch { /* 轮询失败保持上一轮，不清空 */ }
  }
  useEffect(() => { void loadGit() }, [gitDir])
  useEffect(() => {
    let stop = false
    const load = async () => {
      if (stop || document.hidden) return
      try {
        const prP = api('GET', '/projects')
        const anP = api('GET', '/sessions/annotations').catch(() => null)
        const swP = api('GET', '/swarms').catch(() => null)
        void anP.then((an) => {
          if (stop || !an?.data) return
          const known = treeSrcRef.current.projects
          if (known.length) setSessionProjects(buildSessionProjects(known, an.data))
        })
        const [pr, an, sw] = await Promise.all([prP, anP, swP])
        if (stop) return
        const projects = pr?.data?.projects || []
        setUnfinished(projects.reduce((n: number, p: any) => n + (p.unfinished || 0), 0))
        const placement = buildSessionProjects(projects, an?.data || {})
        setSessionProjects(placement)
        const swarms = Array.isArray(sw) ? sw : sw?.data || []
        setSwarmCount(swarms.filter((x: any) => x?.status && x.status !== 'archived').length)
        void loadGit()
        setTreeSrc((cur) => ({ ...cur, projects }))
        // Worktree scans are expensive: serialize them and keep the slower cadence.
        if (hasSider && Date.now() - wtAt > 60000) {
          wtAt = Date.now()
          const worktrees: Record<string, any[]> = {}
          for (const p of projects.filter((x: any) => x.git)) {
            if (stop) return
            try { worktrees[p.key] = (await api('GET', `/git/worktrees?dir=${encodeURIComponent(p.dir)}`))?.data || [] }
            catch { worktrees[p.key] = [] }
            if (stop) return
            setTreeSrc((cur) => ({ projects, worktrees: { ...cur.worktrees, [p.key]: worktrees[p.key] } }))
          }
          if (stop) return
          setTreeSrc({ projects, worktrees })
          saveTreeSrc({ projects, worktrees, placement })
        }
      } catch { /* 轮询失败就保持上一轮的值，不清空 */ }
    }
    let wtAt = 0
    treeReload.current = () => { wtAt = 0; void load() }
    load()
    const i = setInterval(load, 15000)
    return () => { stop = true; clearInterval(i); treeReload.current = null }
  }, [hasSider])

  return { treeSrc, setTreeSrc, treeSrcRef, unfinished, swarmCount, git, refresh: () => treeReload.current?.() }
}
export type ProjectDirectory = ReturnType<typeof useProjectDirectory>
