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
  <p>导航中的“插件”升级为“能力”。页面设插件、Skill、MCP、CLI、基础工具五个 Tab。
    设置中的 Agent 能力管理整体迁入；模型、运行时、消息、记忆、专业 Agent 配置仍归设置。
    旧插件深链和 settings/agent 下的 skills、cli、mcp、tools、capabilities 深链映射到新页面。</p>
  <p>桌面使用统一页头、分类 Tab 与搜索目录。插件与其他分类统一采用独立能力卡片，展示图标、名称、来源、
    简短描述和真实状态；查看与编辑在卡片底部直接可见。详细指令、参数与配置按需打开。页面壳与相邻模块同底、直角，以单条细线分隔。
    手机从“工具”进入能力，保留首页、项目、工具、设置四个主入口；长详情、创建和导入使用全屏二级页，
    只有一层返回栏和一个滚动容器，输入与提交避让键盘。
    编辑表单的保存栏位于字段滚动区外，键盘留白只由 MobileSubPage 处理。</p>
  <h3>创建、导入与配置</h3>
  <ul>
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
  CapabilityCatalog.tsx   目录查询、过滤、启停与详情
  CapabilityEditor.tsx    创建、文件导入、校验及保存
  capability-format.ts   SKILL.md / JSON 的输入解析
  capabilities.css       令牌、响应式、粗指针命中区
frontend/src/components/plugins/
  PluginsPanel.tsx        插件卡片、URL 详情、安装与清单驱动配置
  plugins.css             插件身份、详情布局；卡片复用能力目录样式
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
    <li>仓库 quick / full 质量门禁通过；Go 测试通过。最终前端 120 个测试文件、838 个用例通过，Agent 运行时 744 个用例通过。</li>
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
    <li>所有截图与临时验收脚本位于 /tmp，不进入主分支；当前开发代码位于 feat/capabilities-hub。</li>
  </ul>
</section>
