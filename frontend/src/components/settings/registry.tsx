// 分类、内容和搜索共用这份清单；生效范围独立于导航分组。
import type { ReactNode } from 'react'
import { PushSettings } from './push-settings'
import { HotkeyRecorder } from './hotkey-recorder'
import { KEY_ACTIONS, DEFAULT_KEYBINDINGS, keybindingConflicts, resolveKeybindings, type KeyAction } from '../shell/keybindings'
import { BrowserSettings } from './browser-settings'
import { PhoneSettings } from './phone-settings'
import { SpeechSettings } from './speech-settings'
import { P2PSettings } from './p2p-settings'
import { EnvVarsSettings } from './env-vars'
import { MemoryGuardSettings } from './memory-settings'
import { QuickCommandsSettings } from './quick-commands'
import { ChangePasswordSettings, TwoFactorSettings, CertDownloadButton } from './security-settings'
import { AboutSettings } from './about-settings'
import { ClusterSettings } from '../cluster/ClusterSettings'
import { AgentMemorySettings } from './agent-memory-settings'
import { AgentMessageSettings } from './agent-message-settings'
import { AgentSettings } from './agent-settings'
import { FullscreenAction, LogoutAction, fullscreenSupported } from './account-actions'
import AgentImprovement from '../agent/AgentImprovement'

export const MAX_ROWS = 6

/** 生效范围。 */
export type Scope = 'mine' | 'node' | 'cluster' | 'browser'

export type Control =
  | { kind: 'switch'; get: () => boolean; set: (v: boolean) => void }
  | { kind: 'segment'; options: { value: string; label: ReactNode }[]; get: () => string; set: (v: string) => void }
  | { kind: 'select'; options: { value: string; label: string }[]; get: () => string; set: (v: string) => void }
  | { kind: 'text'; get: () => string; set: (v: string) => void; placeholder?: string }
  | { kind: 'custom'; node: ReactNode }

export interface SettingItem {
  id: string
  label: string
  /** 一句话说后果，不复述控件。开关型可省，用 control 自带的说明 */
  desc?: string
  /** 保留键名作为搜索别名。 */
  key?: string
  control: Control
  /** 偏离默认才挂：'exp' 实验性 / 'restart' 改完要重启 */
  badge?: 'exp' | 'restart'
  scope?: Scope
  /** 自定义块没有 label/desc 可索引，靠这个补搜索词 */
  keywords?: string
  /** 整页就这一块时置 true：页头已经写了标题与说明，块自己不再画一遍行头 */
  bare?: boolean
}

export interface SettingsPageDef {
  id: string
  name: string
  /** 分类名称，用于搜索结果。 */
  parent?: string
  scope: Scope
  hideScope?: boolean
  note?: string
  items: SettingItem[]
  /** 页级动作：管整页而不是某一项，摆在标题右边 */
  action?: { label: string; hint?: string; run: () => void | Promise<void> }
}

export interface SettingsGroup { title: string; pages: string[] }

export interface SettingsModel {
  groups: SettingsGroup[]
  pages: Record<string, SettingsPageDef>
  order: string[]
}

/** 这一页的所有可搜文本 */
export function itemText(it: SettingItem, page: SettingsPageDef): string {
  return [it.label, it.desc, it.key, it.keywords, page.name, page.parent].filter(Boolean).join(' ').toLowerCase()
}

/**
 * 组装 model。**在 hook 里调**——label 要过 t()，控件要读当前偏好。
 * deps 是各种上下文的值与写入口，由 SettingsPage 传进来（这里不自己调 hook，
 * 免得每加一项设置就多一层 hook 依赖）。
 */
export function buildSettings(deps: {
  t: (k: string, v?: Record<string, string | number>) => string
  theme: string
  setTheme: (v: 'dark' | 'light') => void
  locale: string
  setLocale: (v: any) => void
  prefs: any
  setPrefs: (p: any) => void
  setWorkspace: (p: any) => void
  /** 退出登录：原来在侧栏脚「当前设备」菜单里，22 设计把它并进设置页 */
  onLogout?: () => void
  developmentRsi?: boolean
  nodeId?: string | null
  experimentRunId?: string
  onExperimentRun?: (id: string) => void
  onBrowserReady?: (run: (() => Promise<void>) | null) => void
  onBrowserRestart: () => void
  onEnvPush: () => void
  onMemoryBack?: () => void
  onInstall?: () => void
  fullscreen?: { active: boolean; toggle: () => void }
}): SettingsModel {
  const { t, prefs } = deps
  const ws = prefs.workspace || {}

  const themeItem: SettingItem = {
    id: 'theme', label: t('settings.appearance'), desc: t('settings.themeHelp'), key: 'theme',
    control: {
      kind: 'segment', get: () => deps.theme, set: (v) => deps.setTheme(v as 'dark' | 'light'),
      options: [{ value: 'dark', label: t('common.darkTheme') }, { value: 'light', label: t('common.lightTheme') }],
    },
  }
  const claudeThemeItem: SettingItem = {
    id: 'claudeThemeSync', label: t('set.claudeTheme'), desc: t('set.claudeThemeHelp'), key: 'claudeThemeSync',
    keywords: 'claude theme 主题 对比度',
    control: { kind: 'switch', get: () => prefs.claudeThemeSync !== false, set: (on) => deps.setPrefs({ claudeThemeSync: on }) },
  }
  const localeItem: SettingItem = {
    id: 'locale', label: t('settings.language'), desc: t('settings.languageHelp'), key: 'locale',
    control: {
      kind: 'select', get: () => deps.locale, set: deps.setLocale,
      options: [{ value: 'zh-CN', label: '中文' }, { value: 'en-US', label: 'English' }],
    },
  }
  const promptPopupItem: SettingItem = {
    id: 'promptPopupOff', label: t('settings.promptPopupDefault'), desc: t('settings.promptPopupDefaultHelp'), key: 'promptPopupOff', keywords: 'new session 新会话',
    control: { kind: 'switch', get: () => !prefs.promptPopupOff, set: (on) => deps.setPrefs({ promptPopupOff: !on }) },
  }
  const pushItem: SettingItem = {
    id: 'push', label: t('set.push'), desc: t('set.pushHelp'), key: 'push', scope: 'browser',
    keywords: '推送 通知 push notification 手机 锁屏',
    control: { kind: 'custom', node: <PushSettings /> },
  }
  const kb = resolveKeybindings(prefs.keybindings)
  const kbConflicts = keybindingConflicts(kb)
  const keyItems: SettingItem[] = KEY_ACTIONS.map((a: KeyAction) => ({
    id: 'key.' + a, label: t('key.' + a), desc: t('key.' + a + 'Help'), key: 'keybindings.' + a,
    keywords: '快捷键 hotkey shortcut keybinding',
    control: { kind: 'custom', node: <HotkeyRecorder value={kb[a].spec} fallback={DEFAULT_KEYBINDINGS[a]}
      conflict={kbConflicts[a] ? t('key.' + kbConflicts[a]) : undefined}
      onChange={(v) => deps.setPrefs({ keybindings: { ...(prefs.keybindings || {}), [a]: v } })} /> },
  }))
  const voiceItem: SettingItem = {
    id: 'showVoiceButton', label: t('set.voiceButton'), desc: t('set.voiceButtonHelp'), key: 'showVoiceButton', scope: 'mine',
    control: { kind: 'switch', get: () => prefs.showVoiceButton !== false, set: (on) => deps.setPrefs({ showVoiceButton: on }) },
  }

  const pages: SettingsPageDef[] = [
    ...(deps.developmentRsi ? [{ id: 'experiments.rsi', name: t('set.pageImprovement'), scope: 'node' as const, items: [{ id: 'rsiWorkflow', label: t('agent.experiment.title'), bare: true, control: { kind: 'custom' as const, node: <AgentImprovement key={deps.nodeId} node={deps.nodeId || null} workflow runId={deps.experimentRunId} onRun={deps.onExperimentRun} /> }, keywords: 'RSI workflow pipeline experiment 流水线 实验 每日 复盘 Issue Codex' }] }] : []),
    { id: 'agent.messages', name: t('set.pageNotifications'), scope: 'node', items: [{ id: 'agentMessages', label: t('agent.notification.settings'), bare: true, control: { kind: 'custom', node: <AgentMessageSettings /> }, keywords: 'notifications reminders delivery quiet hours 通知 消息 免打扰 提醒 投递' }, pushItem] },
    { id: 'agent.runtime', name: t('agent.models.settings'), scope: 'node', note: '', items: [{ id: 'agentRuntime', label: t('agent.models.settings'), bare: true, control: { kind: 'custom', node: <AgentSettings /> }, keywords: 'Agent Main Worker Base URL API Key model 智能体 模型 密钥' }] },
    { id: 'agent.memory', name: t('agent.memoryCenter'), scope: 'node', note: '', items: [{ id: 'agentMemory', label: t('agent.memoryCenter'), bare: true, control: { kind: 'custom', node: <AgentMemorySettings onBack={deps.onMemoryBack} /> }, keywords: 'Agent memory memories 记忆 偏好 对话 项目 任务 来源 忘记' }] },
    {
      id: 'ui.look', name: t('set.pageLook'), scope: 'mine',
      items: [
        themeItem,
        claudeThemeItem,
        localeItem,
        {
          id: 'density', label: t('set.density'), desc: t('set.densityHelp'), key: 'workspace.density',
          control: {
            kind: 'segment', get: () => ws.density || 'cozy', set: (v) => deps.setWorkspace({ density: v }),
            options: [{ value: 'cozy', label: t('set.densityCozy') }, { value: 'compact', label: t('set.densityCompact') }],
          },
        },
      ],
    },
    {
      id: 'ui.layout', name: t('set.pageLayout'), scope: 'mine',
      items: [
        {
          id: 'navCollapsed', label: t('set.navRail'), desc: t('set.navRailHelp'), key: 'workspace.navCollapsed',
          control: { kind: 'switch', get: () => ws.navCollapsed !== false, set: (v) => deps.setWorkspace({ navCollapsed: v }) },
        },
        {
          id: 'dockOpen', label: t('set.dockOpen'), desc: t('set.dockOpenHelp'), key: 'workspace.dockOpen',
          control: { kind: 'switch', get: () => ws.dockOpen !== false, set: (v) => deps.setWorkspace({ dockOpen: v }) },
        },
        {
          id: 'dpadOn', label: t('set.dpad'), desc: t('set.dpadHelp'), key: 'workspace.dpadOn',
          control: { kind: 'switch', get: () => ws.dpadOn !== false, set: (v) => deps.setWorkspace({ dpadOn: v }) },
        },
        {
          id: 'dpadSide', label: t('set.dpadSide'), desc: t('set.dpadSideHelp'), key: 'workspace.dpadSide',
          control: {
            kind: 'segment', get: () => ws.dpadSide || 'right', set: (v) => deps.setWorkspace({ dpadSide: v }),
            options: [{ value: 'left', label: t('set.dpadLeft') }, { value: 'right', label: t('set.dpadRight') }],
          },
        },
        ...(deps.fullscreen || fullscreenSupported() ? [{
          id: 'fullscreen', label: t('set.windowDisplay'), scope: 'browser' as const,
          keywords: 'fullscreen 全屏 状态栏',
          control: { kind: 'custom' as const, node: <FullscreenAction controller={deps.fullscreen} /> },
        }] : []),
      ],
    },
    {
      id: 'ui.keys', name: t('set.pageKeys'), scope: 'mine',
      items: keyItems,
    },
    {
      id: 'agent.new', name: t('set.pageNewSession'), scope: 'mine',
      items: [
        {
          id: 'quickCommands', label: t('settings.quickCommands'), desc: t('settings.quickCommandsHelp'),
          key: 'quickCommands', control: { kind: 'custom', node: <QuickCommandsSettings /> },
        },
        promptPopupItem,
      ],
    },
    {
      id: 'node.browser', name: t('set.pageBrowser'), scope: 'node',
      note: t('settings.browserHelp'),
      items: [{
        id: 'browser', label: t('settings.browser'), bare: true, control: { kind: 'custom', node: <BrowserSettings onRestartReady={deps.onBrowserReady} /> },
        keywords: 'chrome headless window scale profile 无头 窗口 缩放 镜像',
      }],
    },
    {
      id: 'node.phone', name: t('settings.phoneTitle'), scope: 'node',
      items: [{
        id: 'phone', label: t('settings.phoneTitle'), bare: true, control: { kind: 'custom', node: <PhoneSettings /> },
        keywords: 'android ios adb avd emulator 模拟器 真机 镜像',
      }],
    },
    {
      id: 'node.speech', name: t('settings.speech'), scope: 'node',
      note: t('settings.speechHelp'),
      items: [voiceItem, {
        id: 'speech', label: t('settings.speech'), bare: true, control: { kind: 'custom', node: <SpeechSettings /> },
        keywords: 'asr whisper openai volcano 火山 语音 识别 密钥 apikey',
      }],
    },
    {
      id: 'node.p2p', name: t('set.pageTransfer'), scope: 'mine',
      items: [{
        id: 'p2p', label: t('settings.p2p'), bare: true, control: { kind: 'custom', node: <P2PSettings /> },
        keywords: 'p2p stun ice webrtc 直连 中转 frp 超时 速率 下载 加速 网络 视频 图片 预览',
      }],
    },
    {
      id: 'node.memory', name: t('set.pageMemory'), scope: 'node',
      note: t('set.memoryNote'),
      items: [{
        id: 'sessionMemory', label: t('set.mem.limit'), bare: true,
        control: { kind: 'custom', node: <MemoryGuardSettings /> },
        keywords: 'memory oom cgroup 内存 上限 护栏 限制 kill',
      }],
    },
    {
      id: 'node.env', name: t('settings.tabEnv'), scope: 'node',
      note: t('set.envHelp'),
      items: [{
        id: 'env', label: t('env.globalVariables'), bare: true,
        control: { kind: 'custom', node: <EnvVarsSettings /> }, keywords: 'env 环境变量 export',
      }],
      action: { label: t('env.pushToSessions'), hint: t('set.envPushHint'), run: deps.onEnvPush },
    },
    {
      id: 'cluster', name: t('set.pageCluster'), scope: 'cluster',
      items: [{
        id: 'cluster', label: t('settings.tabCluster'), bare: true, control: { kind: 'custom', node: <ClusterSettings /> },
        keywords: 'hub node 中心 节点 集群 多机 令牌 token 注册 证书',
      }],
    },
    {
      id: 'sec', name: t('set.pageSecurity'), scope: 'node',
      items: [
        { id: 'password', label: t('password.title'), desc: t('set.passwordHelp'), control: { kind: 'custom', node: <ChangePasswordSettings /> }, keywords: '口令 密码 password' },
        { id: 'totp', label: t('twoFactor.title'), key: 'totp', control: { kind: 'custom', node: <TwoFactorSettings /> }, keywords: '2fa totp 两步 动态码 authenticator' },
        { id: 'cert', label: t('install.downloadCert'), desc: t('set.certHelp'), control: { kind: 'custom', node: <CertDownloadButton /> }, keywords: 'https ca 证书 cert 安全上下文' },
        ...(deps.onLogout ? [{ id: 'logout', label: t('set.account'), scope: 'browser' as const,
          keywords: 'logout sign out 退出 登录 账户', control: { kind: 'custom' as const, node: <LogoutAction onLogout={deps.onLogout} /> } }] : []),
      ],
    },
    {
      id: 'about', name: t('set.pageAbout'), scope: 'mine', hideScope: true,
      items: [{
        id: 'about', label: t('set.pageAbout'), bare: true, control: { kind: 'custom', node: <AboutSettings onInstall={deps.onInstall} /> },
        keywords: 'pwa 安装 版本 更新 github 证书 关于',
      }],
    },
  ]

  // 浏览器页的「保存并重启」是页级动作：它管的是整页的参数，不是某一行
  const browserPage = pages.find((p) => p.id === 'node.browser')
  if (browserPage) browserPage.action = { label: t('settings.browserRelaunch'), hint: t('set.restartHint'), run: deps.onBrowserRestart }

  const byId: Record<string, SettingsPageDef> = {}
  pages.forEach((p) => { byId[p.id] = p })

  const groups: SettingsGroup[] = [
    { title: t('set.groupPreferences'), pages: ['ui.look', 'ui.layout', 'ui.keys', 'agent.new'] },
    { title: t('set.groupAgent'), pages: ['agent.runtime', 'agent.memory', ...(deps.developmentRsi ? ['experiments.rsi'] : [])] },
    { title: t('set.groupNotifications'), pages: ['agent.messages', 'node.speech'] },
    { title: t('set.groupDevices'), pages: ['node.browser', 'node.phone', 'node.p2p', 'cluster'] },
    { title: t('set.groupSystem'), pages: ['node.env', 'sec', 'about'] },
  ]
  for (const group of groups) for (const id of group.pages) byId[id].parent = group.title
  const order = groups.flatMap(group => group.pages)

  if (import.meta.env.DEV) {
    pages.forEach((p) => {
      const rows = p.items.filter((it) => it.control.kind !== 'custom').length
      if (rows > MAX_ROWS) console.warn(`[settings] 「${p.name}」有 ${rows} 项，超过一屏预算 ${MAX_ROWS}——该拆二级了`)
    })
  }

  return { groups, pages: byId, order }
}
