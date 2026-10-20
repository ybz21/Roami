# Web UI 设计系统（强制）

前端所有新界面必须走这套令牌与规则。它不是审美偏好，是一次实测的结论：改造前在概览页
一屏上量出 **10 种字号**（最常用的三种是 11.5 / 11 / 10.5）、**8 种圆角**、**10 种间距**。
半像素级的差别没人看得出是刻意的，只会读成"随手写的"——这就是"界面不够优雅"的来源。

配套设计稿：[13 移动端响应式](../design/web/13-mobile-responsive.md) ·
[14 桌面工作区](../design/web/14-desktop-workspace.md)。真机验收跑法见
[web-ui-checklist.md](./web-ui-checklist.md)。

## 1. 令牌：只准用这些值

全部定义在 `frontend/src/index.css` 的 `:root`。**不要在组件里写死数值**——写死的那一刻，
下一个人就没有依据再改回来。

### 字号（六档）

| 令牌 | 值 | 用途 |
|---|---:|---|
| `--fs-micro` | 11 | 眉标、角标。**唯一允许 <12 的一档** |
| `--fs-meta` | 12 | 次要信息：时间、路径、计数 |
| `--fs-sm` | 13 | 密集列表行、区块标题 |
| `--fs-body` | 14 | 正文（compact 档 15） |
| `--fs-lg` | 16 | 区块标题 |
| `--fs-title` | 22 | 页面标题 |

**除眉标/角标外不许低于 12px。** 不要出现 10.5 / 11.5 / 12.5 / 13.5 这类半档。

### 圆角（四档）

`--r-xs 6`（控件）· `--r-sm 10`（行、导航项）· `--r-card 14`（卡片、sheet 内块）·
`--r-pill 999`（胶囊、徽标）。

### 间距（五档）

`--sp-1 4` · `--sp-2 8` · `--sp-3 12` · `--sp-4 16` · `--sp-5 24`。一律 4 的倍数，
不要 3/5/7/9/11/13。

### 强调色（一组）

| 令牌 | 用途 |
|---|---|
| `--accent` | 线、图标、链接、强调线 |
| `--accent-solid` | 实心块：主按钮、Segmented 选中、徽标 |
| `--accent-soft` | 淡底：选中行、当前导航项 |
| `--accent-border` | 强调描边 |

### 成功 / 运行绿（一组）

| 令牌 | 用途 |
|---|---|
| `--ok` | 线、文字、状态点、diff 的 `+`、Codex 一方的强调色 |
| `--ok-solid` | 实心块 |
| `--ok-soft` | 淡底 |
| `--ok-border` | 描边 |

### 错误红 / 警示黄（各一组）

| 令牌 | 用途 |
|---|---|
| `--danger` | 线、文字、diff 的 `-`、失败徽标 |
| `--danger-soft` | 淡底：错误行、diff 删除行 |
| `--danger-border` | 描边 |
| `--warn` | 线、文字、「待确认 / 已拒绝」、改文件类工具的色条 |
| `--warn-soft` / `--warn-border` | 同上 |

改造前 `#f85149` 与 `#d29922` 散在十几个组件里各写各的，深浅色主题还各差一档。
**全站一共只有四支色**：蓝（强调）、绿（成功 / 运行 / Codex）、黄（警示）、红（错误）。
需要第五支的时候，先确认不是「同一件事换了个说法」——工具调用的分类色条就是靠这四支撑起来的
（见 [15 · 对话渲染](../design/web/15-chat-render/README.md)）。

**蓝和绿都只有这一支。** 改造前全站数出四种蓝（`#58a6ff` / `#1f6feb` / `#79b8ff` / `#388bfd`）
和五种绿（`#3fb950` / `#10a37f` / `#52c41a` / `hsl(140,…)` / `hsl(150,…)`）——同一个「运行中」
在会话页和概览页不是一个绿。品牌标（`logo-mark.svg`）用的也是这支蓝，不另调。
antd 的 `colorPrimary` / `colorSuccess` 由 `theme.tsx` 从同一份 token 喂进去，自绘控件和
antd 控件才不会差一档。

> **别照抄十六进制。** antd 的 `darkAlgorithm` 会在 seed 基础上**再推导一层**
> （`#58a6ff` → `rgb(78,144,220)`），任何照抄 seed 的自绘控件都会比 antd 自己画的差一档，
> 而且深浅色各差一档。`--accent-solid` 由 `theme.tsx` 用 `antdTheme.getDesignToken()`
> 推导后回填，要跟 antd 一致就用它。

### 密度 / 层级 / 安全区

`--tap 44`（最小命中边长）、`--ctl-h`、`--pad-page`、`--gap`；九个具名 z 层
（`--z-sticky` … `--z-drag`），不要再写 1199/1200/1201 这类魔数；`--safe-*` 与 `--kb`。

## 2. 结构规则

- **页头统一 `.tt-pagehead`**：标题（h2）+ 右侧动作（.acts）；眉标与说明按需添加，不能重复标题或解释显而易见的操作。
  沿用已有结构，不要各写各的标题行。
- **不要嵌套同名壳**：页面已经在 tab 或路由里说明了身份，就别再套一层带同名标题的 Card。
- **区块标题**用 13px 正常字重的亮色文字，**不要**「小号 + 大字距 + 横贯全宽的虚线」——
  那条线不承载信息却横穿版面。
- **少画框**：同一屏里状态条、侧轨这类次级容器用底色区分即可，不必每个都描 1px 边。
- **箭头等符号用 SVG 图标**，不要 `→ ← ⌃ ✕ ▾ ▸ ✓ ⎇ ⧉` 这类文字符号，也不要 emoji
  （🔄 📎 🤖 📢）：字号下与标点混在一起，粗细跟不上界面的线性图标语言，emoji 还各平台一个样、
  高低不齐。图标统一从 [`frontend/src/icons.tsx`](../../frontend/src/icons.tsx) 取
  （24×24 viewBox / `currentColor` / 1.8 线宽），文件类型图标在 `file-icons.tsx`、
  Git 相关在 `git/parts.tsx`。**同一个动作全站必须是同一枚图标**——关闭曾经在 Dock 是 `✕`、
  浏览器标签是 `×`、文件页签又是第三个写法。
- **图标别写进 i18n 文案**：`'＋ 新建'` 这种把符号焊死在译文里，换图标要改两份 locale，
  而且换不成 SVG。文案只写字，图标在调用处用 `icon={<PlusIcon />}` 给。
- **输入卡统一 `.tt-composer`**：项目页「下任务」和对话页「发消息」是同一件事的两处长相——
  一张卡（`.tt-composer`），上面 `variant="borderless"` 的文本框，下面一条控制条
  （`.tt-cbar`：左边 `.tt-cgrp` 放「怎么干」的选项，右边 `.tt-cend` 贴动作）。
  选项一律是 `.tt-pill`（`.on` 选中 / `.ico` 图标钮 / `.sel` 带值下拉 / `.danger`），
  主动作是唯一那枚实心圆 `.tt-send`。**一条控制条只有一种控件长相**，也只有一个实心块。
  pill 必须是 `<button type="button">`，不是 `<span onClick>`。

## 3. 触控

- 粗指针（`html[data-pointer="coarse"]`）下所有可点目标命中区 ≥ **44**。
  **用伪元素撑命中区，不要撑视觉尺寸**。
- 视觉小于 44 的控件（角标、行内链接）必须显式补 `::after` 命中区，并在真机上用
  `document.elementFromPoint` 验证——截图看不出来。

## 4. 断点与档位

只有一个入口：`useLayout()`（`frontend/src/layout.ts`）。**不要**再读 `window.innerWidth`
或自己 `matchMedia`。四档：compact <600 · medium 600–904 · expanded 905–1279 · large ≥1280。
纯样式差异走 `<html>` 上的 `data-size` / `data-orient` / `data-pointer` / `data-density`，
不要往组件里塞 JS 分支。

`data-size="compact"`（窗口窄）与 `data-density="compact"`（信息密）**是两个属性**，
同名不同义，合并会在 CSS 里撞车。

## 5. 反复踩到的坑

这几条都在真机或 CDP 上咬过，改相关代码前先读：

| 现象 | 真因 |
|---|---|
| 页头 `position: sticky` 不生效 | 祖先里有个**不滚动的** `overflow:auto`。任何非 `visible` 的祖先都会成为 sticky 的参照系 |
| antd `Dropdown.Button` 把兄弟节点挤没/盖住 | 它内部的 `Space.Compact` 在 flex 容器里是块级 flex 子项，会一路撑开。包一层 `flex:0 0 auto` |
| `--kb` 与 `env(keyboard-inset-height)` 对不上 | VirtualKeyboard API 的 `geometrychange` 没订阅，`--kb` 只能靠 resize 顺带刷新 |
| 中间省略的名字读成两个词 | 头尾两段之间留了 gap。它俩是同一个名字被切开的两半，间距只加在项目前缀之后 |
| `项目 · 会话` 两截都被截成碎片 | 两段等比例挨压。给项目前缀 `flex: 0 100 auto`，让它先被吸收干净 |
| 软键盘收起后终端仍然只有半屏 | Chrome 的 keyboard inset 可能卡住不复位。**量高度前先确认 `env(keyboard-inset-height)` 是 0** |
| CDP 改视口后档位不变 | `Emulation.setDeviceMetricsOverride` 不触发 `resize` / `matchMedia change`。**每个视口重载一次**；纯 CSS 容器查询不受影响 |

## 6. 提交前必过

```bash
cd frontend && npm run typecheck && npm run i18n:check && npx vitest run && npm run build
```

`i18n:check` 除了查两份 locale 对齐，还会查 `t('key')` 引用的 key 是否存在——
key 拼错时界面会**原样显示这个 key**，而两份 locale 都缺它，只查对齐是发现不了的。
