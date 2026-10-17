// 输入行最左那枚「+」：低频、但每次都要找的那几件事。
//
// 为什么不是一排 pill：手机上输入行只有 392px，摆得下的只有「说话」和「发送」。
// 为什么不是一张普通菜单：这里每一条都关系到**这一轮怎么跑**，而「现在是哪一档」
// 恰恰是菜单答不出来的——于是右端带上当前值（权限模式 / 目标 / 模型 / 上下文占用），
// 面板一打开就先回答「现在什么样」，再谈改不改。
//
// 内容与取值在 composer-plus.ts（纯函数、可测），这里只管画、点，以及「开到指定档」
// 这件只有在浏览器里才做得成的事：按一下、看一眼画面、不对再按。
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Dropdown } from 'antd'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { ArchiveIcon, BotIcon, CheckIcon, ChevronRight, ForkIcon, PaperclipIcon, PlusIcon, SearchIcon, ShieldIcon, TargetIcon } from '../../icons'
import { goalFromPane, modeChoices, paneMode, plusGroups, type GoalState, type PlusGroupId, type PlusRowId } from './composer-plus'
import { modeKey, toMode, type AgentStatus } from './status'

const ICON: Record<PlusRowId, ReactNode> = {
  files: <PaperclipIcon size={14} />,
  mode: <ShieldIcon size={14} />,
  goal: <TargetIcon size={14} />,
  model: <BotIcon size={14} />,
  compact: <ArchiveIcon size={14} />,
  review: <SearchIcon size={14} />,
  git: <ForkIcon size={14} />,
}

const GROUP_LABEL: Record<PlusGroupId, string> = {
  bring: 'chat.plus.bring',
  turn: 'chat.plus.turn',
  do: 'chat.plus.do',
  goto: '', // 单独一行的跳转，只靠分隔线断开，不值得再加一行标题
}

// 按一下之后等画面变的节奏（毫秒，累加约 2s）。按键要过一趟 tmux、TUI 再重画，
// 320ms 一刀切太紧：读到的还是旧的那一档，会被误判成「按了没反应」。
const SETTLE_AT = [200, 250, 350, 500, 700]
// 一路按过去的上限：轮一圈没遇到目标档就停（bypassPermissions 要配置允许才轮得到）
const MAX_PRESSES = 8

export function ComposerPlus({ name, agent, status, uploading, onFiles, onCycleMode, onCommand, onOpenGit, onMouseDown }: {
  /** 会话名：面板要自己回读终端画面，看当前是哪一档、目标跑成什么样 */
  name: string
  agent?: 'claude' | 'codex' | 'opencode'
  status?: AgentStatus
  uploading?: boolean
  onFiles: () => void
  /** 注入 Shift+Tab（tmux 的 BTab）：跟人在 TUI 里按是同一个动作，两端都认 */
  onCycleMode: () => void
  /** 发一条斜杠命令（/model /compact /review /goal /approvals），TUI 自己弹选择框 */
  onCommand: (cmd: string) => void
  onOpenGit?: () => void
  onMouseDown?: (e: React.MouseEvent) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  // 当前权限档以**画面**为准：转录里那份要等下一条消息才更新，而这里问的就是「此刻」
  const [pane, setPane] = useState<{ mode?: string; goal?: GoalState }>({})
  // 正在往哪一档开（连按 Shift+Tab，边按边看画面）
  const [driving, setDriving] = useState<string | null>(null)
  const [showModes, setShowModes] = useState(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const readPane = useCallback(async (): Promise<string | undefined> => {
    try {
      // 40 行：Codex 的界面画在备用屏上半部，末尾十几行是空的，抓少了连页脚都拿不到
      const r = await api('GET', `/sessions/${encodeURIComponent(name)}/capture?lines=40`)
      const text = r?.data || ''
      const next = { mode: paneMode(text, agent), goal: goalFromPane(text) }
      if (alive.current) setPane(next)
      return next.mode
    } catch { return undefined }
  }, [name, agent])

  // 打开就读一次画面；关了把展开的档位收回去，下次打开还是那张干净的卡
  useEffect(() => { if (open && agent) void readPane() }, [open, agent, readPane])
  useEffect(() => { if (!open) { setShowModes(false); setDriving(null) } }, [open])

  const mode = pane.mode ? toMode(pane.mode) : status?.mode

  /**
   * 开到指定的一档。
   *
   * TUI 只给了「轮换」这一个动作，没有「跳到 X」。但既然每按一下都能从画面读出
   * 落在哪一档，那就按一下、看一眼、不对再按——把轮换拼成直选。轮一圈回到起点
   * 仍没遇到目标（比如这个会话根本不允许 bypassPermissions），就停在原处：
   * 宁可这一档去不了，也不能把人丢在一个他没选过的档上。
   */
  const driveMode = async (target: string) => {
    if (driving) return
    let cur = await readPane()
    if (cur === target) return
    const start = cur
    setDriving(target)
    for (let i = 0; i < MAX_PRESSES; i++) {
      onCycleMode()
      const next = await settle(cur)
      if (!alive.current) return
      // 按下去画面纹丝不动：这一下没进到 TUI（比如它正卡在别的选择框里）。
      // 停手——继续盲按只会把档位越按越乱，而人根本看不见按了几下。
      if (!next) break
      cur = next
      if (cur === target) break
      // 确确实实转回起点了（不是「还没变」被误当成没动），说明这一档到不了
      if (cur === start) break
    }
    if (alive.current) setDriving(null)
  }

  /** 等画面从 prev 变成别的什么；一直没变就返回 undefined（当作这一下没生效） */
  const settle = async (prev?: string): Promise<string | undefined> => {
    for (const ms of SETTLE_AT) {
      await new Promise((r) => setTimeout(r, ms))
      if (!alive.current) return undefined
      const now = await readPane()
      if (now !== prev) return now
    }
    return undefined
  }

  const groups = plusGroups({
    agent, status, mode, goal: pane.goal, uploading,
    canGit: !!onOpenGit, modePending: !!driving, t,
  })

  const LABEL: Record<PlusRowId, string> = {
    files: t('chat.uploadToCwd'),
    mode: t('chat.plus.mode'),
    goal: t('chat.plus.goal'),
    model: t('chat.model'),
    compact: t('chat.compact'),
    review: t('chat.plus.review'),
    git: t('git.title'),
  }
  const TITLE: Record<PlusRowId, string> = {
    files: t('chat.uploadToCwd'),
    mode: t('chat.plus.modeHint'),
    goal: t('chat.plus.goalHint'),
    model: t('chat.modelPick'),
    compact: t('chat.plus.compactHint'),
    review: t('chat.plus.reviewHint'),
    git: t('git.title'),
  }
  // 改档位后面板不关：档就在眼前，切到了哪一档看得见。
  // 其余几条要么跳到别的界面、要么在 TUI 里弹出选择框，点完即关。
  const RUN: Record<PlusRowId, () => void> = {
    files: () => { setOpen(false); onFiles() },
    mode: () => setShowModes((v) => !v),
    goal: () => { setOpen(false); onCommand('/goal') },
    model: () => { setOpen(false); onCommand('/model') },
    compact: () => { setOpen(false); onCommand('/compact') },
    review: () => { setOpen(false); onCommand('/review') },
    git: () => { setOpen(false); onOpenGit?.() },
  }

  const choices = modeChoices(agent, mode?.id)

  return (
    <Dropdown trigger={['click']} placement="topLeft" open={open} onOpenChange={setOpen}
      popupRender={() => (
        <div className="cc-plus" role="menu">
          {groups.map((g) => (
            <div className="cc-plus-grp" key={g.id}>
              {GROUP_LABEL[g.id] && <div className="cc-plus-head">{t(GROUP_LABEL[g.id])}</div>}
              {g.rows.map((r) => (
                <div key={r.id}>
                  <button type="button" role="menuitem"
                    className={`cc-plus-row${r.pending ? ' is-pending' : ''}`}
                    aria-expanded={r.id === 'mode' ? showModes : undefined}
                    disabled={r.disabled} title={TITLE[r.id]} onClick={RUN[r.id]}>
                    <span className="ic" aria-hidden>{ICON[r.id]}</span>
                    <span className="nm">{LABEL[r.id]}</span>
                    {r.value && (
                      <span className="val" style={r.tone ? { color: r.tone } : undefined}>
                        {r.dot && <i style={{ background: r.dot }} />}{r.value}
                      </span>
                    )}
                    {r.kbd && <kbd>{r.kbd}</kbd>}
                    {r.id === 'mode' && (
                      <span className="chev" style={{ transform: showModes ? 'rotate(90deg)' : 'none' }} aria-hidden>
                        <ChevronRight size={12} />
                      </span>
                    )}
                  </button>

                  {/* 档位直选：TUI 只有「轮换」，这里替你一路按到你选的那一档 */}
                  {r.id === 'mode' && showModes && (
                    <div className="cc-plus-sub">
                      {choices.map((id) => {
                        const label = t(modeKey(id))
                        return (
                          <button key={id} type="button" role="menuitemradio" aria-checked={mode?.id === id}
                            className={`cc-plus-row is-sub${driving === id ? ' is-pending' : ''}`}
                            disabled={!!driving} onClick={() => void driveMode(id)}>
                            <span className="ic" aria-hidden>{mode?.id === id ? <CheckIcon size={13} /> : null}</span>
                            <span className="nm">{label.startsWith('chat.mode.') ? id : label}</span>
                            {driving === id && <span className="val">{t('chat.plus.modeWaiting')}</span>}
                          </button>
                        )
                      })}
                      {/* Codex 的沙箱/审批策略不在 Shift+Tab 的轮换里，它自己有一张表 */}
                      {agent === 'codex' && (
                        <button type="button" role="menuitem" className="cc-plus-row is-sub"
                          title={t('chat.plus.approvalsHint')}
                          onClick={() => { setOpen(false); onCommand('/approvals') }}>
                          <span className="ic" aria-hidden />
                          <span className="nm">{t('chat.plus.approvals')}</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}>
      <button type="button" className="tt-pill ico" aria-label={t('chat.more')} title={t('chat.more')}
        onMouseDown={onMouseDown}><PlusIcon size={14} /></button>
    </Dropdown>
  )
}
