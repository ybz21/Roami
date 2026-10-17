// 轮询会话转录(JSONL)，按**字节偏移**增量拉取，自动归一为 Msg[]。
//
// offset 在这一层是**不透明游标**：只原样回传、只比大小（变小=文件被换过，重来）。
// 后端 2026-08-30 把它从行号改成字节偏移，这里一行没动——行号逼着后端每次轮询
// 从第 1 行重数一遍，一次请求就分配一整个文件（见 backend/api/transcript-read.go）。
// Claude 与 Codex 共用，只是 path 不同(transcript / codex-transcript)。
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { Block, Msg } from './types'
import type { RawStatus } from './status'

/** 首屏只取最近这么多条。整卷搬过来的代价见 backend/api/transcript-window.go。 */
export const FIRST_PAGE = 200

export function useTranscript(name: string, file: string | undefined, path: string, interval = 1500) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [err, setErr] = useState('')
  // 后端这轮定位到的转录文件：undefined=第一轮还没回来，''=后端也没找到（agent 一句没说）。
  // 空状态那行字靠它区分「加载中」和「还没有对话」，光看调用方传没传 file 会把两者混成一句。
  const [resolvedFile, setResolvedFile] = useState<string | undefined>(undefined)
  // 状态是「上次成交价」：这一轮没扫到新行后端就回空，保留上次的值。
  // 会话闲着不动百分比就不动——那是对的，没发生新对话上下文确实没变。
  const [status, setStatus] = useState<RawStatus>({})
  const [refreshKey, setRefreshKey] = useState(0)
  // 还有更早的没取：后端截过头才为真。前端不再自己算「隐藏了几条」——它手里根本没有全量。
  const [hasEarlier, setHasEarlier] = useState(false)
  const [serverPending, setServerPending] = useState<boolean | undefined>(undefined)
  const [tail, setTail] = useState(FIRST_PAGE)
  const refresh = useCallback(() => setRefreshKey((n) => n + 1), [])
  // 间隔走 ref：后台会话把间隔放宽时不能重启 effect——重启等于清空重拉整个首屏
  const intervalRef = useRef(interval)
  intervalRef.current = interval
  // 加载更早：把首屏窗口放大一档重取。往回翻是低频动作，值得用一次全量重取换实现上的简单。
  const loadEarlier = useCallback(() => setTail((n) => n + 400), [])
  useEffect(() => {
    let stop = false
    let offset = 0
    let f = file
    let lastFile = file || ''
    setMsgs([]); setErr(''); setStatus({}); setResolvedFile(undefined); setServerPending(undefined)
    const poll = async () => {
      try {
        // boff=1：告诉后端这个 offset 是字节偏移（升级前的页面不会带，后端据此重新锚定）
        const q = new URLSearchParams({ offset: String(offset), boff: '1' })
        // 只有首屏带 tail：增量轮询要的是「新行」，一条都不能丢。
        if (offset === 0) q.set('tail', String(tail))
        if (f) q.set('file', f)
        const r = await api('GET', `/sessions/${encodeURIComponent(name)}/${path}?${q.toString()}`)
        const d = r.data
        if (stop) return
        setErr('') // 这轮通了就把上一轮的报错擦掉，否则一次抖动的红字会一直挂到重开面板
        if (typeof d.file === 'string') setResolvedFile(d.file)
        if (d.file && d.file !== lastFile) {
          f = d.file
          lastFile = d.file
          offset = 0
          setMsgs([])
          return
        }
        if (typeof d.nextOffset === 'number' && d.nextOffset < offset) {
          offset = 0
          setMsgs([])
          return
        }
        if (d.status || typeof d.quota === 'number') {
          setStatus((prev) => mergeStatus(prev, d.status, d.quota))
        }
        if (typeof d.truncated === 'boolean') setHasEarlier(d.truncated)
        if (typeof d.pending === 'boolean') setServerPending(d.pending)
        if (d.messages?.length) {
          setMsgs((m) => {
            if (path !== 'opencode-transcript') return [...m, ...d.messages]
            const ids = new Map<string, number>()
            const merged = [...m]
            let changed = false
            merged.forEach((item, i) => { if (item.id) ids.set(item.id, i) })
            for (const item of d.messages as Msg[]) {
              const at = item.id ? ids.get(item.id) : undefined
              if (at === undefined) { if (item.id) ids.set(item.id, merged.length); merged.push(item); changed = true }
              else if (JSON.stringify(merged[at]) !== JSON.stringify(item)) { merged[at] = item; changed = true }
            }
            return changed ? merged : m
          })
          offset = d.nextOffset
        }
        else if (typeof d.nextOffset === 'number') offset = d.nextOffset
      } catch (e: any) { if (!stop) setErr(e.message) }
    }
    let t: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      await poll()
      if (!stop) t = setTimeout(tick, intervalRef.current)
    }
    void tick()
    return () => { stop = true; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, file, path, refreshKey, tail])
  return { msgs, err, refresh, status, hasEarlier, loadEarlier, resolvedFile, serverPending }
}

// 只有非空字段才覆盖：后端每轮只回它这次扫到的东西，缺的字段不该把已知值抹掉。
// 没有任何字段变化时返回 prev 本身：React 靠引用相等跳过整棵对话树的重渲染，
// 而这个函数每 1.5s 被调一次——每次都造新对象等于每 1.5s 白重渲染一次几百条消息。
function mergeStatus(prev: RawStatus, next: RawStatus | undefined, quota?: number): RawStatus {
  const out: RawStatus = { ...prev }
  let changed = false
  for (const [k, v] of Object.entries(next || {})) {
    if (v !== '' && v !== 0 && v != null && (prev as any)[k] !== v) { (out as any)[k] = v; changed = true }
  }
  if (typeof quota === 'number' && quota > 0 && prev.quota !== quota) { out.quota = quota; changed = true }
  return changed ? out : prev
}

// 把 tool_result 按 tool_use_id 挂回对应 tool_use，并从消息流里隐去已收纳的独立结果气泡。
// Claude、Codex 共用（两端后端都已透出 id / toolUseId）。
export function pairToolResults(msgs: Msg[]): { results: Record<string, Block>; view: Msg[] } {
  const results: Record<string, Block> = {}
  for (const m of msgs) for (const b of m.blocks) if (b.kind === 'tool_result' && b.toolUseId) results[b.toolUseId] = b
  const consumed = new Set<string>()
  for (const m of msgs) for (const b of m.blocks) if (b.kind === 'tool_use' && b.id && results[b.id]) consumed.add(b.id)
  const view = msgs.map((m) => {
    const blocks = m.blocks.filter((b) => !(b.kind === 'tool_result' && b.toolUseId && consumed.has(b.toolUseId)))
    return { ...m, blocks }
  }).filter((m) => m.blocks.length > 0)
  return { results, view }
}

// 「正在生成」判定：最后一轮还没轮到 assistant 收尾(用户刚发 / 工具刚返回 / 正调用工具)。
export function isPending(view: Msg[]): boolean {
  const last = view[view.length - 1]
  if (!last) return false
  if (last.role === 'user' || last.role === 'tool') return true
  if (last.role === 'assistant') return last.blocks[last.blocks.length - 1]?.kind === 'tool_use'
  return false
}
