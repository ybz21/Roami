// 设置清单：**唯一**的设置出处。分类树、每一页的内容、搜索索引、手机端列表全从这里生成。
//
// 两条约束写在这里而不是文档里，因为只有在这里才拦得住：
//   ① 一页 ≤ MAX_ROWS 项。一页装不下就是这一类该拆二级，而不是让它长出滚动条
//      （设置页不做长流，翻页由树决定——见 docs/design/settings/index.html）。
//      超了不是报错，是 dev 下 console.warn，因为 items 的条数依赖运行时（比如 iOS 只在 macOS 出现）。
//   ② 页级动作（保存并重启浏览器、推送到会话）不占行数预算，摆在页头。
//
// 标签走 labelKey/descKey 而不是中文串：搜索索引必须在 t() 之后建，否则英文界面搜不到任何东西。
import type { ReactNode } from 'react'
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
import { StatusBarSettings } from './status-bar-settings'
import { AccountActions } from './account-actions'

export const MAX_ROWS = 6

/** 值写在哪——决定它落在树的哪一段，以及页头那枚徽标写什么 */
export type Scope = 'mine' | 'node' | 'cluster'

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
  /** 展示用键名（claudeCommand 这种）——既是搜索命中项，也是用户描述问题时的说法 */
  key?: string
  control: Control
  /** 偏离默认才挂：'exp' 实验性 / 'restart' 改完要重启 */
  badge?: 'exp' | 'restart'
  /** 别名行：这一项真正的家（「常用」页用） */
  from?: string
  /** 自定义块没有 label/desc 可索引，靠这个补搜索词 */
  keywords?: string
  /** 整页就这一块时置 true：页头已经写了标题与说明，块自己不再画一遍行头 */
  bare?: boolean
}

export interface SettingsPageDef {
  id: string
  name: string
  /** 父级名字，面包屑用；叶子页没有父级时为空 */
  parent?: string
  scope: Scope
  note?: string
  items: SettingItem[]
  /** 页级动作：管整页而不是某一项，摆在标题右边 */
  action?: { label: string; hint?: string; run: () => void | Promise<void> }
}

export type TreeNode =
  | { kind: 'section'; title: string; note: string }
  | { kind: 'leaf'; page: string }
  | { kind: 'parent'; id: string; title: string; kids: string[] }

export interface SettingsModel {
  nodes: TreeNode[]
  pages: Record<string, SettingsPageDef>
  order: string[]
}

/** 树上的条数：一页只有一个自定义块时不显示——「1」不是信息 */
export function rowCount(p: SettingsPageDef): number {
  const rows = p.items.filter((it) => it.control.kind !== 'custom').length
  return rows || (p.items.length > 1 ? p.items.length : 0)
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
  nodeLabel: string
  isHub: boolean
  onBrowserRestart: () => void
  onEnvPush: () => void
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
  // 全屏 / 退出登录：原来挂在侧栏脚「当前设备」那枚账户菜单里（22 设计 §3.2 拍板：侧栏脚只留 设置 / 收起）
  const accountItem: SettingItem = {
    id: 'account', label: t('set.account'), desc: t('set.accountDesc'),
    keywords: '全屏 退出 登录 fullscreen logout',
    control: { kind: 'custom', node: <AccountActions onLogout={deps.onLogout} /> },
  }
  const localeItem: SettingItem = {
    id: 'locale', label: t('settings.language'), desc: t('settings.languageHelp'), key: 'locale',
    control: {
      kind: 'select', get: () => deps.locale, set: deps.setLocale,
      options: [{ value: 'zh-CN', label: '中文' }, { value: 'en-US', label: 'English' }],
    },
  }
  const claudeItem: SettingItem = {
    id: 'claudeCommand', label: t('set.claudeCmd'), desc: t('set.claudeCmdHelp'), key: 'claudeCommand',
    control: {
      kind: 'text', placeholder: 'claude',
      get: () => prefs.claudeCommand || '',
      set: (v) => deps.setPrefs({ claudeCommand: v.trim() || 'claude' }),
    },
  }
  const codexItem: SettingItem = {
    id: 'codexCommand', label: t('set.codexCmd'), desc: t('set.codexCmdHelp'), key: 'codexCommand',
    control: {
      kind: 'text', placeholder: 'codex',
      get: () => prefs.codexCommand || '',
      set: (v) => deps.setPrefs({ codexCommand: v.trim() || 'codex' }),
    },
  }
  const promptPopupItem: SettingItem = {
    id: 'promptPopupOff', label: t('settings.promptPopupDefault'), desc: t('settings.promptPopupDefaultHelp'), key: 'promptPopupOff',
    control: { kind: 'switch', get: () => !prefs.promptPopupOff, set: (on) => deps.setPrefs({ promptPopupOff: !on }) },
  }
  // 快捷键：一动作一行，全站的键都在这儿改。本机别的软件占了哪个键，换一个就是
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
    id: 'showVoiceButton', label: t('set.voiceButton'), desc: t('set.voiceButtonHelp'), key: 'showVoiceButton',
    control: { kind: 'switch', get: () => prefs.showVoiceButton !== false, set: (on) => deps.setPrefs({ showVoiceButton: on }) },
  }

  const pages: SettingsPageDef[] = [
    {
      id: 'common', name: t('set.pageCommon'), scope: 'mine', note: t('set.pageCommonNote'),
      items: [
        { ...themeItem, from: `${t('set.groupUi')} · ${t('set.pageLook')}` },
        { ...localeItem, from: `${t('set.groupUi')} · ${t('set.pageLook')}` },
        { ...claudeItem, from: `${t('set.groupAgent')} · ${t('set.pageBin')}` },
        { ...promptPopupItem, from: `${t('set.groupAgent')} · ${t('set.pageNewSession')}` },
        { ...voiceItem, from: `${t('set.groupAgent')} · ${t('set.pageNewSession')}` },
      ],
    },
    {
      id: 'ui.look', name: t('set.pageLook'), parent: t('set.groupUi'), scope: 'mine',
      items: [
        themeItem,
        claudeThemeItem,
        accountItem,
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
      id: 'ui.layout', name: t('set.pageLayout'), parent: t('set.groupUi'), scope: 'mine',
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
      ],
    },
    {
      id: 'ui.keys', name: t('set.pageKeys'), parent: t('set.groupUi'), scope: 'mine', note: t('set.pageKeysNote'),
      items: keyItems,
    },
    {
      id: 'ui.status', name: t('status.settings'), parent: t('set.groupUi'), scope: 'mine',
      note: t('status.settingsDesc'),
      items: [{
        id: 'statusBar', label: t('status.settings'), bare: true,
        keywords: '状态条 status bar cpu 内存 memory 插件 plugin 主机 host',
        control: { kind: 'custom', node: <StatusBarSettings /> },
      }],
    },
    {
      id: 'agent.bin', name: t('set.pageBin'), parent: t('set.groupAgent'), scope: 'mine',
      items: [claudeItem, codexItem],
    },
    {
      id: 'agent.new', name: t('set.pageNewSession'), parent: t('set.groupAgent'), scope: 'mine',
      items: [
        {
          id: 'quickCommands', label: t('settings.quickCommands'), desc: t('settings.quickCommandsHelp'),
          key: 'quickCommands', control: { kind: 'custom', node: <QuickCommandsSettings /> },
        },
        promptPopupItem,
        voiceItem,
      ],
    },
    {
      id: 'node.browser', name: t('settings.browser'), parent: t('set.groupNode'), scope: 'node',
      note: t('settings.browserHelp'),
      items: [{
        id: 'browser', label: t('settings.browser'), bare: true, control: { kind: 'custom', node: <BrowserSettings /> },
        keywords: 'chrome headless window scale profile 无头 窗口 缩放 镜像',
      }],
    },
    {
      id: 'node.phone', name: t('settings.phoneTitle'), parent: t('set.groupNode'), scope: 'node',
      items: [{
        id: 'phone', label: t('settings.phoneTitle'), bare: true, control: { kind: 'custom', node: <PhoneSettings /> },
        keywords: 'android ios adb avd emulator 模拟器 真机 镜像',
      }],
    },
    {
      id: 'node.speech', name: t('settings.speech'), parent: t('set.groupNode'), scope: 'node',
      note: t('settings.speechHelp'),
      items: [{
        id: 'speech', label: t('settings.speech'), bare: true, control: { kind: 'custom', node: <SpeechSettings /> },
        keywords: 'asr whisper openai volcano 火山 语音 识别 密钥 apikey',
      }],
    },
    {
      id: 'node.p2p', name: t('set.pageTransfer'), parent: t('set.groupNode'), scope: 'node',
      items: [{
        id: 'p2p', label: t('settings.p2p'), bare: true, control: { kind: 'custom', node: <P2PSettings /> },
        keywords: 'p2p stun ice webrtc 直连 中转 frp 超时 速率 下载 加速 网络 视频 图片 预览',
      }],
    },
    {
      id: 'node.memory', name: t('set.pageMemory'), parent: t('set.groupNode'), scope: 'node',
      note: t('set.memoryNote'),
      items: [{
        id: 'sessionMemory', label: t('set.mem.limit'), bare: true,
        control: { kind: 'custom', node: <MemoryGuardSettings /> },
        keywords: 'memory oom cgroup 内存 上限 护栏 限制 kill',
      }],
    },
    {
      id: 'node.env', name: t('settings.tabEnv'), parent: t('set.groupNode'), scope: 'node',
      note: t('set.envHelp'),
      items: [{
        id: 'env', label: t('env.globalVariables'), bare: true,
        control: { kind: 'custom', node: <EnvVarsSettings /> }, keywords: 'env 环境变量 export',
      }],
      action: { label: t('env.pushToSessions'), hint: t('set.envPushHint'), run: deps.onEnvPush },
    },
    {
      id: 'cluster', name: t('settings.tabCluster'), scope: 'cluster',
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
      ],
    },
    {
      id: 'about', name: t('set.pageAbout'), scope: 'mine',
      items: [{
        id: 'about', label: t('set.pageAbout'), bare: true, control: { kind: 'custom', node: <AboutSettings /> },
        keywords: 'pwa 安装 版本 更新 github 证书 关于',
      }],
    },
  ]

  // 浏览器页的「保存并重启」是页级动作：它管的是整页的参数，不是某一行
  const browserPage = pages.find((p) => p.id === 'node.browser')
  if (browserPage) browserPage.action = { label: t('settings.browserRelaunch'), hint: t('set.restartHint'), run: deps.onBrowserRestart }

  const byId: Record<string, SettingsPageDef> = {}
  pages.forEach((p) => { byId[p.id] = p })

  // 段标题本身就把「值写在哪」说清了，不再挂第二行注解——那是设计稿里的解释文，
  // 搬进产品就是每次开设置都要重读一遍的噪音。分段也跟着改：原来「整个集群 / 这台设备」
  // 把两类硬塞进一个标题，才不得不写注解去解释。现在安全归「这台机器」（口令与两步验证
  // 写的就是这台的 config.yaml），集群只剩多机，关于与安装挂在最后、不需要段标题。
  const nodes: TreeNode[] = [
    { kind: 'section', title: t('set.secMine'), note: '' },
    { kind: 'leaf', page: 'common' },
    { kind: 'parent', id: 'ui', title: t('set.groupUi'), kids: ['ui.look', 'ui.layout', 'ui.keys', 'ui.status'] },
    { kind: 'parent', id: 'agent', title: t('set.groupAgent'), kids: ['agent.bin', 'agent.new'] },
    // 这一段的页直接摊平：段标题已经写了「这台机器」，再套一层同名的父节点是把同一件事说两遍
    { kind: 'section', title: deps.nodeLabel ? t('set.secNode', { node: deps.nodeLabel }) : t('set.groupNode'), note: '' },
    ...(['node.browser', 'node.phone', 'node.speech', 'node.p2p', 'node.env', 'sec'].map((page) => ({ kind: 'leaf', page } as TreeNode))),
    { kind: 'section', title: t('set.secCluster'), note: '' },
    { kind: 'leaf', page: 'cluster' },
    { kind: 'leaf', page: 'about' },
  ]

  if (import.meta.env.DEV) {
    pages.forEach((p) => {
      const rows = p.items.filter((it) => it.control.kind !== 'custom').length
      if (rows > MAX_ROWS) console.warn(`[settings] 「${p.name}」有 ${rows} 项，超过一屏预算 ${MAX_ROWS}——该拆二级了`)
    })
  }

  return { nodes, pages: byId, order: pages.map((p) => p.id) }
}
