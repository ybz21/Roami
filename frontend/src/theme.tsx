// 主题（黑/白）切换：单一 mode 状态，持久化到 localStorage。
// 所有应用级颜色从 THEME_TOKENS 出发，同时喂给 CSS 变量和 Antd ConfigProvider。
// 组件只使用 var(--...) 或语义常量，不再各自判断黑白主题。
import { createContext, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from 'react'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import { useI18n } from './i18n'
import { usePreferences, savePreferences } from './preferences'
import { applyDensity } from './layout'

export type ThemeMode = 'dark' | 'light'
const KEY = 'ttmux-theme'
const FONT_FAMILY = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Roboto, Helvetica, Arial, sans-serif"

type ThemeTokens = {
  css: Record<string, string>
  antd: {
    bgBase: string
    bgContainer: string
    bgElevated: string
    bgLayout: string
    border: string
    borderSecondary: string
    shadowSecondary: string
  }
}

export const THEME_TOKENS: Record<ThemeMode, ThemeTokens> = {
  dark: {
    css: {
      '--bg-base': '#0d1117',
      '--bg-container': '#161b22',
      '--bg-elevated': '#1b222b',
      '--bg-term': '#0b0f14',
      '--border': '#30363d',
      '--border-subtle': '#21262d',
      '--text-bright': '#e6edf3',
      '--text-dim': '#8b949e',
      '--text-dimmer': '#6e7681',
      // 强调色只有这一组，别再往组件里写死蓝色十六进制（见下面 buildTheme 的注释）：
      //   --accent       线 / 图标 / 链接（浅蓝，压在深底上够亮）
      //   --accent-solid 实心块：主按钮、Segmented 选中、徽标（深蓝，白字够对比）
      //   --accent-soft  淡底：强调件（芯片、徽标、聚焦光晕）——**不是**选中行
      // 选中行走 --sel-bg：中性提亮，不带色相。深底上一层 14% 的蓝糊成一块脏navy，
      // 而选中这件事本来就不该靠颜色喊——左边那条 3px accent 线已经说清了「就是这一条」。
      '--accent': '#58a6ff',
      '--accent-solid': '#1f6feb',
      '--accent-soft': 'rgba(31, 111, 235, .14)',
      '--accent-border': 'rgba(88, 166, 255, .45)',
      '--sel-bg': 'rgba(255, 255, 255, .065)',
      // 成功/运行绿也只有这一组，同理别写死：--ok 线/文字（含 diff 的 +），
      // --ok-solid 实心块，--ok-soft 淡底，--ok-border 描边
      '--ok': '#3fb950',
      '--ok-solid': '#238636',
      '--ok-soft': 'rgba(63, 185, 80, .14)',
      '--ok-border': 'rgba(63, 185, 80, .42)',
      // 危险/断开红同样只有这一组。此前没有这一档，#f85149 就散在 index.css 与
      // 各组件里手抄——和当初蓝、绿被抄得到处都是的成因一模一样。
      '--danger': '#f85149',
      '--danger-soft': 'rgba(248, 81, 73, .16)',
      '--danger-border': 'rgba(248, 81, 73, .45)',
      // 警示黄：同理，此前 #d29922 也散在十几个组件里各写各的
      '--warn': '#d29922',
      '--warn-soft': 'rgba(210, 153, 34, .12)',
      '--warn-border': 'rgba(210, 153, 34, .40)',
      '--brand-grad': 'linear-gradient(180deg, #f5f7fa 0%, #c3c9d1 46%, #9aa1ab 56%, #e7ebef 100%)',
      '--list-hover': 'rgba(255, 255, 255, .025)',
      '--scroll-thumb': '#2a313a',
      '--scroll-thumb-hover': '#3d444d',
      '--card-hover-shadow': '0 8px 24px rgba(1, 4, 9, .5)',
      '--elevated-shadow': '0 16px 48px rgba(1, 4, 9, .55)',
      '--xterm-bg': '#0b0f14',
      '--xterm-fg': '#e6edf3',
      '--xterm-selection': 'rgba(88, 166, 255, .35)',
      '--hl-comment': '#8b949e',
      '--hl-keyword': '#ff7b72',
      '--hl-string': '#a5d6ff',
      '--hl-number': '#79c0ff',
      '--hl-title': '#d2a8ff',
      '--hl-attr': '#7ee787',
      '--hl-built': '#ffa657',
    },
    antd: {
      bgBase: '#0d1117',
      bgContainer: '#161b22',
      bgElevated: '#1b222b',
      bgLayout: '#0d1117',
      border: '#2a313a',
      borderSecondary: '#21262d',
      shadowSecondary: '0 8px 24px rgba(1,4,9,0.5)',
    },
  },
  light: {
    css: {
      '--bg-base': '#f6f8fa',
      '--bg-container': '#ffffff',
      '--bg-elevated': '#ffffff',
      '--bg-term': '#ffffff',
      '--border': '#d0d7de',
      '--border-subtle': '#e6e9ec',
      '--text-bright': '#1f2328',
      '--text-dim': '#57606a',
      '--text-dimmer': '#8c959f',
      '--accent': '#0969da',
      '--accent-solid': '#1f6feb',
      '--accent-soft': 'rgba(31, 111, 235, .10)',
      '--sel-bg': 'rgba(27, 31, 36, .055)',
      '--accent-border': 'rgba(31, 111, 235, .40)',
      '--ok': '#1a7f37',
      '--ok-solid': '#1f883d',
      '--ok-soft': 'rgba(31, 136, 61, .10)',
      '--ok-border': 'rgba(31, 136, 61, .40)',
      '--danger': '#cf222e',
      '--danger-soft': 'rgba(207, 34, 46, .10)',
      '--danger-border': 'rgba(207, 34, 46, .40)',
      '--warn': '#9a6700',
      '--warn-soft': 'rgba(154, 103, 0, .10)',
      '--warn-border': 'rgba(154, 103, 0, .35)',
      '--brand-grad': 'linear-gradient(180deg, #2c333b 0%, #1f2328 100%)',
      '--list-hover': 'rgba(27, 31, 36, .04)',
      '--scroll-thumb': '#c9d1d9',
      '--scroll-thumb-hover': '#aab1b9',
      '--card-hover-shadow': '0 8px 24px rgba(140, 149, 159, .18)',
      '--elevated-shadow': '0 16px 48px rgba(140, 149, 159, .22)',
      '--xterm-bg': '#ffffff',
      '--xterm-fg': '#1f2328',
      '--xterm-selection': 'rgba(9, 105, 218, .28)',
      '--hl-comment': '#6e7781',
      '--hl-keyword': '#cf222e',
      '--hl-string': '#0a3069',
      '--hl-number': '#0550ae',
      '--hl-title': '#8250df',
      '--hl-attr': '#116329',
      '--hl-built': '#953800',
    },
    antd: {
      bgBase: '#f6f8fa',
      bgContainer: '#ffffff',
      bgElevated: '#ffffff',
      bgLayout: '#f6f8fa',
      border: '#d0d7de',
      borderSecondary: '#e6e9ec',
      shadowSecondary: '0 8px 24px rgba(140,149,159,0.18)',
    },
  },
}

const ThemeCtx = createContext<{ mode: ThemeMode; toggle: () => void; setMode: (m: ThemeMode) => void }>({
  mode: 'dark', toggle: () => {}, setMode: () => {},
})
export const useThemeMode = () => useContext(ThemeCtx)

// 强调色种子。**别在别处照抄这个十六进制**：antd 的 darkAlgorithm 会在它基础上再推导
// 一层（#58a6ff → rgb(78,144,220)），照抄的值和 antd 实际画出来的必然差一档——
// 这正是「名称」段控件和「＋新项目」并排时两种蓝的成因。
// 要和 antd 一致就用 --accent-solid（下面回填成推导后的真值）。
const ACCENT_SEED = THEME_TOKENS.dark.css['--accent']
// 成功色种子：antd 的 Tag success / Result / 校验通过都吃它，和自绘的 --ok 同源
const SUCCESS_SEED = THEME_TOKENS.dark.css['--ok']

/** antd 推导后的实际主色：Segmented 选中底、自绘实心块都用它 */
function solidAccent(mode: ThemeMode): string {
  return antdTheme.getDesignToken({
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: { colorPrimary: ACCENT_SEED },
  }).colorPrimary
}

function buildTheme(mode: ThemeMode) {
  const dark = mode === 'dark'
  const t = THEME_TOKENS[mode].antd
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: ACCENT_SEED,
      colorSuccess: SUCCESS_SEED,
      // 圆角跟 CSS 的 --r-* 同一套刻度：控件 10 / 卡片 14 / 小件 6。
      // 这三个数一改，所有 antd 控件一起对齐，不必逐个组件覆盖。
      borderRadius: 10, borderRadiusLG: 14, borderRadiusSM: 6,
      fontFamily: FONT_FAMILY,
      fontSize: 14, lineHeight: 1.6,
      colorBgBase: t.bgBase,
      colorBgContainer: t.bgContainer,
      colorBgElevated: t.bgElevated,
      colorBgLayout: t.bgLayout,
      colorBorder: t.border,
      colorBorderSecondary: t.borderSecondary,
      boxShadowSecondary: t.shadowSecondary,
      wireframe: false,
    },
    components: {
      Layout: dark
        ? { siderBg: t.bgBase, headerBg: t.bgContainer, bodyBg: t.bgBase }
        : { siderBg: t.bgContainer, headerBg: t.bgContainer, bodyBg: t.bgLayout },
      Menu: dark ? {
        darkItemBg: 'transparent', darkItemSelectedBg: 'rgba(88,166,255,0.16)',
        darkItemSelectedColor: THEME_TOKENS.dark.css['--accent'], darkItemHoverBg: 'rgba(255,255,255,0.04)',
        itemBorderRadius: 8, itemHeight: 42, itemMarginInline: 8,
      } : {
        itemBg: 'transparent', itemSelectedBg: 'rgba(31,111,235,0.10)',
        itemSelectedColor: THEME_TOKENS.light.css['--accent-solid'], itemHoverBg: 'rgba(31,111,235,0.06)',
        itemBorderRadius: 8, itemHeight: 42, itemMarginInline: 8,
      },
      Card: { borderRadiusLG: 14, paddingLG: 18, headerFontSize: 15 },
      Button: { fontWeight: 500, primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none' },
      Modal: { borderRadiusLG: 14, contentBg: t.bgContainer, headerBg: 'transparent' },
      Segmented: { borderRadius: 10, itemSelectedBg: solidAccent(mode), itemSelectedColor: '#fff' },
      Tag: { borderRadiusSM: 6 },
      Tooltip: { borderRadius: 10 },
    },
  }
}

function applyCssVars(mode: ThemeMode) {
  const root = document.documentElement
  root.dataset.theme = mode
  root.style.colorScheme = mode
  for (const [key, value] of Object.entries(THEME_TOKENS[mode].css)) {
    root.style.setProperty(key, value)
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_TOKENS[mode].css['--bg-container'])
  // 实心强调色以 antd 推导出来的为准，自绘控件才不会比 antd 控件差一档蓝
  root.style.setProperty('--accent-solid', solidAccent(mode))
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { locale } = useI18n()
  const [prefs] = usePreferences()
  const [mode, setModeLocal] = useState<ThemeMode>(() => {
    try { const v = localStorage.getItem(KEY); if (v === 'light' || v === 'dark') return v } catch {}
    return 'dark'
  })
  useEffect(() => {
    if (prefs.theme && (prefs.theme === 'dark' || prefs.theme === 'light')) setModeLocal(prefs.theme)
  }, [prefs.theme])
  useLayoutEffect(() => { applyCssVars(mode) }, [mode])
  // 密度是用户偏好，写到 <html data-density> 上；档位由 layout.ts 写 data-size，两者正交
  useLayoutEffect(() => { applyDensity(prefs.workspace.density) }, [prefs.workspace.density])
  const setMode = (m: ThemeMode) => {
    setModeLocal(m)
    savePreferences({ theme: m })
    try { localStorage.setItem(KEY, m) } catch {}
  }
  const toggle = () => setMode(mode === 'dark' ? 'light' : 'dark')
  return (
    <ThemeCtx.Provider value={{ mode, toggle, setMode }}>
      <ConfigProvider locale={locale === 'en-US' ? enUS : zhCN} theme={buildTheme(mode)}>{children}</ConfigProvider>
    </ThemeCtx.Provider>
  )
}
