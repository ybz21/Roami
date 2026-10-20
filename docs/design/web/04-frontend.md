# 04 · 前端设计（React + Vite + Antd）

← 返回 [README](./README.md) ｜ 页面线框见 [05-pages](./05-pages.md)

## 1. 前端架构

当前实现的应用入口、状态所有者及依赖方向见
[前端应用入口与工作区拆分](../20261020-前端应用拆分/README.md)。`App.tsx` 只负责启动与入口选择，
`src/app/AppShell.tsx` 组合响应式工作区，页面选择、目录刷新、标签状态和终端运行状态分别由独立模块负责。
下方目录与 react-router / Zustand 是早期设计草案；当前沿用项目已有的 hash 路由、React hooks 和外部订阅。

国际化是前端硬性要求：所有新增用户可见文案必须遵守
[docs/development/i18n.md](../../development/i18n.md)，不得在组件里新增硬编码中英文文案。

```
web/                        Vite 项目根
├── index.html
├── vite.config.ts          dev proxy: /api,/ws → :8080；build → dist（被 Go embed）
└── src/
    ├── main.tsx            挂载 + ConfigProvider(antd 主题)
    ├── App.tsx             路由表（react-router）
    ├── shell/
    │   └── AppShell.tsx     响应式骨架：按断点切换导航 + 布局（唯一感知"端"的组件）
    ├── api/
    │   ├── client.ts        axios/fetch 封装（带 Cookie，401 → 跳登录）
    │   ├── sse.ts           SSE 订阅 + 自动重连
    │   └── ws.ts            WS 封装（终端/日志，断线重连）
    ├── store/              全局状态（Zustand：sessions/tasks/auth；tasks 含命令+Agent）
    ├── hooks/              useBreakpoint / useSSE / useTerminal ...
    ├── components/         StatusBadge / TaskTable / LogViewer / Terminal / SpawnForm ...
    └── pages/             login / overview / tasks / sessions / env / settings
```

**技术点**：
- **React + Vite + TypeScript**，路由用 `react-router`，全局状态用轻量 `Zustand`（也可 Redux Toolkit）。
- **Antd** 提供 `Layout`、`Menu`、`Table`、`Form`、`Modal`、`Drawer`、`Tabs`、`Tag`、`Result` 等。
- 数据请求可配 `@tanstack/react-query`（缓存/重试），与 SSE 增量更新配合。

## 2. 响应式布局系统

> **本节已被 [13-mobile-responsive](./13-mobile-responsive.md) 取代。**
> 下面的三档方案是设计初稿，实现出来的是「散在 6 处的一个 `!screens.md` 布尔量」。
> 断点划分、令牌、导航形态与会话页布局一律以 13 为准；`large ≥ 1280` 的桌面形态见
> [14-desktop-workspace](./14-desktop-workspace.md)。

**断点**对齐 Antd `Grid.useBreakpoint()`：`xs<576 / sm / md768 / lg992 / xl1200 / xxl1600`。
实践三档：`mobile < md`、`tablet md–xl`、`desktop ≥ xl`。

`AppShell` 是唯一感知"端"的组件，用 `Grid.useBreakpoint()` 决定导航与内容容器：

```
mobile  : <主内容 全宽> + <BottomTabBar 固定底部>;  详情 = 全屏路由（带返回）
tablet  : <antd Layout.Sider 可收起> | <列表 + 详情 两栏>
desktop : <Sider 常驻>              | <列表> | <详情/终端>（三栏，可拖拽分隔）
```

```tsx
function AppShell({ children }) {
  const bp = Grid.useBreakpoint();
  const mode = bp.xl ? 'desktop' : bp.md ? 'tablet' : 'mobile';
  if (mode === 'mobile')  return <><Outlet/><BottomTabBar/></>;
  return <Layout><Sider collapsible={mode==='tablet'}/><MasterDetail/></Layout>;
}
```

- **导航组件**：`BottomTabBar`（手机，自定义或 antd-mobile `TabBar`）/ antd `Layout.Sider + Menu`
  （平板可收起、电脑常驻）共用同一份菜单数据。菜单项：
  **概览 / 任务(命令+Agent 合并) / 会话 / Env / 设置**（手机底部栏取前 4 项，Env+设置归「更多」）。
- **Master-Detail 模式**：列表与详情是同两个组件；手机用路由切全屏，宽屏用并排栏（URL 仍可深链）。
- **断点切换不丢状态**：旋转屏幕/改窗口尺寸时，选中项、滚动位置保持（状态存在 store + URL）。

## 3. 设计语言

- **主题**：Antd `ConfigProvider` 暗色算法为主（终端友好）+ 亮色可选，跟随系统 `prefers-color-scheme`。
- **配色**：状态语义色用 antd `Tag`/`Badge` — 🏃运行(processing 蓝) / ✅完成(success 绿) /
  ❌失败(error 红) / ⏸️空闲(default 灰)。
- **排版**：正文系统字体；终端/日志/命令用等宽字体。
- **触控**：手机端组件 `size="large"`，可点区 ≥ 44px；关键操作放底部"拇指区"。
- **桌面增强**：键盘快捷键（`g` 跳转、`/` 搜索、`n` 新建）、Antd `Dropdown` 右键菜单、Hover 态。
- **无障碍**：语义化、focus 可见、对比度 WCAG AA。

## 4. 状态与数据流

- `store`（Zustand）持有全局快照；订阅 `/api/stream/status`（SSE）增量更新，列表页"活的"无需手刷。
- 写操作 = 乐观更新 + API 调用 + 失败回滚 + antd `message`/`notification` 提示。
- 终端/日志走各自 WS hook，组件挂载时连接、卸载时断开。
- 全局 401 拦截（client.ts 响应拦截器）→ 跳登录页并记住来源 URL。

## 5. 终端组件

- `Terminal.tsx` 封装 **xterm.js**（`@xterm/xterm` + `@xterm/addon-fit`）：
  - 挂载即用 ws.ts 连 `/api/term/:name`，PTY ↔ xterm 双向。
  - `FitAddon` + `ResizeObserver` 自适应容器，resize 通过 WS 同步 PTY 列宽行高。
  - 手机端配套 `TermShortcutBar`（`Yes/No/Enter/Esc/Ctrl-C/↑/↓/Tab`），点击注入对应键序列。
  - 断线自动重连 + 状态指示。

## 6. 构建与集成

- `vite build` → `web/dist`，Go 侧 `//go:embed web/dist` 打进二进制（详见 [02-backend §5](./02-backend.md)）。
- 开发期 `vite.config.ts` 配 proxy：`/api`、`/ws` → `http://127.0.0.1:8080`，前后端分离热更新。
