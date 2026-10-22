# Agent Instructions

**This file is the single source of truth for agent rules in this repository** — Codex, Claude
Code, and anything else editing this repo. They are requirements, not suggestions.

Codex reads `AGENTS.md` directly; Claude Code reads [`CLAUDE.md`](CLAUDE.md), which is a thin
pointer that imports this file with `@AGENTS.md`. Add or change a rule **here**, never in a
tool-specific copy — two copies drift, and then the two agents work from different rulebooks.

# Design System

All Web UI work — layout, color, typography, spacing, component selection, UX behavior — must
follow the [Roami UI design specification](docs/development/ui-design-system.md). Read it before
designing or changing a screen: it defines dark/light colors, layout, dimensions, responsive
classes, desktop workspace behavior, and phone navigation and input rules. Use the
tokens it defines (`--fs-*` type, `--r-*` radius, `--sp-*` spacing, `--accent*` / `--ok*` accents)
and the existing antd/component patterns in `frontend/src/`. Don't invent a new color value, font
size, radius, or spacing step when a documented one already covers the role. Frontend structure
follows [`docs/design/web/04-frontend.md`](docs/design/web/04-frontend.md) unless a newer pattern
already exists in code.

## Keep UI Minimal

Page shells and adjacent layout modules use `--bg-base`, square edges, and no enclosing border,
shadow, or outer card margin. Separate adjacent modules with one `1px solid var(--border-subtle)`
line, owned by one side. This applies to every route, including Home, Files, Browser, Phone,
Projects, Plugins, and Settings. Reserve `--bg-container` and `--r-card` for independent content
cards and composers; controls use `--r-xs` / `--r-sm`, popups use the documented surface tokens.
Never wrap a whole page in a rounded card or use a different background to distinguish sibling
panes. Remote images, documents, and terminal canvases keep their content-specific colors.

UI must be concise. Show the content, current state, and actions needed for the next decision.
Use short, familiar wording: brief action verbs for buttons, direct labels, and one sentence for
routine hints. Keep implementation terms and logs in details; explain errors with a clear next
step. Preserve user input and choices instead of making users repeat work.
Remove repeated titles, obvious instructions, generic introductions, and redundant empty-state
explanations. Use one short empty-state message; hide zero-result counters and pagination when
there is only one page. Lists show identity and essential status; put full errors, revision
history, and technical details in the detail view or an explicit disclosure. Keep necessary
warnings, recovery actions, field labels, and accessible names. Do not replace visible clutter
with tooltip-only instructions on touch devices. Keep primary destinations such as Home tasks
visible and directly reachable; overflow menus hold secondary actions such as debug and memory.
Desktop Home actions belong in the right workspace header when it is open; avoid duplicate task
entries beside the workspace tabs. Phone top-bar task entries are icon buttons with accessible names.
Task lists show a short topic; keep full instructions in details. Task details show descriptions in three expandable lines,
with agent instructions collapsed by default. Put the verified outcome and usable deliverables before execution records. Executor claims never
override task or verification state. Main chat shows task progress and actionable blockers; tool
steps, routing explanations and internal IDs belong in execution records. Ended task details do
not poll; refresh them through events, navigation or explicit recovery actions.

Use existing automatic updates and mobile pull-to-refresh instead of a permanent refresh button
or a toolbar devoted to it. Desktop pages use browser refresh/F5; keep explicit recovery actions
where an error requires them.

## Mobile Material UI

All compact Web pages follow [`docs/development/mobile-material-ui.md`](docs/development/mobile-material-ui.md).
Open content-heavy views such as memories, background tasks, and notifications as full-screen
secondary pages on phones, using `MobileSubPage` or a dedicated route with one return bar and
one scroll container. Reserve dialogs for short confirmations and focused actions.
Keep the top app bar and bottom navigation consistent across routes; put Home, Projects, Tools,
and Settings in the bottom bar. Open messages from the top bar; Home's pending-work summary
opens Projects. A page must not repeat its
route title below the top bar. Secondary pages use one equal-height return bar and one scroll container; URL-backed pages must not also push overlay history. Use the existing design tokens for Material surfaces, type, space,
and state. Verify both bars, safe areas, page scrolling, and a real touch navigation pass on an
Android phone before calling mobile UI done.

## Tokens Only: No Raw Values

The ladders are fixed: type `--fs-micro/meta/sm/body/lg/title`, radius `--r-xs/sm/card/pill`,
spacing `--sp-1`…`--sp-5`, accent `--accent` / `--accent-solid` / `--accent-soft` /
`--accent-border`, success `--ok` / `--ok-solid` / `--ok-soft` / `--ok-border`.

NEVER hardcode a design value that has a token. No `#58a6ff` / `#3fb950` in components — there is
exactly one blue and one green site-wide, and antd's `darkAlgorithm` derives its own shade from
the seed, so a copied hex is always a step off what antd draws next to it. No off-ramp font sizes
(10.5 / 11.5 / 12.5), and nothing below 12px outside eyebrow/badge text.

Top-level pages use `.tt-pagehead` for their header; eyebrow and description are optional and
must add information beyond the title. Don't hand-roll a title row per page.

## Clickable Things Are Buttons

An `<a onClick>` with no `href` is not keyboard-focusable and looks like text — it fails both
discoverability and a11y. Row-end actions use the quiet ghost button `.tt-act` (bare border at
rest, brightens on hover, `.danger` / `.ok` modifiers for destructive and confirming actions).
Reach for `<button type="button">` by default; `<a>` only when it really navigates.

## Breakpoints: One Entry Point

`useLayout()` is the only way to read layout size. NEVER read `window.innerWidth` and never call
`matchMedia` yourself. Pure style differences key off `data-size` / `data-pointer` on `<html>`.
Under a coarse pointer, hit targets are ≥44px — grow the hit area with a pseudo-element, not the
visual size, and overshoot the gap between neighbouring icon buttons by 4px (3px still misses at
dpr 2.75).

## Hover Belongs to the Mouse

Every `:hover` rule is written `:where(html[data-pointer="fine"]) X:hover`. Touch has no
`mouseleave`, so a bare `:hover` sticks to the last thing a finger touched: the previously tapped
button stays lit and a row of buttons flickers as you work down it. `:where()` adds no
specificity, so the gate changes nothing about the cascade. Anything hidden until hover
(`opacity: 0` copy/close/download buttons) needs a coarse rule that keeps it visible, or the phone
can never reach it. `npm run hover:check` (`frontend/scripts/hover-scope-audit.mjs`) enforces both
halves and runs inside `npm run build`.

Tooltips are mouse furniture too: under a coarse pointer `.ant-tooltip` is hidden site-wide,
because a tooltip opened by a long press never gets a `mouseleave` and its overlay then eats the
next tap. An icon-only button therefore carries its name in `aria-label`, not only in a Tooltip.

## The Document Never Scrolls

`html, body { overflow: hidden }` — the app is a fixed-height shell and every page scrolls inside
its own container. One pixel of document overflow summons a 10px document scrollbar, which takes
10px off the workspace and slides the canvas and the terminal dock sideways; on a 150%-scaled
display the fractional rounding flips it back and forth with every burst of terminal output, and
buttons move out from under the cursor between mousedown and mouseup.

## Icons: SVG Only

NEVER add an emoji (🔄 📎 🤖 …), NEVER use a text symbol as an icon
(`✕ × ✓ ▾ ▸ ← → ↑ ↓ ⏎ ■ ● ◆ ⚠ ⎇ ⧉ ＋ …`), and NEVER draw a one-off inline SVG in a component.

- Icons come from `frontend/src/icons.tsx` (24×24 viewBox, `currentColor`, 1.8 stroke, round
  caps). `file-icons.tsx` and `git/parts.tsx` hold the file-type and Git sets in the same style;
  new icons default to `icons.tsx`.
- The same action uses the same icon everywhere. A close button that is `✕` in one place and `×`
  in another is worse than an ugly icon.
- Icons are NEVER baked into i18n strings (`'＋ Add task'`). Copy holds words only; the call site
  passes `icon={<PlusIcon />}`.
- Status dots and swatches are drawn (`border-radius:50%`, `<Swatch />`), not typed (`●`, `■`).
- Brand marks (`AgentLogo`: the Claude and OpenAI/Codex logos) are the one place our icon rules
  step aside. Use the official path data and the official color — `--brand-claude` /
  `--brand-codex` — never redraw a logo and never re-tint one to our accent. A brand mark also
  gets no chrome: render it bare (`.tt-agentmark`), not boxed in an `ant-tag`.
- Exactly two exceptions: keyboard-shortcut modifier glyphs (`⌘ ⇧ ⌃`), and the swarm office
  view's deliberate role-avatar emoji in `Swarm.tsx`.

Self-check: grep `frontend/src` for emoji and the symbol list above before finishing (comments and
TUI-output regexes don't count). A hit is something to fix.

## Internationalization

All new user-facing product text goes through the project i18n layer:
[`docs/development/i18n.md`](docs/development/i18n.md) is the standard. This covers labels,
buttons, placeholders, tooltips, empty states, validation messages, toast/message/notification
text, modal titles, table columns, navigation labels, status labels, browser page text, and
fallback HTML. Allowed exceptions are listed in the standard; if a change intentionally leaves
user-facing text untranslated, say why in the PR or task summary.

# Style

## Concise, Non-obvious Comments Only

- DO NOT be verbose, explain the obvious, or narrate the code. Comments say WHY, not HOW.
- BE CONCISE. One line where one line does.

## File and Module Naming

Never name a file, folder, or module `helpers`, `utils`, `common`, `misc`, or `shared`. Name it
after what it actually contains — the concrete domain concept (`session-identity.ts`,
`terminal-orphan-cleanup.ts`) over the generic role (`session-helpers.ts`, `term-utils.ts`). If
`helpers` feels right, the file probably has more than one responsibility.

## Design Documentation

New design proposals and their revisions are written as HTML directly in this `AGENTS.md`.
Do not create new design files under `docs/design/`. Each proposal includes Product Design,
User Stories, and Technical Design, including code and module architecture. Existing historical
design documents remain references; keep new decisions and acceptance evidence in the matching
HTML section here. Larger designs may be split into multiple HTML documents, referenced or embedded by one HTML entry point.

# Considerations

## The Phone Is a First-Class Client

Every UI change ships to a phone over LAN, not just a desktop browser. Typecheck is not
acceptance: run the real-device pass in
[`docs/development/web-ui-checklist.md`](docs/development/web-ui-checklist.md) before calling a
frontend change done. Touch behavior, coarse-pointer hit areas, and the compact `data-size` layout
are part of the change, not a follow-up.

Serving over LAN also means a secure context: `start.sh` turns on self-signed HTTPS by default
because microphone and clipboard access need it. Don't add a feature that silently degrades on
plain HTTP without saying so.

## tmux Is the Substrate

Sessions are real tmux sessions, and tmux has sharp edges the Go CLI already works around — match
the existing helpers instead of shelling out fresh:

- **Target names are prefix-matched.** Always pass `-t "=" + name`. Without the `=`, a session
  named `dev-review` keeps `dev` looking alive forever.
- **Sending to a TUI agent is not `send-keys text C-m`.** That types without submitting. Use
  `rt.SendPromptSubmit` (paste-buffer, then a separate Enter), which is also the only reliable
  path for multi-line prompts and bracketed-paste apps.
- **`send-keys` has a length limit.** Large prompts go to a file and in over stdin; if the send
  fails, kill the session you just created rather than leaking an empty one.

## Session CLI and Test Isolation

Use `roami session` for session operations and `roami chrome` for browser automation. The old
`ttmux` entry is retired. Public session commands do not forward native tmux commands or expose
global shutdown. Close only the explicitly identified session or task resources.

Run development instances through `scripts/dev/isolated-roami.sh <test-directory> <command...>`
and clean up their tmux server through the same entry with `--stop`. The launcher records a private
socket and verifies its server identity before cleanup. Setting only `TMUX_TMPDIR` does not isolate
an inherited `TMUX` target. Never use the user's live tmux server as a test fixture or cleanup target.
The session-isolation regression uses two disposable servers and proves the other server survives.

## Agent Panes Are Not Ours

Claude Code and Codex render their own alternate-screen TUIs inside our panes. Anything that
scrolls, resizes, or replays those panes has to account for alternate-screen mode (mouse-wheel
synthesis, not copy-mode) and for redraw quirks on narrow widths.

## Preferences Arrive Late

`usePreferences()` serves defaults until the `/preferences` GET lands, so the first render of any
component that seeds local state from a preference gets the *default*, not the stored value. Two
rules follow. Gate the one-shot hydration on `preferencesLoaded()`, never on "the effect has run
once" — that flag gets set on mount, before the real values exist, and the stored value is then
silently discarded forever (a dragged splitter kept writing `dockWidth` to disk and kept snapping
back to the default on every refresh). And for anything **visible** — widths, collapsed state —
mirror it to `localStorage` so the first paint is already correct; the server value stays the
authority, it just no longer moves the layout under the user a beat after load.

# Gates

## Refresh Budgets

Session state consumers reuse `useAgentKinds` / `useSessionOverview` rather than polling each
session. New polls pause when hidden, share in-flight requests, and back off after errors; use
`pollWhileVisible` for page-owned polling. Stable data keeps its reference — a new list object
must not restart an immediate request loop. Expensive repository counts refresh separately from
fast session state. Measure production builds before and after; request reduction is not a CPU
or memory reduction claim. Evidence and the next steps live in
[`docs/design/20261020-会话刷新负载/README.md`](docs/design/20261020-会话刷新负载/README.md).

## Quality

- Run `scripts/dev/quality/check.sh quick` before committing local changes.
- Run `scripts/dev/quality/check.sh full` before opening or updating a PR with runtime behavior
  changes.
- Frontend changes must additionally pass
  `npm run typecheck && npm run i18n:check && npm run hover:check && npx vitest run && npm run build`.
- Install the tracked Git hooks with `bash scripts/dev/install-git-hooks.sh`; it sets
  `core.hooksPath=.githooks` and `commit.template=.gitmessage`.
- Never commit `.env`, generated dependency folders, coverage output, or hard-coded secrets.

## Commit Convention

- Commit messages follow [Conventional Commits](docs/development/commit-convention.md):
  `<type>(<scope>): <描述>`.
- The `commit-msg` hook enforces the format locally. PR titles must follow it too — squash merges
  turn the title into the final commit.

## Pull Request 必须带截图

每个 PR 都要能**看**出来改了什么，不能只读得出来。文字描述由写的人挑角度，截图不会。

- **界面改动**：至少一张改后的截图；动的是既有界面就给改前 / 改后两张。手机档也受影响的，
  桌面与手机各一张——`data-size` 与粗指针那套差别恰恰是最容易漏的一类。
- **没有界面的改动**（后端 / CLI / 插件 / 脚本）：截能证明它真跑起来的那一屏——命令输出、
  日志、测试结果。
- **文档与规则类改动**：截「这条规则落地之后长什么样」。

放法：仓库是公开的，截图走 `pr-shots` 这条**孤儿分支**（只存图，永不并入 `main`），
正文里引 raw 链接。有脚本，别手搓：

```bash
scripts/dev/pr-shot.sh 253 menu-after.png      # 推图，并打印可直接粘的 markdown
```

```markdown
![改后：合成行的右键菜单](https://raw.githubusercontent.com/ybz21/Roam/pr-shots/pr-253/menu-after.png)
```

脚本用 git plumbing 写（独立索引 + `commit-tree`），不切分支、不碰工作区——截图不该逼你
把手里的活停下来；拉不到 `pr-shots` 时它宁可报错也不从空树重建（那样一推就把之前所有
PR 的图抹了）。

截图不要提交进 `main`：仓库里不留 PR 的一次性产物。

## Code Review

- PRs are reviewed by the **Codex GitHub App** (`chatgpt-codex-connector` bot). See
  [docs/development/codex-review.md](docs/development/codex-review.md) for how it is enabled and
  how to respond.
- The `babysit-pr` skill (`skills/babysit-pr/`) automates polling, deciding fix-vs-skip, replying,
  and resolving Codex review threads.

<section id="capabilities-hub-design" lang="zh-CN">
  <h1>能力中心设计 · 2026-10-21</h1>
  <p>基线为本次 main 快照 a9cfaa6。目标是交付能真实管理、持久保存并被 Agent 调用的首版能力中心。</p>

  <h2 id="capability-product-design">1. 产品设计</h2>
  <div id="capability-prototype-embed">
    <h3>交互原型</h3>
    <p>原型复用实际能力页组件。运行 <code>cd frontend &amp;&amp; npm run design:capabilities</code> 生成含原型的单文件设计 HTML，默认输出到 /tmp/capabilities-design.html。</p>
    <p><a href="/api/file/serve/tmp/capabilities-design.html">打开设计与原型</a> · <a href="/api/file/serve/tmp/capabilities-prototype.html">单独打开原型</a></p>
    <iframe src="/api/file/serve/tmp/capabilities-prototype.html" title="能力中心交互原型" width="100%" height="760" loading="lazy" sandbox="allow-scripts allow-forms allow-downloads"></iframe>
    <p>原型使用隔离的示例数据，可操作上传、新建、编辑和保存；不访问真实业务接口。</p>
  </div>
  <h3>信息架构与页面</h3>
  <p>导航中的“插件”升级为“能力”。页面设 Agent、插件、Skill、MCP、CLI、基础工具六个 Tab，默认打开 Agent。
    设置中的 Agent 能力管理整体迁入；内置 Agent 的模型、运行时、消息、记忆配置仍归设置；Claude Code、Codex、OpenCode、Pi 的管理迁入 Agent Tab。
    旧 settings/agent/bin 及其 Agent 深链映射到 capabilities/agents；旧插件深链和 settings/agent 下的 skills、cli、mcp、tools、capabilities 深链映射到新页面。</p>
  <p>桌面使用统一页头、分类 Tab 与搜索目录。插件与其他分类统一采用独立能力卡片，展示图标、名称、来源、
    简短描述和真实状态；查看与编辑在卡片底部直接可见。详细指令、参数与配置按需打开。页面壳与相邻模块同底、直角，以单条细线分隔。
    手机从“工具”进入能力，保留首页、项目、工具、设置四个主入口；长详情、创建和导入使用全屏二级页，
    只有一层返回栏和一个滚动容器，输入与提交避让键盘。
    编辑表单的保存栏位于字段滚动区外，键盘留白只由 MobileSubPage 处理。</p>
  <h3>创建、导入与配置</h3>
  <ul>
    <li>Agent：Claude Code、Codex、OpenCode、Pi 使用品牌卡片，展示安装、登录确认状态与可用额度。安装和更新沿用已有白名单接口；“检查”显式读取版本和程序位置，自动刷新不执行 CLI。管理详情可保存启动命令（包括模型参数），打开已有会话终端完成登录与模型选择。安装成功不代表已登录；没有可靠证据时显示“登录待确认”。</li>
    <li>插件：卡片展示来源、名称、版本、描述与启停开关，提供“查看详情”和“配置”入口；桌面按需打开详情弹窗，手机使用全屏二级页。配置入口直接进入表单；保留插件包上传、本地目录安装、内置插件恢复、命令、权限与审计。旧深链直接打开对应详情，返回沿用 URL 历史。</li>
    <li>Skill：点击“创建 Skill”填写名称、描述与 Markdown 指令，可从发布检查模板开始并切换预览；点击“上传文件”选择或拖入 SKILL.md，也可粘贴内容。读取后先解析名称与描述，进入可编辑确认页，再点“确认导入”。</li>
    <li>MCP：点击“添加 MCP”选择远程服务地址或本地程序；也可上传单个配置或 mcpServers JSON，解析后编辑确认。
      配置保存后显示“未连接”，显式连接才启动进程或访问服务，按真实发现结果显示连接状态与工具数量。</li>
    <li>CLI：点击“注册 CLI”填写程序、参数数组和可选工作目录，或上传 JSON 后编辑确认；参数中的 {input} 代表调用参数 JSON。
      复用运行时的工作目录边界与进程管理，不隐式调用 shell。</li>
    <li>基础工具：保留内置工具参数与读写属性查看，固定工具不可编辑或关闭。</li>
  </ul>
  <p>卡片上的“编辑”直接打开同一份表单，预填已有内容，名称固定；用户可修改描述、指令或连接配置，并点击“保存更改”。托管能力支持移除；Skill 和 CLI 沿用启停策略。重复名称明确报错，普通导入不覆盖旧配置。
    编辑保留名称，批量 MCP 先全部验证再原子保存。失败保留输入，给出可读的纠正提示。
    MCP 凭证使用 env_env、header_env、key_env 引用环境变量，不接受或回显明文凭证。
    本版外部导入指文件上传或粘贴配置；不把未实现的在线市场、仓库下载或 OAuth 授权显示为可用功能。</p>

  <h2 id="capability-user-stories">2. 用户故事</h2>
  <ol>
    <li>作为专业 Agent 用户，我能在能力页找到 Claude Code 和 Codex，安装或更新、检查版本、保存启动命令，并进入终端完成登录和模型选择。旧设置链接继续有效，保存失败保留输入，偏好加载完成前不会用默认命令覆盖已有配置。</li>
    <li>作为已有插件用户，我从“能力 / 插件”继续配置定时任务，旧状态条链接仍能选中原插件。</li>
    <li>作为 Agent 用户，我不用在设置和插件页之间寻找工具；分类地址可以分享、刷新，并跟随浏览器返回。</li>
    <li>作为流程维护者，我上传 SKILL.md，确认名称和内容后保存；立即可在目录找到，重启后仍存在。
      重名时收到提示，我的输入不会清空，必须显式编辑才能替换。</li>
    <li>作为外部服务用户，我粘贴 MCP 配置后先登记，再点连接查看真实结果；连接失败可修正配置并重试。</li>
    <li>作为命令行用户，我登记程序和参数，Agent 在已有工作目录约束内调用；停用后旧调用也被阻止。</li>
    <li>作为手机用户，我能通过真实触控完成分类切换、查看、创建和返回，键盘不会遮住保存按钮。</li>
    <li>作为管理员，我移除自行创建的能力后，它立即退出目录；内置能力保持只读，移除失败不伪报成功。</li>
  </ol>

  <h2 id="capability-technical-design">3. 技术设计</h2>
  <h3>代码架构</h3>
  <pre>frontend/src/components/capabilities/
  CapabilitiesPage.tsx    页面壳、URL 分类与插件面板整合
  AgentCatalog.tsx        Agent 卡片、按需检查、URL 详情、启动命令和会话入口
  AgentBalance.tsx        额度窗口与过期快照处理
  agents.css              品牌、状态、额度与管理表单布局
  CapabilityCatalog.tsx   目录查询、过滤、启停与详情
  CapabilityEditor.tsx    创建、文件导入、校验及保存
  capability-format.ts   SKILL.md / JSON 的输入解析
  capabilities.css       令牌、响应式、粗指针命中区
frontend/src/components/plugins/
  PluginsPanel.tsx        插件卡片、URL 详情、安装与清单驱动配置
  plugins.css             插件身份、详情布局；卡片复用能力目录样式
internal/agentinventory/
  professional.go         默认 CLI 安装发现、显式有界版本探测、已有安装白名单
backend/api/
  professional-agents.go  已有状态 / 安装和新增检查接口
internal/cli/plugin/
  plugin.go               按字段声明与权限声明完整打码插件秘密配置
agent-runtime/src/roami_agent/server/
  capability_imports.py  托管注册、验证、私有文件持久化、运行时安装与移除
  capability_settings.py 统一目录与现有启停策略
  http.py                所有者校验、请求大小限制和 REST 入口
agent-runtime/src/roami_agent/tools/
  mcp.py                 惰性连接、动态发现、已有连接生命周期
  shell.py               复用工作目录边界、凭证过滤、取消与产物外置</pre>
  <h3>模块与数据流</h3>
  <pre>能力页 → 节点感知 api() → Go 登录网关 → 私有 Agent HTTP
  → CapabilityImports（验证、名称冲突、原子保存）
  → Tools.skills / Tools.registry / MCPConnections
  → CapabilitySettings.view（目录、托管配置、真实状态）
  → 已有 read / bash / tool_list 调用路径</pre>
  <p>托管数据保存在当前节点 data_root/agents/capability-imports.json，文件权限 0600，父目录 0700。
    临时文件写入、fsync 后原子 replace；落盘成功后更新内存，失败保持原目录。启动时验证并恢复托管项。
    注册和移除串行化，与启停策略共享互斥；MCP 存在正在执行或排队请求时拒绝改配和移除，避免截断调用。</p>
  <p>插件沿用已有 /plugins 与 /plugin 接口，通过 Go 网关访问插件管理器，不重复登记为 Skill。目录只加载身份和状态，按需打开详情才读取配置；配置表单由 manifest 字段生成，秘密字段按 manifest.configFields.secret 或 permissions.secrets 完整打码，表单只提交用户改动项。配置读取失败时阻止编辑并提供重试，安装成功后返回目录，不再另开命令日志弹窗。卡片打开详情写入分类 URL，手机详情不额外压入 overlay history。</p>
  <p>Agent 目录复用 /agent/professional 和节点偏好。页面仅一个可见性控制的轮询，错误退避且保留最近快照；安装、版本检查按需执行。版本检查只允许运行已注册 Agent 的默认程序和固定 --version 参数，3 秒超时、输出上限 4 KiB。新窗口不会自动启动 CLI，也不会把本地凭证返回给前端。专业 CLI 的 Skill / MCP 配置继续由各自管理，不声称 Roami 托管能力已自动绑定到它们。</p>
  <h3>接口与边界</h3>
  <ul>
    <li>GET /api/agent/capability-settings：目录、来源、可变标记、托管配置与 MCP 状态。</li>
    <li>PUT /api/agent/capability-settings：现有 Skill / 工具启停策略，内置项仍拒绝修改。</li>
    <li>POST /api/agent/capability-imports/{skills|cli|mcp}：创建或导入，MCP 支持原子批量登记。</li>
    <li>PUT、DELETE /api/agent/capability-imports/{kind}/{name}：编辑或移除托管项，名称不能暗中改变。</li>
    <li>POST /api/agent/capability-imports/mcp/{name}/connect：显式连接并发现工具，超时或失败不报告连接成功。</li>
  </ul>
  <p>每次导入请求最多 64 KiB，持久目录最多 1 MiB，每类最多 64 个托管项，MCP 沿用最多 16 个服务限制。
    名称只接受小写字母开头的短标识；JSON Schema 禁止外部引用。
    CLI 参数按 argv 传递，{input} 只做单个参数内替换；执行仍经过既有 Agent 上下文与 shell 权限边界。
    不增加常驻轮询，目录在进入分类或成功变更后更新，插件原有状态刷新遵守页面可见性规则。</p>
  <h3>验证计划与交付边界</h3>
  <p>自动验证覆盖所有者隔离、格式与体积限制、重名与批量原子性、内置保护、落盘失败、重启恢复、
    Skill / CLI 真实调用、启停与移除、MCP 惰性注册和真实发现。界面覆盖旧地址迁移、分类、创建 / 导入和失败保留输入。
    交付前运行前后端质量门禁，并在桌面浏览器和 Android 真机检查导航、触控命中、滚动、键盘、安全区及无横向溢出。
    此次交付为可审阅的开发版本，不自动发布到用户正在使用的服务或外部托管平台。</p>
  <h3>原型与交互修订 · 2026-10-21</h3>
  <p>设计 HTML 默认打开交互原型，并可切换桌面 / 手机、深浅主题与中英文。
    原型通过构建脚本将真实页面组件、样式和示例目录打包成单文件，再内嵌到总 HTML 中。
    iframe 使用 sandbox 隔离来源，示例 API 完全在页面内处理，不访问真实配置或业务接口。
    原型入口为 frontend/prototypes/capabilities.tsx，示例目录为 capability-catalog.ts，构建入口为 frontend/scripts/build-capability-design.mjs。</p>
  <p>新建：按当前分类分别显示“创建 Skill / 添加 MCP / 注册 CLI”，直接填写有示例的表单；Skill 提供模板与 Markdown 预览。
    上传：选择或拖入文件后立即解析，再进入可编辑的确认页；也支持粘贴文件内容。
    编辑：卡片底部直接显示“编辑”，预填现有配置，名称固定，点击“保存更改”提交。</p>
  <h3>验收记录 · 2026-10-21</h3>
  <ul>
    <li>仓库 quick / full 质量门禁通过；Go 测试通过。最终前端 120 个测试文件、843 个用例通过，Agent 运行时 744 个用例通过。</li>
    <li>真实 SKILL.md 文件上传通过，兼容折叠描述与超过 20 位的 Skill 名称；重名失败保留输入。
    </li>
    <li>typecheck、i18n:check、hover:check、生产构建通过。构建仍有现有大块体积提示，不影响本次交付。</li>
    <li>桌面检查 320、390、820、1100、1280、1600、1920 宽度，分类内容独立滚动，无横向或文档滚动；中文深色与英文浅色均检查。</li>
    <li>Redmi Note 8 真机以 coarse 指针完成分类切换、创建、刷新恢复、文件内容导入、旧地址迁移、CLI 手势滚动及四个底部主入口点按。</li>
    <li>真机键盘高度 314px 时保存按钮仍位于键盘上方，可真实点按，按钮高度 44px；保存后回到列表，导航恢复。</li>
    <li>独立 MCP stdio 测试服务通过页面真实连接并发现 6 个工具；托管配置与运行目录与现用 Roami 实例隔离。</li>
    <li>本轮原型在桌面和 Android 上均验证模板新建、卡片编辑、真实文件上传后修改并保存、MCP 新建，以及 HTML 内章节 / 视口 / 主题 / 语言切换。</li>
    <li>插件卡片在桌面与 Redmi Note 8 上完成搜索、启停、配置保存后重新打开、插件包上传、卸载与内置恢复；7 个新增交互测试覆盖配置失败保留输入、秘密掩码不回写和 URL 详情返回。</li>
    <li>当前工作树构建的 Go 服务和 Python 运行时完成真实插件包上传、密码字段打码与配置保存、exec 插件命令执行、Skill 文件导入与编辑、CLI 注册和启停、MCP 本地进程发现 6 个工具；使用独立数据目录和 tmux 服务。</li>
    <li>Agent 页通过桌面与 Redmi Note 8 真机触控验收：版本检查、命令保存及刷新恢复、旧地址迁移、返回、更新确认和打开终端。真实 Go / Python / tmux 链路运行在隔离实例，CLI 与 npm 使用固定测试程序，验证保存的模型参数确实进入新终端，不安装或更新本机现有 Agent。</li>
    <li>所有截图与临时验收脚本位于 /tmp，不进入主分支；当前开发代码位于 feat/capabilities-hub。</li>
  </ul>
</section>

<section id="skill-cli-organization-review" lang="zh-CN">
  <h1>Skill 与 CLI 职责整理 · 2026-10-21</h1>
  <p>状态：已实施。两个内置 Skill、公开 CLI 命令族、受管适配与旧路径兼容已经落地；验收使用独立数据目录和 tmux 服务。</p>

  <h2>1. 评审发现</h2>
  <ul>
    <li>浏览器职责交叉：roami-dispatch 的 description、决策说明和 references/chrome.md 覆盖网页操作；web-research 又维护检索流程。
      WORKER_INSTRUCTIONS 同时重复浏览器操作名、参数和检索步骤，修改一处不能保证其他入口一致。</li>
    <li>委派示例漂移：两个 Skill 的入口及 Chrome 手册仍示例 delegate(executor="native", ...)，
      但 tools/registry.py 的 Main 目录已经隐藏顶层 executor 并要求 routing；projects-sessions.md 则已使用新格式。</li>
    <li>事实过期：projects-sessions.md 声称未知 session 命令透传 tmux，internal/cli/app.go 已明确拒绝；
      capabilities.md 声称上传导入尚为预留，而 capability_imports.py 和能力页已实现。</li>
    <li>重命名涉及代码：research 角色在 tools/foundations.py、tools/registry.py、protocol/research.py 中只允许 web-research，
      可用性检查、系统提示、前端翻译和测试也引用旧名。只移动目录会导致研究任务无法发现或读取 Skill。</li>
    <li>CLI 目录暴露了内部操作：CapabilitySettings.view 的 cli 来自 ToolDirectory.groups，前端又用 flatMap 将组展开，
      因而 browser_open / browser_observe / browser_act 各自成为一张卡片。它们实际复用同一个 roami chrome 驱动，
      不应被展示或发现为三套独立 CLI。应以真实命令族组织目录，浏览器只保留 roami chrome 一个入口。</li>
  </ul>

  <h2>2. 产品设计</h2>
  <p>保留两个内置 Skill：roami 负责 Roami 基础使用，browser_use 负责浏览器使用。网页检索归入 browser_use，
    原 web-research 不再作为第三个独立目录项。browser_use 沿用需求指定名称；当前内置加载器与托管名称校验均支持下划线。</p>
  <table>
    <thead><tr><th>入口</th><th>负责内容</th><th>边界</th></tr></thead>
    <tbody>
      <tr><td>Skill：roami</td><td>项目、会话、委派、后台进度、记忆、文件与节点操作；按需读取专题手册。</td>
        <td>遇到浏览器任务只指向 browser_use；不再维护浏览器参数和操作步骤。</td></tr>
      <tr><td>Skill：browser_use</td><td>导航、观察、交互、网页检索、截图、录屏和交付；说明当前角色可走的执行路径。</td>
        <td>使用 roami chrome 驱动；研究角色仍仅能导航和观察，不能因读取通用 Skill 获得交互或 Shell 权限。</td></tr>
      <tr><td>CLI：roami chrome</td><td>浏览器唯一命令族入口，关联 browser_use；子命令通过 roami chrome help 按需发现。</td>
        <td>不再分别展示或向模型发现 browser_open / browser_observe / browser_act；权限、资源与回执由宿主适配层处理。</td></tr>
      <tr><td>其他 CLI</td><td>按真实可执行程序和命令族登记；外部 CLI 沿用注册的程序与参数。</td>
        <td>逐项核对其与基础工具、roami Skill 的关系；内部函数名不直接当成独立 CLI 产品入口。</td></tr>
      <tr><td>系统提示</td><td>角色、路由、授权、真实状态与未知写结果处理等持续适用的约束，以及 Skill 入口。</td>
        <td>移出重复命令表和任务流程；不可只靠可选 Skill 承载强制权限边界。</td></tr>
    </tbody>
  </table>
  <p>能力页保留 Skill / CLI 分类。Skill 展示 roami 与 browser_use；CLI 中浏览器只展示一张 roami chrome 卡片，
    说明其用途并关联 browser_use。详情按需查看子命令；不把子命令平铺成独立能力卡片。
    同步 Agent 的 tool_list 目录，让用户与模型看到相同的命令族组织，不能只在页面上把三个旧操作合成一张卡片。</p>

  <h2>3. 用户故事</h2>
  <ol>
    <li>查询项目或继续已有会话时，Agent 读取 roami 后即可找到相应流程，不加载浏览器手册。</li>
    <li>浏览、检索或截图时，Agent 发现 browser_use；公开查询读取检索规范，交互任务读取操作规范，均使用既有 Chrome 驱动。</li>
    <li>原生 Worker 与专业 Agent 均按 browser_use 使用 roami chrome 子命令；宿主按角色绑定任务资源与执行权限，不要求模型学习第二套 browser_* 命令。</li>
    <li>CLI 目录只看到 roami chrome 一个浏览器入口，通过 browser_use 学会用法，通过命令帮助了解参数，不在多张卡片间寻找同一浏览器能力。</li>
    <li>旧对话读取旧 Skill 路径仍能到达对应规范；能力目录只展示两个正式 Skill。</li>
  </ol>

  <h2>4. 技术设计</h2>
  <h3>模块与代码结构</h3>
  <pre>agent-runtime/src/roami_agent/skills/
  roami/
    SKILL.md                       基础入口与专题索引
    references/projects-sessions.md
    references/agent-tasks.md
    references/capabilities.md
    references/node-operations.md
  browser_use/
    SKILL.md                       工作流与角色选择、必要约束
    references/research.md         来源、时间、检索范围与证据限制
    references/managed-browser.md  当前角色限制、观察与资源恢复
    references/chrome-cli.md       专业 Agent 的目标选择、截图与录屏惯例</pre>
  <p>roami 保留原基础专题并删除过期事实。将原 Chrome 手册迁入 browser_use，检索内容合并自 web-research；
    入口只索引当前任务需要的参考文档。参数以注册 schema 和 roami chrome help 为准，参考文档保留必要示例和非显然约束，避免复制完整帮助。</p>
  <pre>Skill：browser_use → CLI：roami chrome &lt;子命令&gt;
原生任务：bash argv → 宿主命令解析与角色校验 → 任务资源适配 → 既有 Chrome 驱动
专业 Agent：终端 argv → roami chrome → 真实页面与本地文件
内部实现：按需复用 open / observe / act 处理函数，不作为独立 CLI 发布</pre>
  <p>这同时调整目录与模型调用入口。原生 bash 目前拒绝直接执行 roami chrome，因此实施时要增加命令族适配，
    解析真实 argv 后复用受管处理逻辑；不是简单放开通用 Shell，也不是另造一个 browser_use 执行程序。
    宿主继续执行 research 导航限制、task/run 绑定、资源租约、停止与未知结果对账。
    子命令及 flags 以现有 roami chrome help 和驱动契约为准；不支持的操作明确拒绝，不能静默走不受管执行。</p>
  <h3>迁移范围与兼容</h3>
  <ol>
    <li>统一内置名称与旧名解析：roami-dispatch → roami，web-research → browser_use；
      旧 roami-dispatch/references/chrome.md 单独映射到 browser_use/references/chrome-cli.md。
      别名不注册成额外 Skill，目录和 tool_list 只展示正式名称；不重写历史执行记录。</li>
    <li>在实际读取与权限校验前统一解析旧路径；research 仅允许 browser_use 及其参考文档，执行限制仍由 protocol/research.py 校验。
      旧名与外部配置冲突时显式报错，不静默把用户 Skill 重定向到内置内容。</li>
    <li>同步 tools/skills.py、foundations.py、registry.py、web_research.py、protocol/research.py 与 server/configuration.py 的名称、发现提示、可用性和兼容路径。
      旧 web_research 兼容调用与正常目录的隐藏规则保持既有行为，不混同 Skill 重命名与接口删除。</li>
    <li>分离内部操作注册表与公开 CLI 目录：为真实程序 / 命令族建立目录映射，浏览器仅输出 roami chrome，关联 browser_use；
      tools/foundations.py 的 list 与 groups、CapabilitySettings.view、前端目录共同采用这一粒度。
      内部 browser_* 处理函数按需复用；旧调用若保留兼容，不再作为正常目录项展示。</li>
    <li>为原生 bash 增加 roami chrome 命令族的受管适配，统一角色准入、task/run 绑定、观察与回执；
      研究任务禁止交互的限制由代码执行。同步系统提示、Skill 与发现结果，模型只学习真实的 roami chrome 子命令。</li>
    <li>逐项评审 artifact_read、executor_catalog、capability_overview 等条目：属于基础 read 的能力归基础工具，
      属于 Roami 管理的操作按实际命令族归类；没有真实 CLI 对应的内部操作不冒充独立程序，也不凭名称臆造命令。</li>
    <li>同步 CapabilityCatalog、AgentComposerPlus、中英文翻译和测试引用，更新 CLI 命令族详情与 Skill 关联，使用现有布局组件。</li>
  </ol>
  <h3>全部 CLI 条目复核 · 2026-10-21</h3>
  <p>结论：其余内置条目也应按职责收回，公开 CLI 默认保留 roami 与 roami chrome 两个入口，分别关联 roami、browser_use。
    roami 详情按 project、session、agent 等真实子命令组织；chrome 为浏览器专用命令族。
    用户注册的外部 CLI 独立保留。不是给每个内部函数再造一个新名字，也不是删除其业务能力。</p>
  <table>
    <thead><tr><th>现有条目</th><th>建议归属</th><th>源码核对与迁移条件</th></tr></thead>
    <tbody>
      <tr><td>artifact_read</td><td>基础 read，移出 CLI 目录。</td>
        <td>foundations.resolve 已将 read 的 artifact:// 路径转给 artifact_read；保留分页、所有者与已遗忘来源检查。</td></tr>
      <tr><td>capability_overview</td><td>tool_list 的目录摘要或宿主提供的运行状态，移出独立 CLI 条目。</td>
        <td>普通 tool_list 已提供分类总数与当前角色范围，但 overview 还包含后台能力可用性；迁移需保留按角色区分的可用状态，不能直接删掉该信息。</td></tr>
      <tr><td>executor_catalog</td><td>roami 的 agent execution 专题。</td>
        <td>真实命令 roami agent execution catalog 已存在。内部仍保留安装探测，不将安装状态当成登录、额度或能力证明。</td></tr>
      <tr><td>workspace_overview、target_search、target_resolve</td><td>roami 的项目 / 会话专题。</td>
        <td>project ls/show/sessions 与 session ls/resolve 已存在；跨类型搜索、完整分页和汇总计数不全等价。
          保留这些语义并补齐适配，不能改成数摘要卡片或只读第一页。</td></tr>
      <tr><td>session_send、session_dispatch_status</td><td>roami 的会话投递与回报专题。</td>
        <td>session send 与 agent reply 已存在，但普通 send 不等于带 dispatchId、回报通道的受管投递。
          需保留原 Main 回报关联与状态查询；先保证命令族具备等价能力，再撤掉独立操作入口。</td></tr>
      <tr><td>task_status、task_cancel、task_steer</td><td>roami 的 Agent 任务专题。</td>
        <td>agent steer 已存在；agent execution status/cancel 操作的是专业执行器 launch key，不能替代基于 taskId 的完整任务生命周期。
          需补齐真实任务查询 / 取消命令，并保持 revision、停止证明与未知状态对账。</td></tr>
      <tr><td>reminder_create、reminder_list、reminder_cancel</td><td>roami 的 agent reminder 专题。</td>
        <td>真实命令 roami agent reminder add/ls/cancel 已存在；宿主补入会话、稳定请求键及默认时区，保留 daily_brief 分支与真实投递状态。</td></tr>
      <tr><td>memory_search、memory_get</td><td>roami 的记忆专题。</td>
        <td>当前没有专用记忆 CLI，只有受管 capability call。先实现对应真实子命令或等价命令族适配，保留用户范围、来源、分页与遗忘约束；方案中的归属不代表已有命令。</td></tr>
      <tr><td>browser_open、browser_observe、browser_act</td><td>一个 roami chrome CLI 入口，关联 browser_use。</td>
        <td>复用 Chrome 驱动与受管处理，按前述方案统一原生 argv 路径、资源与角色限制。</td></tr>
      <tr><td>computer_open、computer_observe、computer_act</td><td>桌面资源操作，收回 CLI 分类。</td>
        <td>当前是 Python DesktopDriver，未提供 roami computer 之类真实命令；保留按需发现和调用途径，完善资源类别后迁移，不虚构 CLI，也不并入浏览器。</td></tr>
      <tr><td>mcp_discover、mcp_* 动态工具</td><td>保持 MCP 分类，不在 CLI 中重复展示。</td>
        <td>tool_list 已按 mcp_ 前缀分类，前端 CLI 也已过滤；迁移需继续支持发现、真实 schema 和按服务调用。</td></tr>
      <tr><td>http_* 外部接口</td><td>外部接口 / 工具，收回 CLI 分类。</td>
        <td>worker_catalog 直接使用 httpx 请求配置端点，属于 HTTP 集成。保留连接配置、凭证注入、schema 与启停策略，完善按需发现分类后迁移。</td></tr>
      <tr><td>cli_* 用户注册项</td><td>继续作为外部 CLI。</td>
        <td>capability_imports 注册真实程序与 argv；保留注册名称、工作目录、参数模板、启停和移除，不因归并内置操作而隐藏用户注册。</td></tr>
    </tbody>
  </table>
  <p>基础 file_read/file_write/file_patch/shell/skill_read 与旧 web_research 在正常 CLI 目录中已经被过滤，继续由 read/write/edit/bash 与 browser_use 承接，不新增重复项。
    delegate、ask_user 保持基础工具；任务委派不能被退化成新建 tmux 会话。</p>
  <p>迁移顺序：先明确公开目录与内部操作注册表的区别，再补齐缺失的真实子命令和受管适配，随后同步 tool_list、能力页与 Skill。
    对暂不具备等价入口的任务、记忆和桌面能力，先保留可达路径再迁移；验收必须覆盖功能可达性与原有授权边界，不能只比较卡片数量。</p>
  <h3>验收条件与顺序</h3>
  <p>先建立公开命令族与内部操作的映射、受管 argv 适配和角色回归，再合并 Skill、兼容旧路径并同步前端。
    验证 Skill 有两个正式内置项；CLI 页面和 tool_list 均只有一个浏览器入口 roami chrome，不再平铺 browser_*；
    新旧 Skill 路径可读取正确内容，旧 Chrome 路径不能让 research 读取 roami 运维文档；
    research 通过 roami chrome 可导航观察、不可交互或执行通用 Shell；普通 Worker 的交互和专业 Agent 的 roami chrome 路径继续有效。
    验证检索、截图交付、会话继续、未知动作恢复，并检查中英文 Skill 展示。
    实施后运行相应运行时回归与仓库质量门禁；前端改动执行前端门禁与桌面、Android 真机验收。</p>
  <h3>实施与验收记录</h3>
  <ul>
    <li>命令路径单一来源为 roami_agent/commands.json，Go 使用 agent-runtime/commands.go 嵌入相同文件；Python command_families.py 将真实 argv 解析为既有受管操作，内部处理器和回执语义保持可复用。</li>
    <li>模型与能力页公开 roami、roami chrome 两个内置 CLI；HTTP 与桌面操作归工具，MCP 独立输出 mcpTools；外部 CLI 包括停用项继续显示，可重新启用。</li>
    <li>新增任务、记忆、目标查询等命令族 --input 入口；原生任务由宿主拦截执行，真实终端调用同样要求运行中的 Agent 工具上下文。浏览器的 --resource / --observation 形式使用现有任务资源和观察身份，未开放任意 Chrome flags。</li>
    <li>roami 与 browser_use 为正式 Skill；旧名称及旧 Chrome 手册路径可读取，研究角色仍不能读取 Roami 运维手册、点击表单、占用用户标签或执行 Shell。</li>
    <li>仓库 full 质量门禁通过，包含 Go 全量测试、Python 756 个用例、国际化、hover、类型检查及生产构建；前端额外运行 123 个测试文件、873 个用例通过。构建保留已有大块体积提示。</li>
    <li>新 Chrome 命令通过完整任务链路完成表单填写与保存，并验证四条持久动作回执；命名记忆与任务命令通过真实运行时调用。wheel 检查确认包含命令 JSON 及两个 Skill。</li>
    <li>桌面 320、390、820、1100、1280、1600、1920 宽度均无文档或横向溢出；桌面与 Redmi Note 8 真机验证 CLI / Skill 分类、唯一命令族、指南展开、触摸滚动、单返回栏及返回；手机实测 392 CSS px、coarse 指针，上下栏正常，无文档或横向溢出。</li>
    <li>改前截图使用本分支 HEAD 的原始运行时目录数据在相同页面重放；改后截图来自当前 Go 网关和 Python 运行时的隔离实例，未修改现用节点。截图、验收脚本与日志均位于 /tmp。</li>
  </ul>
</section>

<section id="browser-tab-pool-design" lang="zh-CN">
  <h1>浏览器标签池与回收 · 2026-10-21</h1>
  <h2>产品设计</h2>
  <p>Agent 新建的标签页按浏览器实例共享最多 20 页；用户自行打开或仅被 Agent 借用的页面不进入回收池。
    任务释放页面后保留 10 分钟供查看结果，空闲超时自动关闭；容量不足时按最早空闲顺序提前回收。
    活跃任务、人工接管、未知动作及当前前台页面不被自动关闭。全部页面受保护时明确报告容量不足，不抢占任务。</p>
  <h2>用户故事</h2>
  <ul>
    <li>作为用户，我能让多个检索任务使用最多 20 个 Agent 标签页，不会因旧的每任务 3 页预算过早失败。</li>
    <li>作为用户，我完成检索后仍能短暂查看页面；无人使用的结果页随后自动释放浏览器内存。</li>
    <li>作为正在接管页面的用户，我的页面保持打开；后台回收不能切换焦点或关闭我的其他标签页。</li>
    <li>作为服务维护者，我重启 Agent 后仍能核对旧页面和关闭回执，避免重复关闭或按变化后的标签序号误操作。</li>
  </ul>
  <h2>技术设计</h2>
  <pre>protocol/browser.py             默认 max_tabs=20，允许 1..20；idle_timeout_seconds 默认 600
storage migration               持久 browser_tabs，记录来源、使用/空闲时间和关闭操作回执
executors/browser_tabs.py        浏览器实例内的容量核对、空闲 LRU、关闭及重启恢复
executors/browser_driver.py      创建时持有浏览器 context 租约并登记新页；定时触发回收
 dispatch/resource_leases.py      获得/释放控制权时更新使用与空闲时间；关闭中不可重新认领
browser/automation/driver.mjs    精确 targetId + browserId 关闭；回收专用后台页检查，不抢焦点</pre>
  <p>仅成功创建回执确认的 target 加入池；旧版本页面从成功创建回执补登记，不按页面 URL 猜所有权。
    并发创建通过现有 context 租约串行，计数覆盖全部任务的托管页面。关闭前在同一数据库事务中验证空闲、无绑定、无未知动作且未接管，
    写入关闭中的隔离状态和唯一 operationId，再执行带持久回执的无重试关闭。页面已消失只清账；身份变化不对另一实例发送旧关闭。
    关闭结果未知时保留隔离，后续只核对原回执和稳定 target 是否存在，不重新发送关闭。已知失败退避后再评估。
    标签池未变化时，重复满额开页沿用持久失败记录结束重试；释放并回收出容量后允许继续。</p>
  <h2>验收计划</h2>
  <p>测试覆盖第 20/21 页边界、跨任务总量、空闲超时与压力 LRU、活动/接管/未知动作保护、用户页面排除、外部关闭、
    并发创建、关闭失败及重启恢复；独立 Chrome 验证前台保护和精确目标回收。运行仓库 quick / full 门禁，截图保存在 PR 图片分支。</p>
</section>
<section id="browser-tab-pool-acceptance" lang="zh-CN">
  <h2>标签池验收记录 · 2026-10-21</h2>
  <p>独立 profile / CDP / 数据目录的真实 Chrome 打开 20 个 Agent 页面后拒绝第 21 个；任务释放后，空闲回收关闭两个后台页，
    保留正在前台查看的 Agent 页面和原有用户页面。测试浏览器与私有 tmux 由隔离启动器管理，现用服务未部署此变更。</p>
  <p>数据库升级至 schema 9，Go 备份恢复兼容上限同步更新；升级过程保留原任务历史。
    部署时需将显式 max_tabs=3 或 max_tabs=0 改为 20；新范围为 1..20，不能提前写入旧版不支持的配置。</p>
  <p>合并最新 main 后保留观察失败与满额重试终止保护；843 个 Python 用例通过，覆盖重启后的重复满额拒绝和回收后继续开页。</p>
</section>

<section id="browser-origin-groups" lang="zh-CN">
  <h1>人工与智能体浏览器分组 · 2026-10-22</h1>
  <h2>产品设计</h2>
  <p>浏览器页面统一归入人工、智能体两组。默认来源为智能体，包括 CLI 和无法追溯来源的历史页面；
    界面新建显式传 origin=human，用户可在页签菜单更改分组。查看页面不改变来源。创建来源单独永久记录，后续移组不改写创建来源。服务重启保留记录；Chrome 完全重启按恢复快照延续分组和来源，新页面重新计时。分组、固定和休眠状态持久化。
    桌面标签条与手机全屏二级页提供同一组切换和菜单，手机分组栏固定、页面列表独立滚动，休眠页保留标题和地址，选中即唤醒。</p>
  <p>智能体组默认共享最多 20 页（可配置），默认空闲 2 分钟休眠、10 分钟关闭，满额优先回收闲页；人工组默认空闲 30 分钟休眠，
    自动关闭默认关闭。设置中分别配置两组的休眠和关闭时间，0 表示关闭该策略；输入完成后失焦或回车保存，保存后立即生效，校验失败保留输入。
    休眠冻结页面执行并保留页面状态，减少后台运行；关闭才释放页面。不能把冻结宣称为内存释放。</p>
  <p>前台、固定、任务占用、人工接管、运行中或结果未知的操作，以及未提交表单、文件选择和媒体播放受保护。
    无法确认安全状态时跳过自动处理。旧页面第一次登记从当前时间开始计时，不在升级时立即清空。
    用户主动关闭仍为显式行为；更改分组不取消任务租约或未知动作保护。</p>
  <h2>用户故事</h2>
  <ul>
    <li>我从界面打开的工作页面自动归人工组；Agent 和终端创建的页面归智能体组，不混在一条长列表中。</li>
    <li>我能把 Agent 找到的有用页面移到人工组并固定，刷新或重启后仍保留归属。</li>
    <li>后台闲页自动休眠，Agent 的过期结果自动关闭；人工页面默认保留，可自行开启超时关闭。</li>
    <li>运行中的任务和未完成的输入不会被回收；休眠页再次使用时先恢复执行。</li>
  </ul>
  <h2>技术设计</h2>
  <pre>internal/browsertabs/catalog.go       唯一来源目录、跨进程文件锁、原子 JSON 与分组策略
backend/browser/tabs.go               显式来源创建、修改来源/固定、列表元数据
backend/browser/automation/           CLI 默认来源、使用与操作记录、休眠/唤醒、安全维护检查
agent-runtime/executors/browser_tabs.py 发现全部页面，复用资源租约与持久操作回执处理两组生命周期
agent-runtime/migrations/0010_*       分组、保护标记、策略时间与维护动作类型
frontend/components/mirror/           分组标签条、手机列表、移动分组与休眠状态
frontend/components/settings/        两组策略表单；中英文本纳入全局 i18n</pre>
  <p>目录保存于节点 data root 的 browser-tabs.json，通过 Go 统一访问，按 browserId+targetId 定位；
    CLI 驱动通过本机隐藏目录事件入口登记，不依赖公开 HTTP 或登录。目录不存页面正文和凭证。
    Python 保留唯一回收循环；未绑定任务的 CLI/历史页也登记为可管理资源，活动资源沿用既有租约隔离。
    冻结、关闭均记录唯一操作 ID，未知操作不重放；维护预约阻止来源变更与新操作竞争。
    CLI、界面和现有浏览器重启恢复同步来源；缺失来源回落智能体，不能用 URL 猜来源。</p>
  <h2>验收计划</h2>
  <p>验证默认来源与界面人工标记、历史页登记、目录重启/并发/落盘失败、分组迁移与固定、两组阈值、CLI 活动和未知结果保护、
    休眠后实际冻结及唤醒、原生任务与历史页共同容量。运行仓库 full 和前端全部门禁；使用隔离服务、真实 Chrome 和 Android 真机验证界面，
    截图保存在 /tmp，不部署到现用服务。</p>
</section>

<section id="browser-origin-groups-acceptance" lang="zh-CN">
  <h2>浏览器分组验收 · 2026-10-22</h2>
  <ul>
    <li>Go 目录采用原子 JSON 和跨进程文件锁；CLI 默认智能体、界面显式人工，创建来源与当前分组分别保存。移组和固定跨服务重启保留，Chrome 恢复快照延续来源与分组。</li>
    <li>真实 Chrome 验证后台计时器冻结、再次调用自动唤醒、未提交表单拒绝关闭、固定页保护；真实维护循环关闭过期智能体页、休眠并保留人工页，前台页保持打开。</li>
    <li>真实 CLI 与 REST 验证智能体 20 页、第 21 页拒绝、满额仍可创建人工页、移入已满智能体组被拒绝、无来源的历史页归智能体，移组不改写创建来源。</li>
    <li>完整质量门禁通过，Python 844 个用例通过；前端 124 个测试文件、882 个用例，typecheck、i18n、hover 和生产构建通过。后续小范围修订另通过对应 Go / Python 回归，提交钩子重跑 quick 门禁。</li>
    <li>桌面检查 390、820、1280、1600、1920 宽度。Redmi Note 8 以真实触控完成分组、改组、20 页列表滚动、固定返回栏与分组栏、Android 返回键、策略保存及刷新恢复；392 CSS px、coarse，无文档或横向溢出。</li>
    <li>截图和设计预览位于 /tmp，服务与 Chrome 使用独立数据目录及隔离 tmux；现用服务未部署此分支。自动维护依赖已启用浏览器工具的原生 Agent 服务，停止该服务时不执行自动休眠或关闭。</li>
  </ul>
</section>

<section id="browser-group-config" lang="zh-CN">
  <h2>浏览器分组策略可配 · 2026-10-22</h2>
  <h3>产品设计与用户故事</h3>
  <p>用户在浏览器设置中分别调整人工、智能体组的页数上限、休眠和自动关闭时间，无需改文件或重启。页数允许 0..1000，0 表示不限；默认智能体 20、人工不限。时间仍以分钟输入，0 关闭对应策略。降低上限只阻止超额新建和移入，不立即清空已有页面，保留现有回收保护。</p>
  <h3>技术设计</h3>
  <p>扩展 internal/browsertabs 的同一份 tabPolicies，新增两组 maxTabs，缺失字段兼容原有默认。Go REST、Node CLI 与原生 Python 容量检查读取同一策略；驱动 capabilities 返回当前策略，旧驱动保留 TOML 回落。界面字段失焦或回车后保存，新增中英文文案；校验拒绝负数、分数和超过 1000。验证配置迁移、热更新、两组新建与移组限制、无限模式、保护页及手机触控。</p>
  <h3>验收记录</h3>
  <p>真实 Chrome 验证人工独立容量、智能体增加到 22 页、降低上限不删页、超额新建及移组受限、0 不限和非法数值拒绝。桌面及 Redmi Note 8 真机验证页数输入、回车保存、刷新恢复、两组独立设置与无文档溢出；截图位于 /tmp/browser-capacity-desktop.png 与 /tmp/browser-capacity-phone.png。前端 124 个文件、883 个测试通过，Python 容量及驱动 52 个回归通过；运行仓库完整门禁与提交前 quick 检查。现用服务未部署本分支。</p>
</section>

<section id="browser-group-navigation-design" lang="zh-CN">
  <h2>浏览器分组查看设计 · 2026-10-22</h2>
  <p><a href="/api/file/serve/tmp/browser-group-navigation.html">打开可交互原型</a>。本节是产品提案，原型使用示例数据，不连接真实 Chrome。</p>
  <h3>产品设计</h3>
  <p>应用工作区标签和浏览器网页标签保持两层。网页标签栏右侧（用户截图红框位置）常驻“人工 数量 / 智能体 数量”，中间仅展示当前组，旁边固定“全部页面”入口。切组恢复该组上次查看的页面；空组在标签区显示“暂无页面”，保留当前网页直到用户选择其他页面。计数显示实际页面数，容量与超时配置仍放浏览器设置，不常驻占据浏览区域。</p>
  <p>“全部页面”在桌面打开右侧目录，无需离开当前网页；默认分两段展示人工和智能体，提供标题 / 网址搜索、来源筛选。查看或筛选目录不切换当前网页，选择具体页面才激活并按需唤醒。每行只显示标题、域名、已知固定 / 休眠状态；创建来源与完整地址收进详情或菜单。原型为便于评审直接展示移组动作，产品沿用统一菜单，桌面和触控均有可见“更多”入口。</p>
  <p>从界面新建始终归人工，工具栏写“新建人工页”，不随当前筛选变成智能体来源。可将智能体结果移到人工组，也可反向移动；移动不改写创建来源，不取消任务占用和未知操作保护，失败保留原组与当前页面。当前页面被移组时来源指示随之更新；移动其他页面不打断正在查看的页面。后台新增页面只更新数量，不抢组、不切页。被关闭或删除的组内最近页面回退到仍存在的页，不跨组猜选。</p>
  <p>手机主浏览器保留标签入口；来源筛选置于“全部页面”中，使用 MobileSubPage 全屏二级页，一层返回栏，固定搜索 / 来源筛选，只有列表滚动。点页面返回浏览器，返回键仅关闭目录；桌面收窄沿用手机方案。空组显示“暂无页面”，搜索为空显示“未找到页面”，不追加零结果计数。只展示有可信元数据的状态，不虚构任务名和执行中标记。</p>
  <h3>用户故事</h3>
  <ul>
    <li>我能直接查看人工页面和智能体找到的页面，来回切换时恢复各组上次阅读的位置。</li>
    <li>我能打开全部页面按标题或网站找结果，搜索和筛选时不打断当前网页。</li>
    <li>我能把有用结果移入人工组继续使用，原始创建来源保留，任务与输入保护继续生效。</li>
    <li>智能体在后台查资料时，我正在看的组和页面保持稳定；手机上同样能查找、选择和移组。</li>
  </ul>
  <h3>技术设计与交付范围</h3>
  <pre>BrowserView                          唯一页面目录快照、激活页面及用户当前来源
browser-tabs.tsx / TabStrip           常驻来源切换、组内最近页面、标签条和目录入口
browser-tabs.tsx / TabSheet           桌面目录 / 手机 MobileSubPage，共用搜索与分组列表
TabInfo                              复用 origin / createdBy / pinned / sleeping
GET /browser/tabs + PATCH /tabs/:id   复用现有读取与移组，不新增后台轮询</pre>
  <p>每组最近页面在当前面板内记忆，恢复前核对目标仍存在；目录筛选是独立临时状态。后台快照合并只维护数据，不改写用户选择。原型演示基本两组；若增加“Agent 按任务 / 会话分组、人工自定义分类”，必须独立设计 subgroupId 与可靠创建归属，不能用网页 URL、模型品牌或当前任务租约推断历史创建者。设计已按用户指定位置进入实现；发布状态以本次验收记录为准。</p>
</section>

<section id="browser-group-navigation-placement" lang="zh-CN">
  <h2>分组入口位置修订 · 2026-10-22</h2>
  <h3>产品设计与用户故事</h3>
  <p>按用户截图红框，分组控制固定在桌面网页标签栏右端，左边继续展示当前组标签；旁边“全部页面”打开可搜索的两组目录。原“智能体模式 / 手动模式”属于自动跟随行为，移入更多菜单，改为明确动作“暂停自动跟随 / 恢复自动跟随”，避免被理解为页面来源。手机沿用标签入口打开全屏目录；新建始终人工来源。用户能在固定位置找组、搜索、移组，并在各组恢复上次选择。</p>
  <h3>技术设计</h3>
  <p>TabStrip 的 mc-tabs-end 承载来源 Segmented 与全部页面按钮，标签区 flex 收缩和内部横滚。TabSheet 共用目录内容，桌面在 BrowserView 内呈现右侧非模态面板，手机复用 MobileSubPage。搜索和来源筛选不触发激活，批量关闭只作用于可见的同来源组。复用已有读取与修改接口，不新增轮询。样式使用令牌、粗指针命中区和中英文文案。</p>
  <h3>验收记录</h3>
  <p>真实隔离 Chrome 验证分组按钮位于标签条右端、恢复各组最近页面、目录同时展示两组、搜索不激活页面、REST 移组与更多菜单中的自动跟随。Redmi Note 8 真机验证搜索、移组、Android 返回、20 个智能体页面触控滚动，搜索和分组栏保持固定。320、390、820、1100、1280、1600、1920 宽度在中文深色与英文浅色下共 14 组验证无文档或横向溢出。前端 124 个测试文件、887 个用例通过，执行 full 与提交前 quick 门禁。截图位于 /tmp/browser-right-after.png、browser-right-directory.png、browser-right-phone.png、browser-right-phone-scroll.png；未部署到现用服务。</p>
</section>

<section id="non-git-task-setup" lang="zh-CN">
  <h2>无 Git 项目开任务修复 · 2026-10-22</h2>
  <h3>产品设计</h3>
  <p>开任务和新建／派生会话按实际目录检查 Git，不依赖项目列表的旧状态。未初始化或没有首次提交时显示短提示，保留直接在目录开工的能力；用户可显式确认将当前文件保存为首次提交，遵循现有 .gitignore，成功后开放 worktree。失败保留任务与 Agent 选择，提供重试。</p>
  <h3>用户故事</h3>
  <p>新项目用户能在同一表单初始化 Git、保存项目快照并创建含现有文件的独立工作区；已有空仓库用户能补首次提交；不需要版本管理的用户可直接开工。</p>
  <h3>技术设计</h3>
  <p>backend/worktree/repository-setup.go 负责目录探测、初始化和首次快照，以目录锁及现有仓库锁串行写入；有提交的仓库幂等返回，不提交后续改动。GET /git/is-repo 增加 hasCommits 与 root；POST /git/initialize 显式修复。RepositorySetup.tsx 在任务表单共用检查、确认及恢复状态，过期目录响应不能覆盖新选择。remote-base.go 在无任何远端时验证并使用本地分支快照；有远端继续 fetch，失败不回退旧快照。任务目录刷新复用 pollWhileVisible。手机顶栏新会话按钮显式无参调用，防止点击事件被当作目录。</p>
  <h3>验收计划</h3>
  <p>验证未初始化、空仓库、有提交、忽略规则、失败重试、幂等与子目录边界；真实新 worktree 包含项目快照，原有远端拉取与失败保护通过。前端覆盖确认／取消、检查失败、任务内容保留与正确提交路径，执行仓库门禁、桌面与 Android 真机触控验收。</p>
  <h3>验收记录</h3>
  <p>Go 全量与仓库 full 门禁通过，Python 845 个用例通过；最终前端 126 个文件、896 个用例以及 typecheck、i18n、hover、生产构建通过。构建保留现有大块体积提示。quick 中一次已有 Claude 取消时序用例在并行构建下失败，单独重复 3 次通过，随后完整 quick 重跑通过。</p>
  <p>隔离 Go 服务、私有 tmux 和真实 Git 验证未初始化目录、已有空仓库 develop 分支、首次快照及无远端 worktree 创建；任务目录含原文件，.gitignore 排除本地文件。桌面验证中文深色及英文浅色；Redmi Note 8 真机以 392 CSS px、coarse 指针完成顶部入口、项目选择、任务输入、确认取消、初始化及新 worktree 会话创建。键盘实测 314px，确认动作高度至少 44px，无文档或横向溢出，未出现浏览器脚本错误。</p>
  <p>截图和验收脚本位于 /tmp/git-setup-*，不进入主分支。现用服务未部署本分支，用户项目未被初始化或提交。</p>
</section>
