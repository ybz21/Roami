// 「开任务」的 composer（23 设计 §3.1 #1）：描述 ⏎ 就在新 worktree 里开干。
//
// 原来长在项目主页里（Projects.tsx 的 ProjectHome），一份状态一份 JSX 只能在那一页用；
// 项目行的「+」、⌘N 都要同一个框——抽出来，项目主页和弹窗各挂一份。
// 提交流程（先会话后 worktree、开工约定、自动互审）和 NewSessionModal 同款，不改。
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { App as AntApp, Button, Dropdown, Input } from 'antd'
import { api, upload, makeClipboardImageFile } from '../../api'
import { appendPaths } from '../../agent-paths'
import { useI18n } from '../../i18n'
import { usePreferences } from '../../preferences'
import { shellQuote as shq } from '../../shell-quote'
import { taskNameFromPrompt } from './NewSessionModal'
import { VoiceInput } from '../chat/VoiceInput'
import { CheckIcon, ChevronDown, CircleIcon, PaperclipIcon } from '../../icons'
import { BranchIcon } from '../git/parts'
import type { LocalBranch } from '../git/local-branches'
import { ExistingWorkPicker, pickBranch, pickWt, pickedBranch, pickedWtPath } from './ExistingWorkPicker'
import { kickoffBrief, type BriefWhere } from './kickoff-brief'

export type TaskComposerHandle = { focus: () => void; insert: (text: string) => void }

export const TaskComposer = forwardRef<TaskComposerHandle, {
  dir: string
  isGit: boolean
  openTerm: (name: string) => void
  /** 建完（会话已开）：项目主页刷新列表，弹窗关掉自己 */
  onCreated?: (name: string) => void
  autoFocus?: boolean
}>(function TaskComposer({ dir, isGit, openTerm, onCreated, autoFocus }, ref) {
  const { t } = useI18n()
  const { message } = AntApp.useApp()
  const [prefs] = usePreferences()
  const [prompt, setPrompt] = useState('')
  const [wtMode, setWtMode] = useState<'new' | 'existing'>('new')
  const [agent, setAgent] = useState<'claude' | 'codex' | 'none'>('claude')
  const [wtsAll, setWtsAll] = useState<any[]>([])
  // 「已有」选中值：'wt:<路径>'（进这个工作区）/ 'br:<分支>'（为这条分支开一个工作区）
  const [existing, setExisting] = useState('')
  const [defBranch, setDefBranch] = useState('')
  const [base, setBase] = useState('')
  const [branches, setBranches] = useState<LocalBranch[]>([])
  const [remoteBranches, setRemoteBranches] = useState<{ remote: string; name: string }[]>([])
  const [autoReview, setAutoReview] = useState(false)
  const [creating, setCreating] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const promptRef = useRef<any>(null)
  useImperativeHandle(ref, () => ({
    focus: () => promptRef.current?.focus?.(),
    insert: (text) => setPrompt((cur) => appendPaths(cur, [text])),
  }))
  useEffect(() => { if (autoFocus) setTimeout(() => promptRef.current?.focus?.(), 0) }, [autoFocus])

  // worktree 清单（「已有(N)」）与分支（「基于」）：和项目主页同两条接口
  useEffect(() => {
    if (!dir || !isGit) { setWtsAll([]); return }
    let stop = false
    const loadWts = () => api('GET', `/git/worktrees?dir=${encodeURIComponent(dir)}`).then((r) => {
      if (!stop) setWtsAll(Array.isArray(r?.data) ? r.data : [])
    }).catch(() => {})
    loadWts()
    const i = setInterval(loadWts, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [dir, isGit])
  // 分支清单同时喂两处：「基于」（新建档的起点）和「已有」（可收养的分支）。
  // worktree 清单 5s 一轮，分支跟着一起——刚 push 完删掉工作区的分支得立刻能选到。
  useEffect(() => {
    if (!dir || !isGit) { setBranches([]); return }
    let stop = false
    const load = () => api('GET', `/git/branches?dir=${encodeURIComponent(dir)}`).then((r) => {
      if (stop) return
      const def = r?.data?.default || ''
      setDefBranch(def)
      setBranches(r?.data?.branches || [])
      setRemoteBranches(r?.data?.remotes || [])
      setBase((prev) => prev || def) // 「基于」默认跟主干走；用户选过就不再被覆盖
    }).catch(() => {})
    load()
    const i = setInterval(load, 5000)
    return () => { stop = true; clearInterval(i) }
  }, [dir, isGit])
  const wts = useMemo(() => wtsAll.filter((w: any) => !w.isMain && !w.prunable), [wtsAll])
  const mainPath = useMemo(() => wtsAll.find((w: any) => w.isMain)?.path || '', [wtsAll])
  // 可收养的分支 = 没被任何工作区检出的（主仓库检出的那条在单子里置灰，不算候选）
  const freeBranches = useMemo(() => branches.filter((b) => !b.worktree), [branches])
  const existingCount = wts.length + freeBranches.length
  // 选中的东西没了（工作区被删、分支被开了工作区）就落到下一个候选，别停在一个不存在的值上
  useEffect(() => {
    setExisting((prev) => {
      if (wts.some((w: any) => w.path === pickedWtPath(prev))) return prev
      if (freeBranches.some((b) => b.name === pickedBranch(prev))) return prev
      return wts[0] ? pickWt(wts[0].path) : (freeBranches[0] ? pickBranch(freeBranches[0].name) : '')
    })
  }, [wts, freeBranches])

  const uploadImages = async (images: File[]) => {
    if (!images.length || uploading) return
    setUploading(true)
    try {
      const res = await upload('/tmp', images)
      setPrompt((v) => appendPaths(v, res.saved))
      message.success(t('chat.uploadedFiles', { count: images.length, dir: '/tmp' }))
    } catch (e: any) { message.error(t('chat.uploadFailed', { message: e.message })) }
    finally { setUploading(false) }
  }
  // Ctrl+V 粘贴图片：一次只取一张（同张截图常以多种 MIME 重复出现，全收会插入两次）
  const onPaste = (e: React.ClipboardEvent) => {
    if (!e.clipboardData?.items) return
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.type.startsWith('image/')) {
        const f = item.getAsFile()
        if (f) { e.preventDefault(); void uploadImages([makeClipboardImageFile(f, item.type, 0)]); return }
      }
    }
  }
  // 「基于」显示名：远端分支存的是 remote:<remote>:<branch>，展示时还原成 remote/branch
  const baseLabel = (() => {
    const v = base || defBranch
    if (!v) return t('project.baseDefault')
    if (!v.startsWith('remote:')) return v
    const rest = v.slice('remote:'.length)
    const sep = rest.indexOf(':')
    return `${rest.slice(0, sep)}/${rest.slice(sep + 1)}`
  })()

  const goCreate = async () => {
    if (!dir || creating) return
    if (!prompt.trim()) { message.error(t('session.promptOrNameRequired')); return }
    if (isGit && wtMode === 'existing' && !existing) { message.error(t('project.where.pickFirst')); return }
    // 名字一律从需求派生：这就是任务名（23 设计 §3.3 #6），agent 不再改它
    let finalName = taskNameFromPrompt(prompt)
    if (!finalName) {
      const d = new Date()
      finalName = 'task-' + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0') + '-' + String(d.getHours()).padStart(2, '0') + String(d.getMinutes()).padStart(2, '0')
    }
    try {
      setCreating(true)
      let actual: string
      const wantWt = isGit && wtMode === 'new'
      // 选的是分支：同样走建 worktree 那条编排，只是分支已经有了（existing=true，后端检出而不新建）
      const adopt = isGit && wtMode === 'existing' ? pickedBranch(existing) : ''
      let sessionDir = dir
      let wtBranch = ''   // worktree 里的分支（新建档是后端给的占位名）
      let wtBase = ''     // 从哪个分支切出来的 / 拿哪个分支当比对基准
      if (wantWt || adopt) {
        // 「基于」：本地分支存裸名，远端分支编码成 remote:<remote>:<branch>，提交前拆回 {base, remote}
        let baseReq: { base?: string; remote?: string } = base && base !== defBranch ? { base } : {}
        if (base.startsWith('remote:')) {
          const rest = base.slice('remote:'.length)
          const sep = rest.indexOf(':')
          baseReq = { base: rest.slice(sep + 1), remote: rest.slice(0, sep) }
        }
        const res = await api('POST', '/worktree-sessions', adopt
          ? { name: finalName, dir, branch: adopt, existing: true }
          : { name: finalName, dir, ...baseReq })
        actual = res.name || res.data?.session || finalName
        sessionDir = res.data?.path || dir
        wtBranch = res.data?.branch || ''
        wtBase = res.data?.base || (adopt ? defBranch : base || defBranch)
      } else {
        const wtPath = isGit && wtMode === 'existing' ? pickedWtPath(existing) : ''
        sessionDir = wtPath || dir
        const res = await api('POST', '/sessions', { name: finalName, dir: sessionDir })
        actual = res.name || finalName
      }
      if (agent !== 'none') {
        const cmd = agent === 'claude' ? (prefs.claudeCommand || 'claude') : (prefs.codexCommand || 'codex')
        // 开工简报：把这张表单上真正选了什么写给 agent——在哪个目录、从哪个分支切的、占位分支叫什么、
        // 会话现在叫什么。从前这里是两条写死的话，agent 只能猜自己在哪儿，人也无从核对「选的和发出去的
        // 是不是一回事」。会话改名那一条也回来了：派生出来的名字是需求原文的前 16 个字，
        // 只配当占位，真名字得等 agent 看懂任务之后再起。
        const existingWt = wtsAll.find((w: any) => w.path === sessionDir)
        const where: BriefWhere = wantWt
          ? { kind: 'new', path: sessionDir, base: wtBase || defBranch || 'main', branch: wtBranch || finalName }
          : adopt
            ? { kind: 'adopt', path: sessionDir, branch: wtBranch || adopt, base: wtBase || defBranch || 'main' }
            : isGit
              ? { kind: 'repo', path: sessionDir, branch: existingWt?.branch || defBranch || 'main' }
              : { kind: 'plain', path: sessionDir }
        const brief = kickoffBrief(where, actual, autoReview, prompt, t)
        await api('POST', '/tasks/_/send', { sess: actual, msg: brief ? `${cmd} ${shq(brief)}` : cmd })
        if (autoReview) {
          await api('POST', '/plugin/track', {
            session: actual,
            labels: { 'review:auto': 'true', role: 'author', workdir: sessionDir },
          }).catch((e: any) => message.warning(t('session.autoReviewTrackFailed') + ': ' + e.message))
        }
      }
      setPrompt(''); message.success(t('session.created')); openTerm(actual); onCreated?.(actual)
    } catch (e: any) { message.error(e.message) }
    finally { setCreating(false) }
  }

  return (
    <div className="tt-composer prj-in" style={{ animationDelay: '60ms' }}>
      <Input.TextArea ref={promptRef} value={prompt} onChange={(e) => setPrompt(e.target.value)}
        placeholder={isGit ? t('project.composerPlaceholder') : t('project.composerPlain')} autoSize={{ minRows: 2, maxRows: 6 }} variant="borderless"
        onPaste={onPaste}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void goCreate() } }} />
      <input ref={fileRef} type="file" accept="image/*" multiple style={{ display: 'none' }}
        onChange={(e) => { const fs = e.target.files ? Array.from(e.target.files) : []; e.target.value = ''; if (fs.length) void uploadImages(fs) }} />
      {/* 控制条按「在哪干活 / 谁来干 / 动作」三组排，组内 6px、组间 16px，不画分隔线 */}
      <div className="tt-cbar">
        {isGit && (
          <span className="tt-cgrp">
            <button type="button" className={`tt-pill${wtMode === 'new' ? ' on' : ''}`} aria-pressed={wtMode === 'new'} onClick={() => setWtMode('new')}><BranchIcon size={11} />{t('project.where.new')}</button>
            <button type="button" className={`tt-pill${wtMode === 'existing' ? ' on' : ''}`} aria-pressed={wtMode === 'existing'}
              disabled={!existingCount} onClick={() => setWtMode('existing')}>{t('project.where.existing', { count: existingCount })}</button>
            {wtMode === 'existing' && (
              <ExistingWorkPicker wts={wts} branches={branches} mainPath={mainPath} value={existing} onChange={setExisting} />
            )}
            {wtMode === 'new' && (
              <Dropdown trigger={['click']} menu={{
                selectedKeys: [base || defBranch],
                items: [
                  ...(branches.length ? [{ key: 'g-local', type: 'group' as const, label: t('session.wt.localBranches'),
                    children: branches.map((b) => ({ key: b.name, label: b.name, onClick: () => setBase(b.name) })) }] : []),
                  ...(remoteBranches.length ? [{ key: 'g-remote', type: 'group' as const, label: t('session.wt.remoteBranches'),
                    children: remoteBranches.map((r) => ({ key: `remote:${r.remote}:${r.name}`, label: `${r.remote}/${r.name}`, onClick: () => setBase(`remote:${r.remote}:${r.name}`) })) }] : []),
                ],
              }}>
                <button type="button" className="tt-pill sel" title={t('session.wt.base')}>
                  {t('project.basedOnShort')}
                  <b>{baseLabel}</b>
                  <ChevronDown size={10} />
                </button>
              </Dropdown>
            )}
          </span>
        )}
        <span className="tt-cgrp">
          <button type="button" className={`tt-pill${agent === 'claude' ? ' on' : ''}`} aria-pressed={agent === 'claude'} onClick={() => setAgent('claude')}>Claude</button>
          <button type="button" className={`tt-pill${agent === 'codex' ? ' on' : ''}`} aria-pressed={agent === 'codex'} onClick={() => setAgent('codex')}>Codex</button>
          <button type="button" className={`tt-pill${agent === 'none' ? ' on' : ''}`} aria-pressed={agent === 'none'} onClick={() => setAgent('none')}>{t('project.agent.none')}</button>
        </span>
        {agent !== 'none' && (
          <span className="tt-cgrp">
            <button type="button" className={`tt-pill${autoReview ? ' on' : ''}`} title={t('session.autoReviewTip')}
              aria-pressed={autoReview} onClick={() => setAutoReview((v) => !v)}>
              {autoReview ? <CheckIcon size={11} /> : <CircleIcon size={11} />}{t('session.autoReview')}
            </button>
          </span>
        )}
        <span className="tt-cend">
          <VoiceInput inline accent="var(--accent)" onResult={(text) => setPrompt((v) => (v ? v + ' ' : '') + text)} />
          <button type="button" className="tt-pill ico" title={t('project.attachImage')} aria-label={t('project.attachImage')}
            disabled={uploading} onClick={() => fileRef.current?.click()}>
            <PaperclipIcon size={13} />
          </button>
          <Button type="primary" size="small" className="prj-go" loading={creating} onClick={goCreate}>{t('project.go')}</Button>
        </span>
      </div>
    </div>
  )
})
