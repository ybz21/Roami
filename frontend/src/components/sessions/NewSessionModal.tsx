// ── 新建会话（prompt-first 派活）/ 派生子会话 ──
// parent 非空 = 派生模式：同一张表单（目录默认父 cwd 可改、三选一、命名约定 prompt 全同款），
// 仅提交路由不同（fork / fork-worktree，meta 记父子关系）。两处不再各维护一份表单。
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { DirPicker, pushRecentDir, recentDirs } from './DirPicker'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'
import { sessionLabel } from './session-label'
import { shellQuote as shq } from '../../shell-quote'
import { AutoComplete, Button, Checkbox, Input, Modal, Radio, Segmented, Select, Space, Tag, Tooltip, App as AntApp } from 'antd'
import { BranchIcon } from '../git/parts'
import type { LocalBranch } from '../git/local-branches'
import { pickBranch, pickWt, pickedBranch, pickedWtPath } from './ExistingWorkPicker'
import { relTime } from '../../time-format'
import { kickoffBrief, type BriefWhere } from './kickoff-brief'

// 由 prompt 首句推会话名：派活时用户只写了要干什么，名字不该再问一遍。
// worktree 分支默认名：会话名 slug（小写、非字母数字转 -）
// prompt 派生任务名：取首行、去引号标点、截 24 字、空白转 -；中文原样保留（tmux 会话名支持中文）。
/**
 * 从需求派生一个**占位**名字。真名字由 agent 开工后 `ttmux rename`（见 session.wt.brief*）。
 *
 * 三步：剥掉开头的招呼与人称（「你去/帮我/请…」——它们只说了「有人在派活」，
 * 没说这是什么活）、在首个标点处断句、按长度截断但不切在拉丁词中间。
 * 最后那条是这次修的：16 个字硬切，「你去英伟达的 DGX Spark 论坛…」被切成
 * 「你去英伟达的-DGX-Spark」，半个词吊在名字末尾。
 */
export function taskNameFromPrompt(p: string, limit = 16): string {
  const first = (p.trim().split(/\n/)[0] || '').replace(/["'`«»""'']/g, '').trim()
  const lead = first.replace(/^(?:请|麻烦|帮我|帮忙|你去|你来|你先|你把|你|我要|我想|我们|给我|来|去)+\s*/, '')
  const seg = (lead || first).split(/[，。,.!！？?;；:：]/)[0]
  const base = seg.length >= 4 ? seg : (lead || first)
  let cut = base.slice(0, limit)
  if (base.length > limit) {
    // 切点落在拉丁词/数字中间 → 退回上一个边界，别留半个词（Spar…、5.…）
    if (/[A-Za-z0-9.]/.test(base[limit - 1]) && /[A-Za-z0-9.]/.test(base[limit])) {
      const back = cut.replace(/[A-Za-z0-9.]+$/, '')
      if (back.trim().length >= 4) cut = back
    }
    // 末尾剩一个孤零零的汉字，多半是被切成两半的词（「论坛」→「论」）：丢掉
    const lone = cut.replace(/[\s]([\u4e00-\u9fff])$/, '')
    if (lone.trim().length >= 4) cut = lone
  }
  return cut.trim().replace(/[-，。,.!！？?;；:：\s]+$/g, '').replace(/\s+/g, '-')
}

export function NewSessionModal({ open, parent, onClose, onDone }: { open: boolean; parent?: string | null; onClose: () => void; onDone: (name: string) => void }) {
  const [prompt, setPrompt] = useState('')
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [dir, setDir] = useState('')
  const [pick, setPick] = useState(false)
  const [agent, setAgent] = useState<'none' | 'claude' | 'codex'>('claude')
  // 工作区三选一（W1 交互修订）：主仓库 / 新建隔离 worktree / 进入已有 worktree
  // 工作区两选一（22 设计 D4）：新建 worktree / 已有 worktree；非 git 目录才退回「就在这个目录」
  const [wtMode, setWtMode] = useState<'repo' | 'new' | 'existing'>('new')
  const [existingWts, setExistingWts] = useState<any[]>([])
  const [mainPath, setMainPath] = useState('')
  // 「已有」选中值：'wt:<路径>'（进这个工作区）/ 'br:<分支>'（为这条分支开一个工作区）
  const [existing, setExisting] = useState('')
  const [autoReview, setAutoReview] = useState(false)
  const [isGitRepo, setIsGitRepo] = useState(false)
  const [creating, setCreating] = useState(false)
  // worktree 展开态（W1）：只选「基于」。分支不提前指定——后端按会话名占位，
  // Agent 开工后按任务 git branch -m 语义化（交互修订 4：先建会话再建 worktree）。
  // base 选中值：本地分支存裸名；远端分支存 remote:<remote>:<branch> 编码
  // （冒号在 git ref 名里非法，编码无歧义），提交前拆回 {base, remote}
  const [base, setBase] = useState('')
  const [branches, setBranches] = useState<LocalBranch[]>([])
  const [remoteBranches, setRemoteBranches] = useState<{ remote: string; name: string }[]>([])
  const [defBranch, setDefBranch] = useState('')
  const { message } = AntApp.useApp()
  const { t } = useI18n()
  const [prefs] = usePreferences()
  useEffect(() => {
    if (!open) return
    setPrompt(''); setName(''); setNameTouched(false); setDir(''); setAgent('claude'); setWtMode('new'); setAutoReview(false); setIsGitRepo(false)
    setBase(''); setBranches([]); setRemoteBranches([]); setDefBranch(''); setExistingWts([]); setMainPath(''); setExisting('')
    // 派生模式：目录默认父会话 cwd（可改成任意目录，与新建一致）
    if (parent) {
      let cancelled = false
      api('GET', `/sessions/${encodeURIComponent(parent)}/cwd`)
        .then((r) => { if (!cancelled) setDir(r?.data?.dir || '') }).catch(() => {})
      return () => { cancelled = true }
    }
  }, [open, parent])
  useEffect(() => {
    const d = dir.trim()
    if (!d) { setIsGitRepo(false); return }
    let cancelled = false
    api('GET', `/git/is-repo?path=${encodeURIComponent(d)}`).then((r) => {
      if (!cancelled) setIsGitRepo(!!r?.data?.repo)
    }).catch(() => { if (!cancelled) setIsGitRepo(false) })
    return () => { cancelled = true }
  }, [dir])
  // 目录是 git 仓库时拉已有 worktree（三选一的「已有」选项 + 计数）
  useEffect(() => {
    if (!isGitRepo || !dir.trim()) { setExistingWts([]); setExisting(''); setWtMode('repo'); return }
    // 目录换成 git 仓库后要把 'repo' 抬回 'new'：Segmented 早就把「新建 worktree」画成选中了
    // （repo 档在 git 仓库下根本不渲染），状态却还停在 repo，提交时于是不建 worktree——
    // 界面说的和真发生的不是一回事
    setWtMode((m) => (m === 'repo' ? 'new' : m))
    let cancelled = false
    api('GET', `/git/worktrees?dir=${encodeURIComponent(dir.trim())}`).then((r) => {
      if (cancelled) return
      const all = Array.isArray(r?.data) ? r.data : []
      const wts = all.filter((w: any) => !w.isMain && !w.prunable)
      setExistingWts(wts)
      setMainPath(all.find((w: any) => w.isMain)?.path || '')
      setExisting((prev) => (prev && wts.some((w: any) => w.path === pickedWtPath(prev)) ? prev : (wts[0] ? pickWt(wts[0].path) : '')))
    }).catch(() => { if (!cancelled) setExistingWts([]) })
    return () => { cancelled = true }
  }, [isGitRepo, dir])
  // 分支清单喂两处：「新建」的「基于」起点，和「已有」里那些还没有工作区的分支
  useEffect(() => {
    if (!isGitRepo || !dir.trim()) { setBranches([]); return }
    let cancelled = false
    api('GET', `/git/branches?dir=${encodeURIComponent(dir.trim())}`).then((r) => {
      if (cancelled) return
      const bs: LocalBranch[] = r?.data?.branches || []
      const def: string = r?.data?.default || ''
      const rs: { remote: string; name: string }[] = r?.data?.remotes || []
      setBranches(bs); setDefBranch(def); setRemoteBranches(rs)
      setBase((prev) => (prev && (bs.some((b) => b.name === prev) || rs.some((x) => `remote:${x.remote}:${x.name}` === prev)) ? prev : def))
    }).catch(() => {})
    return () => { cancelled = true }
  }, [isGitRepo, dir])
  // 可收养的分支：没被任何工作区检出的那些（被 linked worktree 占的已在上一组里）
  const freeBranches = branches.filter((b) => !b.worktree)
  const existingCount = existingWts.length + freeBranches.length
  // 单子里还多列一条主仓库检出的分支（置灰），免得搜不到时以为是漏了
  const pickable = branches.filter((b) => !b.worktree || b.worktree === mainPath)
  const ok = async () => {
    // prompt-first：名字可全派生；prompt 与名字都空才拦
    let finalName = name.trim()
    if (!finalName) {
      if (!prompt.trim()) return message.error(t('session.promptOrNameRequired'))
      finalName = taskNameFromPrompt(prompt)
    }
    if (!finalName) {
      const d = new Date()
      finalName = 'task-' + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0') + '-' + String(d.getHours()).padStart(2, '0') + String(d.getMinutes()).padStart(2, '0')
    }
    try {
      setCreating(true)
      let sessionDir = dir.trim()
      let actual: string
      let wtBranch = ''   // 新建 worktree 时后端给的占位分支
      let wtBase = ''     // 从哪个分支切出来的
      // 简报按**真正走的那条分支**选，不看 Segmented 显示成什么：非 git 目录时界面只是
      // 把它画成 repo，wtMode 仍是 'new'，于是会发一份「你已经在独立 worktree、去 git branch -m」
      // 的简报给一个连 .git 都没有的目录——agent 照做就是一串报错。
      const madeWt = wtMode === 'new' && isGitRepo && !!sessionDir
      // 「已有」选的是分支：也走建 worktree 那条编排，只是分支已经有了（existing=true，检出不新建）
      const adopt = wtMode === 'existing' && isGitRepo ? pickedBranch(existing) : ''
      if (madeWt || adopt) {
        // 组合 API（先会话后 worktree）：分支不传——后端按会话名占位，Agent 开工后语义化；
        // 派生模式走 fork-worktree（同编排 + meta 记父子）
        let baseReq: { base?: string; remote?: string } = base ? { base } : {}
        if (base.startsWith('remote:')) {
          const rest = base.slice('remote:'.length)
          const sep = rest.indexOf(':')
          baseReq = { base: rest.slice(sep + 1), remote: rest.slice(0, sep) }
        }
        const wtReq = adopt ? { branch: adopt, existing: true } : baseReq
        const res = parent
          ? await api('POST', `/sessions/${encodeURIComponent(parent)}/fork-worktree`, {
            child: finalName, dir: sessionDir, ...wtReq,
          })
          : await api('POST', '/worktree-sessions', {
            name: finalName, dir: sessionDir, ...wtReq,
          })
        actual = res.name || res.data?.session || finalName
        sessionDir = res.data?.path || sessionDir
        wtBranch = res.data?.branch || ''
        wtBase = res.data?.base || (adopt ? defBranch : base || defBranch)
      } else {
        // 主仓库直接用所选目录；「已有 worktree」= 会话 cwd 指进该 worktree；
        // 派生模式走 fork（dir 留空则继承父 cwd）
        if (wtMode === 'existing' && pickedWtPath(existing)) sessionDir = pickedWtPath(existing)
        const res = parent
          ? await api('POST', `/sessions/${encodeURIComponent(parent)}/fork`, {
            child: finalName, ...(sessionDir ? { dir: sessionDir } : {}),
          })
          : await api('POST', '/sessions', { name: finalName, dir: sessionDir })
        actual = res.name || finalName
      }
      if (agent !== 'none') {
        const cmd = agent === 'claude' ? (prefs.claudeCommand || 'claude') : (prefs.codexCommand || 'codex')
        let launch = cmd
        if (prompt.trim()) {
          // 开工简报按**这张表单真正选的**拼：在哪个目录、从哪个分支切的、占位分支叫什么、
          // 会话现在叫什么（见 TaskComposer 里同一段注释）
          const existingWt = existingWts.find((w: any) => w.path === sessionDir)
          const where: BriefWhere = madeWt
            ? { kind: 'new', path: sessionDir, base: wtBase || defBranch || 'main', branch: wtBranch || finalName }
            : adopt
              ? { kind: 'adopt', path: sessionDir, branch: wtBranch || adopt, base: wtBase || defBranch || 'main' }
              : isGitRepo
                ? { kind: 'repo', path: sessionDir || dir, branch: existingWt?.branch || defBranch || 'main' }
                : { kind: 'plain', path: sessionDir || dir }
          launch = `${cmd} ${shq(kickoffBrief(where, actual, autoReview, prompt, t))}`
        }
        await api('POST', '/tasks/_/send', { sess: actual, msg: launch })
        if (autoReview && !sessionDir) {
          message.warning(t('session.autoReviewNeedsDir'))
        } else if (autoReview && sessionDir) {
          // track 会登记跟踪并拉起 review-<会话> 监控会话:对话空闲即互审,意见回灌
          await api('POST', '/plugin/track', {
            session: actual,
            labels: { 'review:auto': 'true', role: 'author', workdir: sessionDir },
          }).catch((e: any) => message.warning(t('session.autoReviewTrackFailed') + ': ' + e.message))
        }
      }
      pushRecentDir(dir); message.success(t(parent ? 'session.fork.created' : 'session.created')); onClose(); onDone(actual)
    }
    catch (e: any) { message.error(e.message) }
    finally { setCreating(false) }
  }
  return (
    <>
      <Modal open={open} onCancel={onClose} onOk={ok}
        okText={parent ? t('session.fork.ok') : t('file.create')}
        title={parent ? t('session.fork.title', { parent }) : t('session.new')} destroyOnClose
        confirmLoading={creating}>
        <Space direction="vertical" style={{ width: '100%' }}>
          {/* 名称是一等短输入(可留空自动命名)；需求是任务本体,发给 Agent/派生分支 */}
          <Input placeholder={t('session.namePlaceholder2')} value={name} autoFocus
            onChange={(e) => { setName(e.target.value); setNameTouched(true) }} />
          {/* 顺序（交互修订 5）：先定位置——名字 → 目录 → 在哪干活；再定执行——Agent → 需求。
              派生模式目录固定 = 父会话 cwd（派生的语义就是在父目录干活），只读展示 */}
          {parent ? (
            <div style={{ color: 'var(--text-dimmer)', fontSize: 12, fontFamily: 'ui-monospace, monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={dir}>{dir || '…'}</div>
          ) : (<>
            <Space.Compact style={{ width: '100%' }}>
              <AutoComplete style={{ flex: 1 }} value={dir} onChange={setDir}
                options={recentDirs().map((d) => ({ value: d }))}
                filterOption={(input, opt) => String(opt?.value).toLowerCase().includes(input.toLowerCase())}
                placeholder={t('session.dirPlaceholder')} />
              <Button onClick={() => setPick(true)}>{t('common.browse')}</Button>
            </Space.Compact>
            {recentDirs().length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {recentDirs().map((d) => (
                  <Tooltip key={d} title={d}>
                    <Tag color={d === dir ? 'blue' : undefined} style={{ cursor: 'pointer', margin: 0, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis' }}
                      onClick={() => setDir(d)}>
                      {d.split('/').filter(Boolean).pop() || d}
                    </Tag>
                  </Tooltip>
                ))}
              </div>
            )}
          </>)}
          {/* 工作区三选一（W1 交互修订）：常驻不隐藏(cc96123 教训)——非 git 目录整组置灰+tooltip */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--text-dim)', fontSize: 13, flex: '0 0 auto' }}>{t('session.wt.where')}</span>
              <Tooltip title={isGitRepo ? '' : parent ? t('session.fork.parentNotRepo') : t('session.worktreeNeedsRepo')}>
                <Segmented size="small" value={isGitRepo ? (wtMode === 'repo' ? 'new' : wtMode) : 'repo'} onChange={(v) => setWtMode(v as any)} options={isGitRepo ? [
                  { label: t('session.wt.newWt'), value: 'new' },
                  { label: t('session.wt.existingWt', { count: existingCount }), value: 'existing', disabled: !existingCount },
                ] : [
                  { label: parent ? t('session.fork.parentDir') : t('session.wt.mainRepo'), value: 'repo' },
                ]} />
              </Tooltip>
            </div>
            <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>
              {!isGitRepo ? (parent ? t('session.fork.parentNotRepo') : t('session.worktreeNeedsRepo'))
                : wtMode === 'repo' ? (parent ? t('session.fork.hintParent') : t('session.wt.hintRepo'))
                  : wtMode === 'new' ? t('session.wt.hintNew')
                    : pickedBranch(existing) ? t('session.wt.hintAdopt') : t('session.wt.hintExisting')}
            </div>
            {/* 「已有」两组：现成的工作区（进去接着干）+ 还没有工作区的本地分支（选中即为它开一个）。
                主仓库检出的那条分支留着但置灰——不然搜 main 搜不到，人会当成漏了 */}
            {wtMode === 'existing' && (
              <Select value={existing || undefined} onChange={(v) => setExisting(v)} placeholder={t('project.where.pick')}
                style={{ width: '100%' }} optionLabelProp="title" showSearch optionFilterProp="title"
                options={[
                  ...(existingWts.length ? [{
                    label: `${t('project.where.groupWt')} · ${t('project.where.groupWtHint')}`,
                    options: existingWts.map((w: any) => {
                      const occupied = (w.sessions || []).length > 0
                      return {
                        value: pickWt(w.path),
                        title: w.branch || w.path.split('/').pop(),
                        label: (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', minWidth: 0 }}>
                            <span style={{ fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', display: 'inline-flex', alignItems: 'center', gap: 4 }}><BranchIcon size={11} />{w.branch || '?'}</span>
                            {occupied
                              ? <Tag color="green" style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{sessionLabel(w.sessions[0].session)}</Tag>
                              : w.external
                                ? <Tag style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{t('worktree.external')}</Tag>
                                : <Tag color="warning" style={{ margin: 0, fontSize: 'var(--fs-micro)', lineHeight: '16px' }}>{t('worktree.orphan')}</Tag>}
                            {(w.dirty > 0 || w.untracked > 0) && <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}>{t('session.wt.dirtyShort', { count: w.dirty + w.untracked })}</span>}
                          </span>
                        ),
                      }
                    }),
                  }] : []),
                  ...(pickable.length ? [{
                    label: `${t('project.where.groupBranch')} · ${t('project.where.groupBranchHint')}`,
                    options: pickable.map((b) => ({
                      value: pickBranch(b.name),
                      title: b.name,
                      disabled: !!b.worktree,
                      label: (
                        <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', minWidth: 0 }}>
                          <span style={{ fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', display: 'inline-flex', alignItems: 'center', gap: 4 }}><BranchIcon size={11} />{b.name}</span>
                          <span style={{ color: 'var(--text-dimmer)', fontSize: 'var(--fs-micro)' }}>
                            {b.worktree ? t('project.where.mainCheckout') : relTime(b.at, t)}
                          </span>
                        </span>
                      ),
                    })),
                  }] : []),
                ]} />
            )}
            {/* 新建 worktree 展开态（W1 交互修订 4）：只选「基于」（缺省本地主干）。
                分支不提前指定——占位按会话名派生，Agent 开工后按任务命名 */}
            {wtMode === 'new' && isGitRepo && (
              <div style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-sm)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ flex: '0 0 52px', color: 'var(--text-dim)', fontSize: 13 }}>{t('session.wt.base')}</span>
                  <Select size="small" showSearch optionFilterProp="label" style={{ flex: 1, minWidth: 0 }}
                    value={base || undefined} onChange={(v) => setBase(v)}
                    placeholder={t('session.wt.basePlaceholder')}
                    options={(() => {
                      type Opt = { value?: string; label: string; options?: { value: string; label: string }[] }
                      const locals = [
                        ...(defBranch ? [{ value: defBranch, label: t('session.wt.defaultBranch', { name: defBranch }) }] : []),
                        ...branches.filter((b) => b.name !== defBranch).map((b) => ({ value: b.name, label: b.name })),
                      ]
                      if (!remoteBranches.length) return locals as Opt[]
                      return [
                        { label: t('session.wt.localBranches'), options: locals },
                        {
                          label: t('session.wt.remoteBranches'),
                          options: remoteBranches.map((rb) => ({ value: `remote:${rb.remote}:${rb.name}`, label: `${rb.remote}/${rb.name}` })),
                        },
                      ] as Opt[]
                    })()} />
                </div>
                <div style={{ color: 'var(--text-dimmer)', fontSize: 12 }}>
                  {base.startsWith('remote:') ? t('session.wt.remoteFetchNote')
                    : agent !== 'none' ? t('session.wt.autoNote') : t('session.wt.autoNoteNoAgent')}
                </div>
              </div>
            )}
          </div>
          <Radio.Group value={agent} onChange={(e) => setAgent(e.target.value)} optionType="button" buttonStyle="solid"
            style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            <Radio.Button value="none">{t('session.agentNone')}</Radio.Button>
            <Radio.Button value="claude">{t('session.agentClaude')}</Radio.Button>
            <Radio.Button value="codex">{t('session.agentCodex')}</Radio.Button>
          </Radio.Group>
          <Input.TextArea placeholder={t('session.promptPlaceholder')} value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 8 }} />
          <Tooltip placement="right" title={agent !== 'none' ? t('session.autoReviewTip') : t('session.autoReviewNeedsAgent')}>
            <Checkbox checked={autoReview && agent !== 'none'} disabled={agent === 'none'}
              onChange={(e) => setAutoReview(e.target.checked)} style={{ width: 'fit-content' }}>
              <span style={{ fontSize: 13 }}>{t('session.autoReview')}</span>
            </Checkbox>
          </Tooltip>
        </Space>
      </Modal>
      <DirPicker open={pick} start={dir || undefined} onPick={(p) => { setDir(p); setPick(false) }} onClose={() => setPick(false)} />
    </>
  )
}


// 改名 = 只改**展示名**：会话本身叫 id，改名不动 handle，
// 所以终端标签、URL、归属、正在跑的东西全都不受影响，重名也随便。
