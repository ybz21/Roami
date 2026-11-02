// 工具调用渲染的唯一入口：一张「工具名 → 怎么画」的注册表 + 一个路由。
//
// 架构参考 claudecodeui（siteboon，AGPL-3.0）的 tools/ 配置表：所有显示决策集中在一处，
// 不散在组件的 if/else 里；加一个工具＝在表里加一行。差别是这里 Claude 与 Codex 共用同一张表
// （Codex 的 shell / apply_patch / update_plan 只是另外几个键），两边的对话页就不会长成两个样。
//
// 密度原则：Read / Grep / Glob 这类「知道发生过就够」的只占一行；命令和改文件才值得展开。
// 成功的结果默认不展开甚至不显示，错误永远显示——一屏里最该被看见的是失败。
import { type ReactNode } from 'react'
import Markdown from '../markdown/Markdown'
import type { Block } from './types'
import { useI18n } from '../../i18n'
import { useLayout } from '../../layout'
import { useChatActions } from './actions'
import { taskList, type TaskIndex } from './tasks'
import {
  CommandRow, DiffPane, ErrorRow, FileListPane, OutputPane, PatchPane, ToolCard, ToolRow, TodoPane,
  shortPath, type Tone, type ToolStatus, type TodoItem,
} from './tool-parts'
import {
  BotIcon, ChecklistIcon, FlagIcon, GearIcon, GlobeIcon, ImageIcon, PencilIcon,
  PlugIcon, QuestionIcon, ReadIcon, SearchIcon, TerminalIcon,
} from '../../icons'
import { CodeBox, localizeSentinels, MONO } from './blocks'

type T = (key: string, vars?: Record<string, string | number>) => string

type Ctx = {
  name: string
  o: any               // 解析后的入参；解析不出来是 null
  raw: string          // 原始入参串（apply_patch 这类非 JSON 的直接用它）
  result?: Block
  status: ToolStatus
  t: T
  keep: number       // 路径保留多少字符（窄屏更短，见 ToolView 里的 useLayout）
  tasks: TaskIndex   // 整段转录归拢出的任务清单（TaskUpdate 只给 id，标题回这里查）
}

// ── 小工具函数 ──────────────────────────────────────────────────────────

const s = (v: any) => (v == null ? '' : String(v))
const clip = (v: string, n = 160) => (v.length > n ? v.slice(0, n) + '…' : v)

const resultText = (c: Ctx) => localizeSentinels(s(c.result?.text), c.t)

// Grep 的内容模式结果是 path:line:match —— 抠出行号，点开就能跳到那一行
const GREP_HIT = /^(.+?):(\d+):/

// 被拒绝 / 被中断和真报错该分开：前者是人的选择，不该染成红色故障。
// 判据必须咬住「人」这个主语——只匹配 denied / rejected 会把 `EACCES: permission denied`
// 这种货真价实的失败也判成「用户拒绝」，那是最不该弄错的一类。
const DENIED = /(user (?:doesn't|does not|didn't) want|user (?:rejected|declined|cancell?ed)|(?:rejected|declined|denied|cancell?ed) by (?:the )?user|request interrupted|interrupted by (?:the )?user|用户(?:拒绝|取消|中断|已取消))/i

export function toolStatus(result?: Block): ToolStatus {
  if (!result) return 'running'
  if (!result.isError) return 'ok'
  return DENIED.test(s(result.text)) ? 'denied' : 'error'
}

// 错误一律显示（成功的结果各工具自己决定给不给）
function withError(c: Ctx, node: ReactNode): ReactNode {
  if (!c.result?.isError) return node
  return <>{node}<ErrorRow text={resultText(c)} /></>
}

// Codex 的 shell 是 command:["bash","-lc","真正的命令"]，直接 String() 会拼成 "bash,-lc,…"。
export function extractCommand(o: any): string {
  if (!o) return ''
  const v = o.command ?? o.cmd ?? o.argv
  if (Array.isArray(v)) {
    // bash -lc / sh -c / zsh -lc：真正的命令在最后一个参数上，前面的壳没信息量
    const last = v[v.length - 1]
    if (v.length >= 3 && /^(ba|z|d|k)?sh$/.test(s(v[0])) && /^-[lic]+$/.test(s(v[1])) && typeof last === 'string') return last
    return v.map(s).join(' ')
  }
  return s(v)
}

// 后端把单块文本截到 6000 字（backend/api/claude.go 的 clip），heredoc 那类长命令
// 一截 JSON 就废了 → JSON.parse 失败 → 整行渲染成裸 `{"command":"cat > …`。
// 所以解析不出对象时再用正则从原文里把命令抠出来：截断的 JSON 也照样能读出前半截。
const CMD_IN_RAW = /"(?:command|cmd)"\s*:\s*"((?:[^"\\]|\\.)*)/
const JSON_ESC: Record<string, string> = { n: '\n', t: '\t', r: '\r', '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f' }

export function commandFromRaw(raw: string): string {
  const m = CMD_IN_RAW.exec(raw)
  if (!m) return ''
  return m[1].replace(/\\(u[0-9a-fA-F]{4}|.)/g, (_, e: string) =>
    e[0] === 'u' ? String.fromCharCode(parseInt(e.slice(1), 16)) : (JSON_ESC[e] ?? e))
}

// 结果文本看着像「一行一个路径」就当文件列表画；path:line: 形式的顺带带上行号
export type Hit = { path: string; line?: number; text: string }

function asFileList(text: string): Hit[] | null {
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  if (lines.length < 2 || lines.length > 400) return null
  const hits: Hit[] = []
  for (const l of lines) {
    const m = GREP_HIT.exec(l)
    if (m && /^(\/|\.{1,2}\/|[\w.@-]+[/.])/.test(m[1])) { hits.push({ path: m[1], line: Number(m[2]), text: l }); continue }
    if (/^(\/|\.{1,2}\/|[\w.@-]+\/)/.test(l) && !/\s{2,}/.test(l)) { hits.push({ path: l, text: l }); continue }
  }
  return hits.length >= lines.length - 1 ? hits : null
}

function todosOf(o: any): TodoItem[] {
  const arr = Array.isArray(o?.todos) ? o.todos : Array.isArray(o?.plan) ? o.plan : []
  return arr
    .map((x: any) => ({ content: s(x?.content ?? x?.step ?? x?.task ?? x), status: s(x?.status || 'pending') }))
    .filter((x: TodoItem) => x.content)
}

// ── 注册表 ──────────────────────────────────────────────────────────────

type Renderer = (c: Ctx) => ReactNode

// 命令类：Claude 的 Bash、Codex 的 shell / exec_command 都走这里。
const command: Renderer = (c) => (
  <CommandRow
    command={extractCommand(c.o) || commandFromRaw(c.raw) || clip(c.raw, 400)}
    description={s(c.o?.description) || undefined}
    output={resultText(c)}
    isError={c.result?.isError}
    status={c.status}
  />
)

const read: Renderer = (c) => {
  const path = s(c.o?.file_path ?? c.o?.path ?? c.o?.notebook_path)
  const line = Number(c.o?.offset) || undefined
  return withError(c, (
    <ToolRow icon={<ReadIcon />} label={c.name} tone="accent" status={c.status}
      value={shortPath(path, c.keep)} path={path} line={line}
      secondary={line ? `+${line}` : undefined} copy={path} />
  ))
}

// 查找：调用只占一行，命中的文件折在结果里，默认收起。
const search: Renderer = (c) => {
  const files = c.result && !c.result.isError ? asFileList(resultText(c)) : null
  const head = (
    <ToolRow icon={<SearchIcon />} label={c.name} tone="accent" status={c.status}
      value={s(c.o?.pattern ?? c.o?.query)}
      secondary={c.o?.path ? c.t('chat.searchIn', { path: shortPath(s(c.o.path), Math.round(c.keep * 0.6)) }) : undefined}
      copy={s(c.o?.pattern ?? c.o?.query)} />
  )
  if (c.result?.isError) return withError(c, head)
  if (!c.result) return head
  return (
    <>
      {head}
      <div style={{ paddingLeft: 'var(--sp-3)' }}>
        {files
          ? <ToolCard label={c.t('chat.filesFound', { count: files.length })} tone="neutral"><FileListPane hits={files} /></ToolCard>
          : <OutputPane text={resultText(c)} />}
      </div>
    </>
  )
}

// 改文件的入参形状：Claude 的 Edit/Write、Codex 的同名工具都归到这三个字段上。
// 运行组的组头要算「这一串一共 +N −M」，也得按同一套抠——所以抠法只写一份（设计 16 §4）。
export type EditParts = { path: string; oldText: string; newText: string; isNew: boolean }

export function editParts(name: string, o: any): EditParts | null {
  if (!o) return null
  const path = s(o.file_path ?? o.path ?? o.notebook_path)
  const isNew = name === 'Write' || name === 'write' || name === 'create_file'
  const oldText = isNew ? '' : s(o.old_string ?? o.oldString ?? o.old_str ?? o.oldText)
  const newText = isNew ? s(o.content) : s(o.new_string ?? o.newString ?? o.new_str ?? o.new_source ?? o.newText)
  if (!path && !oldText && !newText) return null
  return { path, oldText, newText, isNew }
}

// 改文件：新旧文本走 LCS 对齐，只列真正变动的行。
const edit: Renderer = (c) => {
  const p = editParts(c.name, c.o)
  const path = p?.path || ''
  const isNew = !!p?.isNew
  const oldText = p?.oldText || ''
  const newText = p?.newText || ''
  return withError(c, (
    <ToolCard icon={<PencilIcon />} label={c.name} title={shortPath(path, c.keep)} path={path} tone="warn" status={c.status}>
      <DiffPane oldText={oldText} newText={newText} path={path}
        badge={isNew ? c.t('chat.diffNew') : c.t('chat.diffEdit')} badgeTone={isNew ? 'ok' : 'warn'} />
    </ToolCard>
  ))
}

const multiEdit: Renderer = (c) => {
  const path = s(c.o?.file_path)
  const edits: any[] = Array.isArray(c.o?.edits) ? c.o.edits : []
  return withError(c, (
    <ToolCard icon={<PencilIcon />} label={c.name} title={`${shortPath(path, c.keep)} · ${edits.length}`} path={path} tone="warn" status={c.status}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
        {edits.map((e, i) => (
          <DiffPane key={i} oldText={s(e?.old_string)} newText={s(e?.new_string)} path={path}
            badge={c.t('chat.diffEdit')} badgeTone="warn" />
        ))}
      </div>
    </ToolCard>
  ))
}

const patch: Renderer = (c) => {
  // custom_tool_call 的 input 就是补丁原文；function_call 则包了一层 {"input": "..."}
  const text = typeof c.o?.input === 'string' ? c.o.input : typeof c.o === 'string' ? c.o : c.raw
  return withError(c, (
    <ToolCard icon={<PencilIcon />} label={c.name} tone="warn" status={c.status} defaultOpen>
      <PatchPane text={text} />
    </ToolCard>
  ))
}

const todo: Renderer = (c) => {
  const items = todosOf(c.o)
  const doing = items.find((i) => i.status === 'in_progress')
  const done = items.filter((i) => i.status === 'completed').length
  return withError(c, (
    <ToolCard icon={<ChecklistIcon />} label={c.name} tone="accent" status={c.status}
      title={doing ? doing.content : c.t('chat.todoProgress', { done, total: items.length })}>
      <TodoPane items={items} />
      {c.o?.explanation && <div style={{ marginTop: 'var(--sp-2)', color: 'var(--text-dim)', fontSize: 'var(--fs-meta)' }}>{s(c.o.explanation)}</div>}
    </ToolCard>
  ))
}

const plan: Renderer = (c) => withError(c, (
  <ToolCard icon={<FlagIcon />} label={c.t('chat.plan')} tone="accent" status={c.status} defaultOpen>
    <Markdown accent="var(--accent)">{s(c.o?.plan).replace(/\\n/g, '\n')}</Markdown>
  </ToolCard>
))

// 子代理：调用展开是提示词，结果展开是它的汇报——两段都是正文，按 Markdown 画。
const subagent: Renderer = (c) => withError(c, (
  <ToolCard icon={<BotIcon size={13} />} label={c.t('chat.subagent')} tone="accent" status={c.status}
    title={s(c.o?.description || c.o?.subagent_type)}>
    {c.o?.subagent_type && <div style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)', fontFamily: MONO, marginBottom: 'var(--sp-1)' }}>{s(c.o.subagent_type)}</div>}
    <Markdown accent="var(--accent)">{s(c.o?.prompt)}</Markdown>
    {c.result && !c.result.isError && <OutputPane text={resultText(c)} label={c.t('chat.subagentResult')} />}
  </ToolCard>
))

const web: Renderer = (c) => {
  const head = (
    <ToolRow icon={<GlobeIcon />} label={c.name} tone="accent" status={c.status}
      value={s(c.o?.url ?? c.o?.query)} copy={s(c.o?.url ?? c.o?.query)} />
  )
  if (c.result?.isError) return withError(c, head)
  return <>{head}{c.result && <div style={{ paddingLeft: 'var(--sp-3)' }}><OutputPane text={resultText(c)} /></div>}</>
}

// 选择框：把问题、候选项、以及（如果已作答）选中的答案画出来。
const ask: Renderer = (c) => {
  const qs: any[] = Array.isArray(c.o?.questions) ? c.o.questions : []
  const answers = c.o?.answers && typeof c.o.answers === 'object' ? c.o.answers : {}
  const answered = Object.keys(answers).length > 0
  return withError(c, (
    <ToolCard icon={<QuestionIcon size={13} />} label={c.t('chat.question')} tone="accent" status={c.status} defaultOpen
      title={qs.length === 1 ? s(qs[0]?.header || qs[0]?.question) : c.t('chat.questionCount', { count: qs.length })}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
        {qs.map((q, i) => {
          const picked = s(answers[s(q?.question)])
          return (
            <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-xs)', background: 'var(--bg-base)', padding: 'var(--sp-2)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)', fontSize: 'var(--fs-meta)' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                {q?.header && <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}>{s(q.header)}</span>}
                <span style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{s(q?.question)}</span>
                {q?.multiSelect === true && <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}>{c.t('chat.askMultiSelect')}</span>}
              </div>
              {(Array.isArray(q?.options) ? q.options : []).map((op: any, j: number) => {
                const label = s(op?.label)
                const chosen = answered && picked === label
                return (
                  <div key={j} style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingLeft: 'var(--sp-2)', borderLeft: `2px solid ${chosen ? 'var(--accent)' : 'transparent'}` }}>
                    <span style={{ color: chosen ? 'var(--accent)' : 'var(--text-bright)', fontWeight: 600 }}>{label}</span>
                    {op?.description && <span style={{ color: 'var(--text-dim)' }}>{s(op.description)}</span>}
                    {op?.preview && <CodeBox text={s(op.preview)} max={220} />}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </ToolCard>
  ))
}

// ── 任务面板（TaskCreate / TaskUpdate / TaskList / TaskGet）────────────────
// TaskUpdate 的入参只有 {taskId, status}，光看这一次调用不知道 #4 是哪件事；
// 标题在更早那次 TaskCreate 的结果文本里。所以这里回 ctx.tasks 查（见 chat/tasks.ts）。

const TASK_TONE: Record<string, Tone> = { completed: 'ok', in_progress: 'warn', pending: 'neutral', deleted: 'neutral' }

const taskCreate: Renderer = (c) => {
  const subject = s(c.o?.subject)
  const id = /task\s*#(\d+)/i.exec(resultText(c))?.[1]
  return withError(c, (
    <ToolRow icon={<ChecklistIcon />} label={c.t('chat.taskNew')} tone="accent" status={c.status}
      value={subject} secondary={id ? `#${id}` : undefined} copy={subject} />
  ))
}

const taskUpdate: Renderer = (c) => {
  const id = s(c.o?.taskId)
  const known = id ? c.tasks[id] : undefined
  const status = s(c.o?.status) || known?.status || ''
  const subject = s(c.o?.subject) || known?.subject || c.t('chat.taskUnknown', { id })
  return withError(c, (
    <ToolRow icon={<ChecklistIcon />} label={id ? `#${id}` : c.t('chat.taskUpdate')}
      tone={TASK_TONE[status] || 'accent'} status={c.status}
      value={subject} secondary={status ? c.t(`chat.taskStatus.${status}`) : undefined} copy={subject} />
  ))
}

// 面板：整段转录归拢出的当前任务清单，不是这一次调用的入参
const taskPanel: Renderer = (c) => {
  const items = taskList(c.tasks).map((t) => ({ id: t.id, content: t.subject, status: t.status }))
  const done = items.filter((i) => i.status === 'completed').length
  const doing = items.find((i) => i.status === 'in_progress')
  if (!items.length) return withError(c, <ToolRow icon={<ChecklistIcon />} label={c.name} tone="accent" status={c.status} />)
  return withError(c, (
    <ToolCard icon={<ChecklistIcon />} label={c.t('chat.taskPanel')} tone="accent" status={c.status} defaultOpen
      title={doing ? doing.content : c.t('chat.todoProgress', { done, total: items.length })}>
      <TodoPane items={items} />
    </ToolCard>
  ))
}

// 兜底：参数用 JSON 折起来，结果收起来，错误照常红条。
const fallback: Renderer = (c) => {
  const pretty = c.o ? JSON.stringify(c.o, null, 2) : c.raw
  const key = c.o && ['command', 'file_path', 'path', 'pattern', 'query', 'prompt', 'description', 'name'].find((k) => c.o[k])
  return withError(c, (
    <ToolCard icon={<GearIcon />} label={c.name} tone="neutral" status={c.status}
      title={key ? clip(s(c.o[key])) : undefined}>
      {pretty && <CodeBox text={pretty} />}
      {c.result && !c.result.isError && <OutputPane text={resultText(c)} />}
    </ToolCard>
  ))
}

const oneLine = (icon: ReactNode, tone: Tone, pick: string[]): Renderer => (c) => {
  const key = c.o && pick.find((k) => c.o[k] != null)
  const value = key ? clip(s(c.o[key])) : ''
  return withError(c, <ToolRow icon={icon} label={c.name} tone={tone} status={c.status} value={value} copy={value || undefined} />)
}

const TOOLS: Record<string, Renderer> = {
  // Claude Code
  Bash: command,
  BashOutput: oneLine(<TerminalIcon />, 'ok', ['bash_id', 'shell_id']),
  KillShell: oneLine(<TerminalIcon />, 'ok', ['shell_id']),
  Read: read,
  NotebookEdit: edit,
  Write: edit,
  Edit: edit,
  MultiEdit: multiEdit,
  Glob: search,
  Grep: search,
  Task: subagent,
  Agent: subagent,
  TodoWrite: todo,
  WebFetch: web,
  WebSearch: web,
  AskUserQuestion: ask,
  ExitPlanMode: plan,
  exit_plan_mode: plan,
  SlashCommand: oneLine(<TerminalIcon />, 'accent', ['command']),
  TaskCreate: taskCreate,
  TaskUpdate: taskUpdate,
  TaskList: taskPanel,
  TaskGet: taskPanel,
  TaskOutput: oneLine(<ChecklistIcon />, 'accent', ['taskId', 'id']),
  TaskStop: oneLine(<ChecklistIcon />, 'accent', ['taskId', 'id']),
  Skill: oneLine(<PlugIcon />, 'accent', ['skill', 'command', 'name']),

  // Codex
  shell: command,
  local_shell: command,
  exec_command: command,
  container_exec: command,
  write_stdin: oneLine(<TerminalIcon />, 'ok', ['chars', 'text']),
  apply_patch: patch,
  update_plan: todo,
  read_file: read,
  view_image: oneLine(<ImageIcon />, 'accent', ['path', 'url']),
  web_search: web,
  edit,
  write: edit,
  read,
  grep: search,
  glob: search,
  question: ask,
  execute: command,
  webfetch: web,
  subagent,
}

// ── 路由 ────────────────────────────────────────────────────────────────

function parseInput(input?: string): { o: any; raw: string } {
  const raw = s(input)
  if (!raw) return { o: null, raw }
  try { return { o: JSON.parse(raw), raw } } catch { return { o: null, raw } }
}

// mcp__server__tool（Claude）/ mcp:server.tool（Codex）→ 统一显示成 server · tool
function mcpParts(name: string): { server: string; tool: string } | null {
  if (name.startsWith('mcp__')) {
    const [, server, ...rest] = name.split('__')
    return { server: server || name, tool: rest.join('__') }
  }
  if (name.startsWith('mcp:')) {
    const rest = name.slice(4)
    const dot = rest.indexOf('.')
    return dot < 0 ? { server: rest, tool: '' } : { server: rest.slice(0, dot), tool: rest.slice(dot + 1) }
  }
  return null
}

export function ToolView({ block, result }: { block: Block; result?: Block }) {
  const { t } = useI18n()
  // 断点只走 useLayout()（设计系统硬规则），不读 innerWidth、不自己 matchMedia。
  // 窄屏路径留 22 字符≈只剩「上级目录/文件名」，够认人又不把整行挤没。
  const { phone } = useLayout()
  const { tasks } = useChatActions()
  const name = s(block.name) || t('chat.tool')
  const { o, raw } = parseInput(block.input)
  const c: Ctx = { name, o, raw, result, status: toolStatus(result), t, keep: phone ? 28 : 44, tasks: tasks || {} }

  const mcp = mcpParts(name)
  if (mcp) {
    return withError(c, (
      <ToolCard icon={<PlugIcon />} label={`MCP · ${mcp.server}`} title={mcp.tool} tone="neutral" status={c.status}>
        {(o || raw) && <CodeBox text={o ? JSON.stringify(o, null, 2) : raw} />}
        {result && !result.isError && <OutputPane text={resultText(c)} />}
      </ToolCard>
    ))
  }

  const render = TOOLS[name] || fallback
  return <>{render(c)}</>
}

// 独立出现的 tool_result（没配上 tool_use 时的兜底）
export function LooseResult({ block }: { block: Block }) {
  const { t } = useI18n()
  if (block.isError) return <ErrorRow text={s(block.text)} />
  return <OutputPane text={s(block.text)} label={t('common.output')} />
}
