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

<section id="local-model-proxy-20261026" lang="zh-CN">
  <h2>本地模型代理与每日限额 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>内置主智能体、后台任务、记忆与压缩的模型 HTTP 请求统一经过当前节点的本地传输代理。沿用模型连接与密钥配置，不增加监听端口。模型与连接页展示今日已知费用、Token、请求与未知费用笔数，可按模型填写人民币每百万 Token 的输入、输出、缓存命中单价，并设置可选每日限额。价格为空代表未定价，零代表明确免费；本地记账不修改上游账单。</p>
  <p>统计视图提供今日、近 7／30／90 天与累计周期；总览展示已知费用、请求数、总 Token、缓存命中率及输入／输出拆分，每日趋势可切换 Token 与费用并打开完整数值表，模型明细保留相同计量口径。完全未知的模型费用显示“未知”，部分未知时只展示“已知”金额；累计趋势限定最近 90 天并明确提示，总计与模型统计不丢弃更早历史。</p>
  <h3>User Stories</h3>
  <ul><li>我能在原模型设置页查看内置智能体的合计花费，并在重启后保留账目。</li><li>我可按节点时区设置每日限额，达到后停止新请求；最后一笔在途调用可能超额。</li><li>我能区分已知消费与缺价格、缺用量或中断后的未知费用；限额启用时未知费用阻止继续消费，失败不伪报免费。</li><li>我能切换统计周期，对照每日趋势、分模型用量与总计，并保留正在编辑的限额和价格；缺少计量的请求不会被伪装为零消费。</li></ul>
  <h3>Technical Design</h3>
  <p>providers/model_proxy.py 实现 httpx 传输代理、透传 SSE 与用量提取；model_billing.py 负责配置验证、固定精度人民币计价和 SQLite 请求账本。参考 ~/codes/llm-gateway/internal/observe 的三类 Token 计价，OpenAI 缓存命中从总输入中扣除，避免重复收费。每笔请求冻结价格，完成后只结算一次，不存提示词、响应正文或密钥。启用限额时主／后台请求串行准入，拒绝未定价模型、当天未知账目和达到限额的新请求。进程恢复将未结算请求保留为未知，不重放。每日按 memory_timezone 归属请求发起日。</p>
  <p>统计修订：代理与计费支持今日、近 7／30／90 天与累计，展示周期总计、每日 Token／已知费用趋势及模型明细，分别统计输入、输出、缓存命中、请求、未知费用、未定价、缺用量、在途与失败。缓存 Token 属于输入，不重复加入总 Token。累计模式的总计与模型统计覆盖完整账本，每日序列最多最近 90 天并明示日期；无请求日期补零，最多展示 200 个模型并明确截断。providers/model_usage.py 按已持久化的请求归属日聚合，GET /agent/model-usage?days=0..90 保留今日接口字段。前端 model-usage-statistics.tsx 使用 CSS 图表与可展开的每日表格，不增加图表依赖或轮询；周期切换取消旧请求，统计失败不清空编辑草稿。</p>
  <p>model_settings.py 原子保存 proxy 配置并保留现有所有者隔离、忙时拒绝与失败保留输入。GET /agent/model-usage 通过原 Go 登录网关返回当天合计及最近请求；页面进入与保存后读取，不增加轮询。价格编辑与限额复用现有设置草稿、令牌、中英语言包及手机表单。</p>
  <h3>验收记录</h3>
  <p>统计修订验收：full 门禁通过，Python 1,383 项、Go 全量及前端生产构建通过；前端最终 1,002 项测试通过。新增回归验证日／模型／总计一致、缓存不重复计数、空日补零、历史累计、90 天序列边界、200 模型截断、参数及所有者边界、周期请求乱序与失败保留草稿。实际 Go 网关返回的隔离示例核对：近 7 天 20 请求／330,940 Token，累计 21 请求／460,940 Token；不含真实付费模型消费。生产包验证所有周期、费用／Token 趋势、每日明细、跨 Tab 草稿保留、七档宽度及中英／深浅主题，无文档与统计区横向溢出；最终版本追加验证“未知”与“已知金额”及累计窗口提示。证据位于 /tmp/local-model-stats-20261026/index.html。真机仍为安全锁屏，未宣称触控与软键盘验收通过。</p>
  <p>页面修订：模型与连接内部使用“模型配置”“代理与计费”两个 Tab，默认显示连接与主／后台模型。两页共享设置草稿及一个保存栏，切换不保存、不清空输入；隐藏页的字段不参与浏览器原生表单校验。用量只在打开计费 Tab 与保存后读取，隐藏时取消请求，不增加轮询。Tab 使用已有 antd 组件、设计令牌与粗指针命中区。</p>
  <p>Tab 修订验收：前端 997 项测试、typecheck、i18n、hover 与生产构建通过。生产包完成默认 Tab、跨页草稿保留、统一还原、隐藏计费页不请求用量，以及七档宽度下两种语言／主题的实际切换与溢出检查；报告为 tabs-desktop-checks.json，截图为 tabs-models.png、tabs-proxy.png。此轮仅修改前端与验收记录，Python 与 Go 沿用上轮通过的门禁；真机验收仍等待安全锁屏解锁。</p>
  <p>代理新增 25 项回归通过，覆盖缓存不重复计费、压缩与分片 SSE、重试逐笔入账、主／后台限额串行准入、跨日重置、未知费用阻断、磁盘重新打开、取消和所有者隔离。全量 Python 1,367 项与 Go 测试通过，前端 996 项测试通过，新增交互覆盖限额／价格原子保存、失败保留输入、未填齐价格和显式免费。新增账表使用 schema 13，Go 备份恢复同步接受该版本并继续拒绝更新的版本。</p>
  <p>独立 HTTPS 服务与本地 HTTP 测试上游完成主／后台真实传输、记账和限额拦截：1,200 输入、80 输出、400 缓存命中在测试单价 2／8／0.2 下费用为 ¥0.00232，拒绝后上游请求数未增加。桌面完成保存、刷新恢复、320／390／820／1100／1280／1600／1920 宽度、中英和深浅主题检查，无文档溢出。证据入口 /tmp/local-model-proxy-20261026/index.html；未使用真实付费模型，未部署现用服务。Redmi Note 8 当前为安全锁屏，真机触控和软键盘验收待解锁，不能据桌面缩窄宣称手机验收通过。</p>
  <p>full 质量门禁通过。实际 Go CLI 备份后恢复到另一个隔离目录，3 笔调用的身份、日期、角色、模型、状态、单价快照、Token 和费用逐项一致，合计 10,160,000 纳元；恢复库 schema 为 13，证据为 backup-checks.json。测试服务与插件守护进程通过记录过身份的隔离启动器清理，未清理现用 tmux 服务器。</p>
</section>

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
- Scope checks to the affected code. Run Python dependency sync, lint, formatting, and tests only
  when Python code, runtime resources, dependencies, or Python test configuration changes; skip
  them for frontend-only and other unrelated changes. Local hooks inspect staged changes, and CI
  inspects the complete PR or push diff, including deleted files. If the comparison cannot be
  determined reliably, run the Python checks instead of silently skipping them.
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
    <li>Agent：Claude Code、Codex、OpenCode、Pi 使用品牌卡片，展示安装、登录确认状态与可用额度。安装和更新沿用已有白名单接口；列表自动读取已安装版本和程序位置；版本探测合并并发并缓存，“检查”立即重查。管理详情可保存启动命令（包括模型参数），打开已有会话终端完成登录与模型选择。安装成功不代表已登录；没有可靠证据时显示“登录待确认”。</li>
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
  <p>Agent 目录复用 /agent/professional 和节点偏好。页面仅一个可见性控制的轮询，错误退避且保留最近快照；安装按需执行。列表自动读取版本，成功缓存 5 分钟，失败退避 1 分钟；可执行文件路径、身份、大小或修改时间变化立即失效，安装成功清缓存，显式检查绕过已完成缓存。版本检查只允许运行已注册 Agent 的默认程序和固定 --version 参数，3 秒超时、输出上限 4 KiB。新窗口不会自动启动 CLI，也不会把本地凭证返回给前端。专业 CLI 的 Skill / MCP 配置继续由各自管理，不声称 Roami 托管能力已自动绑定到它们。</p>
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

<section id="rsi-memory-evidence-20261026" lang="zh-CN">
  <h2>RSI 记忆证据修复 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>记忆提取读取用户原话、助手可见文本与既有任务／产物证据；助手工具调用参数仅表示执行意图，不作为已观察事实送入提取器。没有可用证据时直接完成空提取，不调用模型。完整转录仍保留工具参数。</p>
  <h3>User Stories</h3>
  <p>用户要求的项目习惯保持原会话／项目范围，不因助手的委派指令扩展为全局偏好。维护者可以用原始来源哈希复核记忆，模型引用已排除的来源时仍明确失败。</p>
  <h3>Technical Design</h3>
  <p>memory/jobs.py 仅在构造模型输入时移除 assistant 内容中的 tool_calls；保留其他字段和原文，排除空助手证据。来源白名单以实际提供的证据生成，写入仍使用原始来源 SHA 并执行既有所有者、遗忘、作用域与激活校验。空证据分支明确记录零请求与零用量；任何已发出的未知用量不走此分支。模型路由、输出限额、重试策略和原始转录不改变。</p>
  <h3>验证记录与剩余问题</h3>
  <p>60 项记忆管线回归通过，覆盖参数排除、可见文本保留、原始来源哈希、已排除来源拒绝、无证据零模型调用。真实低推理 DeepSeek 对照中，原输入以 2,048 个纯推理 Token 截断；投影输入一次得到有效 JSON，隔离 MemoryJobs 复测原任务仍出现同类截断。显式项目偏好样本完成提取，激活记录保留会话范围，无全局激活。两组四次请求共 9,159 Token，用量均已知，失败记录保留；不能据此宣称 MODEL_OUTPUT_LENGTH 或 #443 历史未知流中断已经解决。正式 GLM Memory 路由、质量校准和完整验收仍需各自验证。</p>
  <p>本轮诊断配置的 GLM Memory 路由另作隔离运行验证：原任务与显式偏好两种输入均由真实 MemoryJobs 完成，共 984 Token／两次请求，无重试、无未知用量；项目偏好激活保持会话范围。此结果单列路由，不抵消 DeepSeek 的已知截断失败，也不表示现用服务已部署或改配。</p>
  <p>后续修订提取指令：一次性任务验收清单和未执行计划不属于可复用记忆，不为凑满条数拆分要求；持久事实、已观察结果／决策及长期偏好继续提取。仍使用原 DeepSeek low、2,048 输出上限、20 秒运行时限且不重试，原 CODE-01 输入完成空提取；显式项目偏好保留会话范围，持久部署事实与发布结果分别生成事实候选。四次真实 MemoryJobs 共 3,009 Token，用量完整，原始失败保留。这是四种输入的修复验证，不能替代全套或历史未知流中断的根因证明。</p>
  <p>用户随后授权将每日上限改为 20,000,000 Token；已同时保存运行和评测配置，自动调度仍关闭，原 Case 上限保持。原全套单轮预留 13,292,000 Token 的预算阻塞已解除；四份修订样本人工参考分和完整验收仍独立待完成。</p>
  <p>相同 DeepSeek low 路由的真实 NEWS-01／QUANT-01 回归，六个 MemoryJobs 均完成且无异常码。QUANT-01 独立验收通过；NEWS-01 五条事件字段值与合同一致，但擅增顶层元数据而失败。两项合计 178,183 Token／26 次请求，原失败继续保留。</p>
</section>

<section id="rsi-structured-delivery-20261026" lang="zh-CN">
  <h2>结构化交付合同修复 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>用户给出结构化输出合同时，文件和回复遵守约定字段与类型；只有明确允许扩展才添加字段。说明、来源和诊断信息写入另行请求的报告，不擅自扩展机器消费的结构。</p>
  <h3>User Stories</h3>
  <p>用户获得能由既定消费者读取的结构化文件；可读报告仍保留依据与限制，不为补充说明破坏接口。</p>
  <h3>Technical Design</h3>
  <p>replies/delivery_policy.py 的交付指令由 Main 与 Worker 共用。规则仅描述用户已经提供的合同，不含案例名称、参考答案或评分字段；不修改题目、判定器、用量核算与 Case 上限。原始错误输出与验收失败记录保留，新版本单独复测。</p>
  <p>初版交付指令过长触发两项上下文边界回归；压缩共用文案并保留原有交付约束，27 项上下文与文件交付回归通过，不放宽上下文上限或测试断言。较早的同镜像 NEWS-01、CODE-01、QUANT-01 独立硬检查均通过，但随后发现 QUANT-01 仅保存两份文件快照，因此硬检查不作为完整交付通过。</p>
</section>

<section id="rsi-relative-deliverables-20261026" lang="zh-CN">
  <h2>相对文件名与 SVG 交付修复 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>用户收到请求的全部文件，包括脚本生成的数据和图形；任务摘要用代码格式列出的相对文件名按已绑定工作区收集。保存后不依赖原目录继续存在，不以工作区中存在文件替代可下载快照。</p>
  <h3>User Stories</h3>
  <p>任务列出 analysis.py、result.json、report.md、trades.csv、equity.svg 时，五份文件都能在任务产物中读取；工作区移除后仍可下载原始字节。路径越界、软链接和隐藏文件不能借相对名称进入产物。</p>
  <h3>Technical Design</h3>
  <p>storage/task_deliverables.py 扩展既有摘要路径解析，仅在有工作区绑定时接受带支持后缀的单个代码格式文件名，跳过命令和 URI，不扫描目录。SVG 纳入已有文件类型集合，继续使用逐层 no-follow、目录边界、文件大小、所有者、删除标记和 12 项上限。下载仍为 attachment，沿用 nosniff 与 sandbox CSP，不增加内联执行入口。</p>
  <h3>验证记录</h3>
  <p>62 项文件／任务交付与产物回归通过，新增 Native／专业执行器五文件保存、删除工作区后读取，以及父目录、软链接和隐藏文件边界。对真实 QUANT-01 的原始文件与最终摘要作零模型隔离重放，五份快照 SHA 均匹配原文件，复制目录移除后仍可读，SVG 附件头、CSP 与跨所有者拒绝通过；原 trial 和原文件未修改。该重放只证明持久化修复，不作为新的 Native 执行或正式评分。</p>
  <p>进一步保留代码格式文件名中的字面百分号，避免与空格文件名混淆；归一 /api/file/serve 的分段、全路径编码与额外首斜线形式，避免同一 SVG 已保存却因别名误报不可用。归一后仍执行原目录边界与 no-follow 校验，不将 URL 当作新的文件权限。</p>
</section>

<section id="rsi-delegation-contract-20261026" lang="zh-CN">
  <h2>委派合同保真修复 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>Main 原样传递用户明确的合同与约束，不把解释过程产生的公式或验收条件当作用户要求。数值工作按用户约束做手算样例及守恒／边界检查，不能仅用复制了同一公式的第二份代码声称独立验证。</p>
  <h3>User Stories</h3>
  <p>用户要求在现金额度内完成含费用的计算时，委派不会变成先花光现金再扣费。用户能区分原合同、已观察结果与执行器自检；错误自检不覆盖独立验收失败。</p>
  <h3>Technical Design</h3>
  <p>压缩 configuration.py 中既有交付说明，补入 Main 的合同原文传递和 Worker 的数值验证原则；不包含具体案例、公式答案或判定器信息。当前短交付文案仍保留显式输出合同、用户语言、真实链接、未知状态与可用交付要求。</p>
  <h3>问题证据</h3>
  <p>ff9c38a1 对应版本的三项独立检查为 CODE-01、NEWS-01 通过，QUANT-01 失败；三项共 334,118 Token／45 次请求，用量完整。失败原因为 Main 把“含买入费用的全现金买入”改成“数量等于现金除价格，另扣费用”，Worker 按改写后的规则执行，自检复制同一错误。该失败与原产物保留，不以此前较早版本通过抵消；合同修复后另作真实执行验证。</p>
  <p>仅增加 Main 保真指令的下一版，CODE-01 与 QUANT-01 通过，NEWS-01 仍因 Main 自行扩展结构而失败；三项共 345,331 Token／50 次请求，用量完整。这说明指令不足以保证原合同到达 Worker，不能把单次通过当成问题消失。</p>
</section>

<section id="rsi-native-original-request-20261026" lang="zh-CN">
  <h2>Native 原始用户合同传递 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>普通 Native 任务与已有浏览器研究任务一样，执行上下文同时保留用户原文和协调目标。用户原合同定义事实与约束，Main 目标只限定本次分工，不能覆盖原合同或扩展到未分派的其他事项。</p>
  <h3>User Stories</h3>
  <p>即使协调者把结构或数值规则转述错了，Worker 仍能读取未经改写的用户原话。用户继续在会话中看到原有任务目标；执行记录保存完整来源，跨所有者和已遗忘来源仍不可读。</p>
  <h3>Technical Design</h3>
  <p>dispatch/tasks.py 在已有事务和来源校验内构造 Native 种子消息，普通任务加入原始 source_content.text，再明确合同优先级和分工范围。displayText 保留原目标，模型读取完整 text，存档保留两者；resourceOnly 保持既有显示与输入形式。附件继续沿用原所有者和完整性校验，不增加文件权限或新执行器。</p>
  <p>显式从已完成检查点派生的普通 Native 分支保留原继承边界，不再附入检查点之后的新消息；其历史已有该检查点的用户约束。嵌套执行测试模型按简报中的分工目标工作，原有后代汇合、Main 容量预留和分支隔离断言保留，74 项相关回归通过。另有 95 项路由、Native 工作区、存档、研究和续派回归通过；四个新增场景验证原合同、显示目标、跨所有者和遗忘边界。</p>
  <p>后续真实执行再次暴露原 DeepSeek low／2,048 Memory 输出限制，以及 NEWS-01 在额度内尚未满足结构合同的失败；319,577 Token／48 次请求，用量已知，结果保留。原文传递不是所有错误已解决的证明；另补充显式输出结构不得因元数据真实而扩展的说明，并验证下述预算及流错误修复。</p>
</section>

<section id="rsi-metered-prefix-20261026" lang="zh-CN">
  <h2>已计量前缀预留与流错误保真 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>预算准入继续保守预留，但已成功计量、序列化完全相同的文本前缀不再每次按全部 UTF-8 字节估计。每次请求仍扣完整实际输入与输出；没有费用折扣、未知用量补零或 Case 上限提高。已知生成失败保留原异常码，不能伪装成可重试的流不完整。</p>
  <h3>User Stories</h3>
  <p>用户不会因重复上下文的过大预估而提前失去必要的收尾调用，也不会为已经明确达到输出上限的记忆提取重复付费。提供方用量未知、上下文变化或工具变化时保持原拒绝与保守回退。</p>
  <h3>Technical Design</h3>
  <p>input_reservation.py 保存单个角色实例最近成功、单次请求且输入／输出用量完整的文本指纹与用量。只有消息严格追加、原前缀逐项序列化指纹及工具指纹相同才采用“原完整输入 Token + 新增序列化字节 + 既有 4,096 预留”；图片、编辑、前置插入、工具变化或不完整响应回退。RequestBudgetModel 另计新预算提示的全部字节，双层 MeteredModel 共用同一预留，容器内持久 MeteredModel 也执行相同规则。实际结算与未知用量熔断不变，预留依据写入私有日志。</p>
  <p>ChatCompletions 识别 SSE error 帧，先保留已到达的用量，仅透传有限的协议异常码，其他格式归为 MODEL_STREAM_INVALID，不回显提供方内容。部分工具调用不发布；ModelGateway 的 MODEL_OUTPUT_LENGTH 等终止码到达 MemoryJobs 后一次失败，不再降格成 MODEL_STREAM_INCOMPLETE 并重试。协议标为 container-uds-v6-prefix-reservation，不与 v5 混算同合同收益。</p>
  <p>诊断和报告首次建立当日预算时使用已配置的每日例数，诊断同时检查例数余额，避免原先 10,000 占位值阻塞后续 120 例配置的正式准入。现用当日预算在确认没有正式 cycle、已用例数为 0 后，从占位值收紧到既有 120；Token 上限仍为用户授权的 20,000,000，用量与预留计数均保留。</p>
  <h3>验证与角色配置</h3>
  <p>64 项准入、计量、错误透传相关回归通过，覆盖共享预留、完整扣账、前缀变化／多模态回退、未知用量、失败响应不建立前缀及容器侧持久计量；另有 25 项流水线回归通过，包含先诊断再正式预留和每日例数上限。DeepSeek none 的四次记忆探针共 2,237 Token，但空提取语义断言失败，未采用；GLM low 的四种语义输入均通过，共 2,104 Token。RSI 配置保存为 Main／Worker DeepSeek low、Memory GLM low，Memory 输出上限仍为 2,048，自动调度关闭；不表示部署或改配现用 Agent 服务。</p>
</section>

<section id="rsi-integrated-verification-20261026" lang="zh-CN">
  <h2>RSI 合并验证与完整运行 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>请求进入预算准入前固定消息与工具内容，等待预算锁期间调用方的修改不能改变已评估的输入；实际费用仍逐次完整结算。完整案例结果逐项保留，内容检查通过、任务文件持久化和产物质量评分分别给出证据。</p>
  <h3>User Stories</h3>
  <p>用户能分辨已经验证的链路修复与仍失败或待评的案例，不因部分成功而丢失失败记录，也不因运行已启动而收到通过或关单结论。</p>
  <h3>Technical Design 与验证</h3>
  <p>RequestBudgetModel 与 MeteredModel 在准入前复制 JSON 请求，预算等待竞争的两个新增回归验证提供方收到原快照，调用方修改仍保留。91 项计量、准入、错误透传和流水线检查通过。同步 main f3622829 后 quick/full 通过，Python 1,427 项，Go、前端静态检查与生产构建通过；本 PR 没有新增前端产品改动。</p>
  <p>合并后源码 hash 为 9f7efc03377f6edc5b2f44a5317e17b9b4f3a49bc24f3615dfd1cb7b82c4dc0d，镜像为 sha256:2abc59f835a7b97659c908f8def82a41f29cc01cd57afb88b0dc9cb21d2cc66e。该镜像冻结机制回归 20/20 通过，零模型调用；不作为真实模型能力或正式全套通过。</p>
  <p>此前 v6 三项真实独立检查通过，共 287,402 Token／40 请求；CODE 两份和 QUANT 五份文件快照 SHA 匹配。NEWS 由 Main 直接写入，两份文件没有任务快照，因此不称为三项 Native 完整交付。原失败与已知 DeepSeek Memory 截断保留，RSI Memory 使用经四种语义输入验证的 GLM low；现用服务未部署或改配。</p>
  <p>该合并源码启动单版本完整 60 项运行 c2728007454ed423bbe3a3a6be147ac8b07918f540a9274882b4932bd0bd8c5b，生成预留 12,032,000 Token；同时保留 7 项评分所需的 1,260,000 额度，日上限仍为用户授权的 20,000,000。最初八项为五通过、三失败：DEMO-02 真实预算失败及 OSWorld、FinQA 检查失败均保留。运行尚未结束，四份修订样本人工参考分未确认，产物评分与后续完整日观察未完成，父 issue 不关闭，自动日程保持关闭。</p>
</section>

<section id="rsi-main-turn-failure-20261026" lang="zh-CN">
  <h2>Main 失败预算归因 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>评测报告保留 Main 已记录的预算根因，不能把准入前拒绝折叠为通用运行时失败。错误归因修正不改变失败状态、费用、原始成绩或判定器。</p>
  <h3>User Stories</h3>
  <p>维护者看到长记忆任务真正因 Token 预算失败，能区分模型能力、费用未知和执行器异常；历史失败记录仍可核对。</p>
  <h3>Technical Design 与验证</h3>
  <p>evaluation_tasks.evaluation_turn_failure 只读取当前 turn、conversation 和对应终态事件的最新记录，仅保留既有四个 RSI 预算码，其余仍使用原 RSI_TURN_FAILED／INTERRUPTED；不导出任意错误文本。NativeFilesExecutor 在 Main 终态失败分支调用它，容器继续沿用已有有界预算码映射。</p>
  <p>51 项隔离回归通过，新增六种终止码和跨回合／会话／事件类型隔离。对完整运行中 longmemeval-v2:4ed01379 的真实数据库执行只读、零模型重放，得到 RSI_TOKEN_BUDGET；原 trial 的通用失败及 SHA 保持，案例仍失败。该补丁只修正诊断归因，不声称解决预算耗尽或新增真实模型通过；正在运行的镜像与源码版本保持冻结。</p>
</section>

<section id="rsi-process-tool-contract-20261026" lang="zh-CN">
  <h2>执行工具的进程生命周期合同 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>工具说明明确既有生命周期：一次调用结束会清理其进程组。临时服务与客户端检查在同一次调用内完成，按已捕获的子进程 PID 清理，不按命令文本匹配进程。</p>
  <h3>User Stories</h3>
  <p>Worker 不再假定后台服务能跨工具调用存活，避免连接失败后反复改探针或用广泛匹配的清理命令终止自身验证步骤。</p>
  <h3>Technical Design 与验证</h3>
  <p>压缩并补齐 foundations 的 bash 和底层 shell 说明，保留工作区、授权主机操作、非沙箱、写入、取消、回执及托管资源边界；不修改 process.execute 的清理或权限行为。工具输入文本变化单列 container-uds-v7-process-lifetime，不能与 v6 混算同合同收益。</p>
  <p>40 项工具、上下文边界和评测通道回归通过。零模型独立对照确认临时 HTTP 服务在当前调用内可访问，进程组清理后后续调用无法复用；服务器与客户端同一调用、按子 PID 收尾的路径成功，未作用于其他进程。对照只证明工具合同，不改写正在运行的 v6 真实案例或声称预算失败已全部解决。</p>
</section>

<section id="composer-usage-indicator-20261026" lang="zh-CN">
  <h2>输入框用量组件 · 2026-10-26</h2>
  <h3>产品设计</h3>
  <p>额度与用时属于输入框内部的顶部状态行，与正文和工具栏共用输入卡的宽度、背景和边界，随输入卡居中，不再作为会话通栏。额度警示和用时详情沿用原有行为。</p>
  <h3>用户故事</h3>
  <p>用户在同一输入框内查看额度、用时和输入消息；桌面和手机保持对齐，点开详情不会发送草稿。</p>
  <h3>技术设计</h3>
  <p>ChatShell 将 StatusBar 传入 ConversationComposer.header；StatusBar 复用独立 UsageIndicator。输入卡内的状态行去掉外部分隔线，沿用既有详情层和触控命中区，不增加请求或轮询。</p>
  <h3>验收记录</h3>
  <p>quick／full、前端类型／国际化／hover、138 文件／997 项测试及生产构建通过，PR #457 的质量、策略与前端构建 CI 通过。提交钩子的进程观察用例受并行进程干扰，停止截图服务并串行执行 Go 包后完整通过。隔离生产包在 320、390、820、1440、1920 宽度确认状态行位于输入卡内、左右边界受输入卡约束，无文档溢出；中英／深浅主题、详情点按与草稿保留通过。390 宽度的粗指针模拟验证 44px 命中区；Redmi 仍锁屏，未完成真机验收。1100 整页脚本受既有终端面板遮罩阻挡，不记为通过。截图、测量和日志位于 /tmp/chat-usage-20261026。</p>
</section>



<section id="rsi-source-delivery-20261025" lang="zh-CN">
<h2>RSI源码文件交付修复 · 2026-10-25</h2>
<h3>Product Design</h3><p>原生与专业任务显式生成的Python、TypeScript、Go等源码和脚本，与文档一样保留可下载原件。不同路径写法指向同一份产物时只展示一份，用户已删除的文件不因换用链接写法重新导入。</p>
<h3>User Stories</h3><p>维护者在Worker完成编码后直接取得代码与测试文件，Main可以用真实产物回执交付，不因后缀不支持误报缺文件、重复检查工作区或重新派发任务。</p>
<h3>Technical Design</h3><pre>NativeExecutor / 任务详情 → TaskDeliverables
→ 工作区输出后缀白名单 + 原有no-follow读取
→ 文件链接解码后的sourceFile去重；兼容旧sourcePath
→ 私有ArtifactStore → 已归属任务的artifactRefs → Main任务结果</pre>
<p>目录边界、隐藏文件、符号链接、文件类型、体积、所有者和删除保护继续由已有读取与存储协议校验。sourcePath保留原始证据；sourceFile只作当前尝试内的别名归一化，不能把字面百分号与空格文件名混同。历史成绩与产物评分要求不变。</p>
<p>验收：83项定向回归、Native机制20/20及整仓full门禁通过，运行时共1289项。相同v11合同的真实CODE-01再次通过，app.py与test_items.py各保留一份可下载产物，不再出现TASK_RESULT_REQUIRED与WORKSPACE_REQUIRED；14次请求、69,373 Token，前一轮为16次、79,420 Token，单次差异不证明稳定节省。另对原DOC-05与DEMO-01产物执行无模型调用的独立硬检查与渲染；两项仍待评分，方案图存在文字裁切。人工校准参考分尚未确认，Issue #446保持开放。证据和源码产物位于/tmp/roami-rsi-source-report/；未提交或部署。</p>
</section>

<section id="roami-agent-rsi-design" lang="zh-CN">
  <h1>Roami Agent RSI 方案 · 2026-10-22</h1>
  <p>按用户要求，完整方案、整体架构图、决策空间展开图和可编辑 Excalidraw 文件统一保存在 <a href="docs/design/20261022-roami-agent-rsi/index.html">docs/design/20261022-roami-agent-rsi/</a>，后续修订维护该正文。</p>
  <h2>产品设计</h2>
  <p>每日主动跑用例或设计新实验，观察实际行为并提出修改意见，在隔离源码工作区实施后验证结果效果、交付时间与单位成功 Token；用户日常使用记录不是必要输入。参数搜索只属于辅助实验。</p>
  <h2>用户故事</h2>
  <p>用户能查看跨机评测证据、具体策略差异和三目标变化，在允许范围内应用或恢复策略，日常会话与测试环境隔离。</p>
  <h2>技术设计</h2>
  <p>复用运行时 trace、任务验收、调度与存储；已实现隔离评测、每日worker、规则回顾和有限参数发布底座。现已接入ResearchWorker、语义复盘、持久工单、隔离补丁、源码A/B和专用评测实例观察；真实每日评测尚未启用。完整模块、协议、接口和验收标准见设计正文。</p>
  <p>调研与评价修订：<a href="docs/design/20261022-roami-agent-rsi/research.html">开源做法与源码核对</a>、<a href="docs/design/20261022-roami-agent-rsi/evaluation.html">程序员工作 / 业余任务的 80 项候选规格与评价标准</a>。80项仅为候选池，正式库存已调整为60项（公开20、自有真实20、机制回归20）；尚无真实模型全量成绩，权重、断言和资源上限均有版本记录。</p>
  <p>自动化闭环修订：常驻RSI服务使用内部持久动作队列推进Codex复盘、Codex汇总GitHub Issue、Codex修复、独立验证、专用实例应用、观察与关闭/重开。Codex执行采用预算准入、原生用量与超时，CLI不保证供应商侧硬Token截断。GitHub Issue确认后才派修复，独立验收后发草稿PR；状态、幂等outbox、预算及关闭证据契约见<a href="docs/design/20261022-roami-agent-rsi/index.html#closed-loop">详细设计</a>。</p>
  <p>参与者与交接修订：<a href="docs/design/20261022-roami-agent-rsi/automation-roles.html">图表版架构与执行设计</a>以架构图、执行手段表和闭环条件明确角色；运行边界与模块折叠展示。控制器发起，被测Agent做题，Codex复盘并输出文档，Codex汇总Issue，Codex隔离修改，独立服务验收应用，后续两个合格日周期后控制器关单。本地角色链已接入，正式运行仍待用例和机器配置；总方案的历史技术契约保留在折叠附录。</p>
  <h3>首批实施记录 · 2026-10-23</h3>
  <p>范围修订：正式任务库存为60项（公开20、自有真实20、机制回归20），每天完整执行60项，并回顾所有指标与具体日志；新想法作为剩余预算内的额外开发实验，不替换正式题。机制回归优先使用无模型测试，不预占模型Token；所有测试机共享日预算。主动观察和源码补丁已接入，正式场景与真实模型验收仍未完成。</p>
  <p>已实现评测CLI、隔离文件运行、独立判定、成对比较、预算账本、每日worker与有限参数候选队列。4条公开财务组件合同已锁定，2条确定性设施任务已完成A/B；正式测试机、真实模型收益、完整60例及线上发布未完成。详见 <a href="docs/design/20261022-roami-agent-rsi/implementation.html">实施记录</a> 和 <a href="docs/development/agent-rsi.md">运行手册</a>。</p>
  <p>每日全量修订：规则回顾已逐项接入模型/工具具体日志，缺日志或覆盖不足不能记为当日完成。rsi-v1.3要求正式60项每天全跑，A/B共120次执行；预算不足不静默缩题。quick门禁915项Python通过，最终专项51项、前端910项及生产构建通过；手机组件使用隔离示例数据验证触控与回顾覆盖，真实模型成绩和完整自主源码修改仍未交付。</p>
  <p>验收：仓库quick门禁通过（896项Python测试、全量Go与前端静态检查）；最终记忆结算修订后专项50项通过。独立tmux实例已按身份清理，无真实模型收益分数。</p>

  <h3>自动研发实施 · 2026-10-23</h3>
  <p>ResearchWorkflow/ResearchWorker持久派发；behavior_observer逐项读证据；source_revision在detached worktree应用补丁；candidate_checks用冻结镜像、只读基线测试与独立私有门槛验证；release_observation仅绑定RSI runner，并在两个后续完整日周期后关单或退化回滚重开。原生模型费用与每日评测共用账本，未知调用不重放。源代码权限通过本机CLI配置，Web仅展示进度及恢复阻塞。设施测试不代表真实模型成绩；正式机器、60项材料、私有验证和预算仍须接齐。</p>
  <p>套件验收修订：daily_suite.py统一检查20公开/20自有/20机制配额、指定ID及固定来源；私有集禁止已知ID、cluster与完全相同输入重叠。authored-v3保护冻结输入，PPT对照原件并核对PDF，回测纠错核对因果重跑和退市资产。20机制容器回归与20判定器正反样例通过；5项复杂产物仍待校准评分。公开19项ID已选择，7项可执行合同；其余13项正式合同、私有验证和机器预算未齐。材料hash和精简验收表保存在上述docs入口。</p>
  <p>全链执行与日终修订：容器内启用Main→Native Worker→回报，工作区只绑定外层容器目录，不建立Go/tmux会话，内部waiting_user如实保留，最终由退出后的宿主评分器验收。评分耗时计入总交付时限；评分或用量未定、语义回顾缺项时daily_complete保持false。私有54项不同代码契约已按24/30划分并通过正反验收，不替代办公/GUI隐藏场景；公开合同增至12项，正式共52/60。一次真实预检返回HTTP401且用量未知，未自动重试或启用日程。最新状态和私有范围摘要见docs实施页。</p>
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

<section id="installed-agent-versions" lang="zh-CN">
  <h2>已安装 Agent 版本展示 · 2026-10-22</h2>
  <h3>产品设计与用户故事</h3>
  <p>进入 Agent 目录即可查看所有已安装程序的当前版本，无需逐个点检查；版本位于名称下方，以次要字号和颜色展示，登录状态独立保留在描述下方。桌面与手机使用相同信息顺序。版本读取失败显示“版本未知”，保留检查入口。安装、登录与版本读取保持独立状态，刷新失败保留最近目录。</p>
  <h3>技术设计</h3>
  <p>internal/agentinventory/professional-version.go 按 Agent 缓存默认程序的版本；发现时并行读取各 Agent，并发请求共享同一探测。单次 --version 保留 3 秒超时与 4 KiB 输出限制。成功缓存 5 分钟，失败缓存 1 分钟；文件变化与安装成功失效，显式检查立即重读。客户端直接采用服务端版本，避免旧的手动检查结果覆盖自动刷新的新版本；复用现有版本样式与中英文未知状态。</p>
  <h3>验收计划</h3>
  <p>覆盖四种程序自动版本、重复轮询、并发合并、读取取消、失败退避、显式重查、程序替换及卸载；执行仓库门禁与前端测试，在隔离实例验证本机实际版本，并在桌面和 Android 真机检查版本可见、详情返回与独立滚动。</p>
  <h3>验收记录</h3>
  <p>仓库 full 门禁、版本缓存竞态检查及前端 126 个文件、899 个用例通过；Python 867 个用例通过。首次门禁中已有 Claude 取消时序用例失败，单独连续 3 次及完整门禁重跑通过；生产构建保留已有大块体积提示。</p>
  <p>隔离 Go 服务在缺少 OpenCode 安装目录的 PATH 下自动返回四种本机已安装版本；桌面中英与深浅主题、Redmi Note 8 真机 392 CSS px / coarse 确认版本可见，真实手势滚动、详情点按与返回，无文档或横向溢出。截图保存在 /tmp/agent-versions-*，未部署到现用服务。</p>
  <p>版本位置修订：版本移至名称下方，与登录状态分开展示；复用字号、颜色和间距令牌。前端全部门禁及 899 个用例通过，桌面中文深色、英文浅色和 Redmi Note 8 真机验证位置、滚动、名称点按及详情返回。截图位于 /tmp/agent-version-placement-*。</p>
</section>

<section id="agent-upgrade-provider-presets" lang="zh-CN">
  <h1>Agent 升级与模型预设 · 2026-10-22</h1>
  <h2>产品设计</h2>
  <p>能力页 Agent 卡片提供“升级”和“模型”直接入口；管理详情保留版本、程序位置、终端和启动命令。升级遵循当前安装方式，原生安装的 Claude Code 与 OpenCode 使用原生升级器，npm 安装的 Claude Code / Codex / Pi 更新原安装前缀；无法识别的安装方式显示终端升级提示，不另装一份冒充成功。显式确认后升级，成功重新读取实际版本，失败保留原目录。</p>
  <p>模型页按 Agent 管理服务商预设，填写名称、服务地址、API 协议、模型、API Key 或环境变量引用。保存与应用分开，应用只修改原生配置中对应的连接和模型字段；保留 MCP、插件、hooks、权限、其他服务商及注释。密钥只写不读，留空保留已存密钥。显示实际生效状态和外部改动，不把保存预设当成调用已成功。支持恢复首次应用前的连接与模型字段；每次应用先备份，失败回滚，配置发生外部变化时保留表单并要求重新读取。应用影响后续启动，已有会话由各工具自行处理，不自动重启。</p>
  <p>桌面沿用详情弹窗中的模型区；手机在同一 URL 详情的全屏二级页展示，单返回栏、单滚动区，编辑区和保存动作遵循既有安全区与键盘规则。OAuth 仍在各工具终端登录；不代理协议、不复制订阅令牌、不提供未实现的自动故障切换。各工具只接受已验证的原生协议。</p>
  <h2>用户故事</h2>
  <ul>
    <li>我能升级当前真正使用的程序，并看到更新后的版本；不会因原生安装与 npm 并存而更新错程序。</li>
    <li>我能为不同 Agent 保存多个服务商与模型预设，确认后应用，切换后重开终端使用。</li>
    <li>我能恢复原连接和模型；其他工具配置和登录资料保持可用，失败不会清空输入或谎报已切换。</li>
    <li>我在手机上可以编辑、保存、应用和返回，API Key 不会在列表和重新打开的表单里回显。</li>
  </ul>
  <h2>技术设计</h2>
  <pre>internal/agentinventory/upgrade.go       固定升级计划、原程序解析、维护互斥与版本复查
internal/agentproviders/store.go         0600 预设目录、串行写、脱敏视图与按 Agent 隔离
internal/agentproviders/native-config.go 原生路径、受控字段变更与配置文件读写
internal/agentproviders/apply.go         修订冲突、备份日志、多文件回滚与中断恢复
internal/agentproviders/json-config.go   JSON / JSONC 的保留式字段修改
internal/agentproviders/codex-config.go  TOML AST 定位、精确修改和保留无关配置
backend/api/agent-providers.go           所有者鉴权下的大小限制、预设 CRUD、应用与恢复
frontend/src/components/capabilities/AgentModels.tsx 模型预设、失败保留、显式应用
frontend/src/agent-registry.ts               升级及模型配置的节点感知 API</pre>
  <p>预设位于当前节点 data root 的 agents/professional/provider-presets.json，不使用公开偏好存储保存密钥。所有写入均为临时文件 fsync 后原子替换，文件 0600、私有目录 0700；预设、单次请求和原生文件均有体积上限。API 只返回 hasKey 和白名单字段，原生解析错误不回显文件内容或密钥。</p>
  <p>原生路径尊重 CLAUDE_CONFIG_DIR、CODEX_HOME、XDG_CONFIG_HOME、OPENCODE_CONFIG、PI_CODING_AGENT_DIR。Claude 变更用户 settings.json 的模型与认证环境变量；Codex 变更 config.toml 的模型和受管 provider 表，保留 auth.json；OpenCode 区分 V1 / V2 的 provider 字段；Pi 写 models.json 和默认模型 settings.json。服务端修订值防止陈旧页面覆盖新配置；应用前生成私有恢复记录，多文件写入失败按已写入内容比较回滚，恢复时仅还原托管字段。</p>
  <h2>验收计划</h2>
  <p>隔离 HOME、Agent 配置与原生程序，覆盖安装来源升级、前缀、并发、取消和失败；四类预设增删改、重启恢复、秘密不回显、环境变量引用、应用和还原、原生格式及无关字段保留、外部修改冲突、落盘失败与恢复。执行 Go / 前端完整门禁及 Android 真机键盘、滚动、触控与返回检查；不升级本机现用程序，不应用到现用凭证。</p>
  <h2>验收记录</h2>
  <p>仓库 full 门禁通过，Python 867 个用例、前端 127 个文件 / 907 个用例通过；typecheck、i18n、hover 与生产构建通过，构建保留已有大块体积提示。Go 新增竞态测试覆盖四类预设、密钥不回显、外部变更冲突、两文件失败回滚、中断恢复及符号链接目录中首次建配置后的状态稳定；HTTP 验证请求限制、脱敏和应用状态，升级测试使用固定程序验证原生路径、npm 原前缀与维护互斥。</p>
  <p>隔离 Go 服务、HOME、私有 tmux 和固定升级程序完成四种 Agent 的保存、应用、恢复、升级后版本读取；已安装的 Codex 0.162.1、OpenCode 2.0.27、Pi 1.1.0 均成功读取生成的原生配置，未发起模型调用。OpenCode 原生服务使用独立配置与端口。</p>
  <p>桌面中文深色 / 英文浅色在 320、390、820、1100、1280、1600、1920 宽度无文档溢出。Redmi Note 8 真机以 392 CSS px / coarse 指针完成预设编辑、保存、切换、恢复、Android 返回及升级确认；键盘 314px 时保存按钮位于键盘上方，触控高度 44px，四个底部主入口恢复正常。截图与验收脚本在 /tmp/agent-models-*，现用服务及用户原生配置未修改。</p>
</section>

<section id="roami-rsi-development-only" lang="zh-CN">
<h2>RSI开发版边界修订 · 2026-10-23</h2>
<p>RSI仅在显式development编译通道运行；普通安装版不构造服务、worker、接口或策略绑定，旧enabled设置不生效，入口由当前节点状态控制。改进只应用于开发评测实例，经正常审阅发布后交付用户。无版本差异每日60次，候选对照120次；全部指标与日志仍逐次复盘。</p>
<p>当前60/60项正式合同已备：公开20、自有40；75份来源材料固定hash。公司原生RocketChat/ownCloud与GAIA官方课程公开样本已接通，退出后状态、正确/错误产物及Main/Worker日志验收通过。7项复杂产物（自有5、公司2）仍待独立质量评分；测试机与日预算未绑定，尚无真实完整日或收益结论。详见<a href="docs/design/20261022-roami-agent-rsi/implementation.html">当前实施与验收</a>。</p>
<p>本轮验收：Go与full门禁通过，Python1086项，前端918项及生产构建通过；桌面和Redmi真机验证普通版无入口、深链回退且不请求RSI接口，开发版可进入。界面检查使用隔离数据，不计作真实Agent成绩。</p>
</section>

<section id="roami-rsi-daily-v1" lang="zh-CN">
<h2>RSI首版自动执行 · 2026-10-24</h2>
<h3>产品设计与用户故事</h3><p>开发版每天03:00由内置定时器发起完整60项，不依赖聊天或用户使用记录。程序出分、复盘Agent逐项看指标与日志，创建去重内部问题单；修复Agent独立worktree改允许范围的运行时代码，独立验收后自动提交草稿PR（显式配置GitHub目标），人工审阅合并。仅开发评测实例自动应用并观察，两次后续完整日后才关单，退化回滚重开。</p>
<h3>技术设计与模块</h3><pre>EvaluationWorker → ResearchWorkflow / behavior_observer → source_revision
→ candidate_checks（原问题、回归、全量与私有配对）
→ github_publication（重验证据、quick/full、专用分支、草稿PR与截图）
→ release_observation（开发评测实例、后续全量观察、关闭/回滚）</pre>
<p>GitHub配置位于账本旁的私有review-publication目录，缺省不向外写入。创建请求断线先读远端对账，未确认结果不重复POST；不自动合并，不上传原始日志、隐藏答案或凭证。OpenCode和Pi托管任务采用原生JSON进程加常驻控制器，续聊绑定原生ID；完成确认进程退出与无额外写进程。OpenCode2额外核对精确会话导出的提示词、完成状态与时间，禁止用旧结果冒充新完成。</p>
<p>7项复杂产物已接离线渲染和独立双评分，但本机容器runner已登记，真实校准和日预算尚未齐，不能宣称每日评测已经启用。详见<a href="docs/design/20261022-roami-agent-rsi/automation-roles.html#first-version">首版运行图表</a>及<a href="docs/development/agent-rsi.md#daily-v1">操作手册</a>。</p>
</section>

<section id="roami-rsi-codex-period" lang="zh-CN">
<h2>RSI Codex 三角色与汇总 Issue · 2026-10-24</h2>
<h3>产品设计</h3><p>复盘、Issue、修复固定三个Codex角色。完整复盘列全部待修点，全机完成后每天只发一个GitHub Issue，确认回执后按条目修复。独立验收后发回链草稿PR，两个后续完整周期观察通过才勾选，全部完成关Issue，退化回滚重开。普通安装版不运行。</p>
<h3>用户故事</h3><p>按每日自动执行要求，每天03:00完整跑60项；人查看每日报告、Issue和PR，审阅合并，不逐日派任务。未确认预算与评分校准之前保持停用。</p>
<h3>技术设计</h3><p>behavior_observer最多4项一批，保护题隔离；codex_roles使用只读无工具的原生CLI，记录thread ID、JSONL与用量。review_report和ResearchWorkflow持久保存全量文档与全机汇总；github_issues对账、发布确认并同步清单，source_revision只应用校验补丁。一次只观察一个源码候选，防止后续修复覆盖观察版本。CLI无供应商侧总Token硬截断保证，超额或未知调用阻止后续付费执行。</p>
<p><a href="docs/design/20261022-roami-agent-rsi/automation-roles.html">精简图表设计</a> · <a href="docs/development/agent-rsi.md#codex-roles">配置、预算与恢复</a>。本机真实Codex协议检查已获得原生完成与用量，未执行完整60项；合并主线后quick/full通过（Python1232项），前端952项及生产构建通过；桌面与Redmi真机验证完整复盘、Issue链接、44px触控、单返回栏与无溢出。GitHub写入为固定响应设施验收，真实完整60项和正式日程仍未启用。</p>
</section>

<section id="professional-agent-model-picker" lang="zh-CN">
  <h2>Agent 模型下拉选择 · 2026-10-22</h2>
  <h3>产品设计与用户故事</h3>
  <p>四类 Agent 的模型字段统一为可搜索、可手动输入的下拉框，保留已有模型和未保存输入。用户可点击“获取模型”，按当前服务地址、协议和密钥读取真实模型列表；修改连接信息后清空旧服务返回的候选，失败保留模型选择及表单。服务不支持列模型时允许继续输入自定义模型。</p>
  <h3>技术设计</h3>
  <p>AgentModels.tsx 复用 antd AutoComplete，候选来自同服务已有预设和显式查询结果。新增 POST /api/agent/professional/:kind/model-options，复用预设私有密钥和输入验证；按协议读取 OpenAI / Anthropic 兼容的 GET models，Anthropic 支持分页。请求有时限、响应和条目上限，不跟随重定向、不返回上游错误正文、不执行模型推理，不新增轮询或隐式应用。网络读取在预设锁外执行；变更连接会取消旧请求并丢弃过期结果。</p>
  <h3>验收记录</h3>
  <p>仓库 full 门禁及 Go 竞态测试通过；前端 127 文件 / 913 用例、typecheck、i18n、hover 与生产构建通过。覆盖四类 Agent、保存密钥和环境变量、Anthropic 分页、连接取消、失败保留、重定向及响应限制；Python 按仓库改动范围规则跳过，构建保留已有大块体积提示。</p>
  <p>隔离 Go / HOME / 原生配置 / tmux 和本地模型服务完成四类 Agent 查询、下拉选择、自定义保存及刷新恢复。桌面中英文深浅主题在 320–1920 宽度无文档溢出；Redmi Note 8 真机以 coarse 指针完成查询、搜索、Android 原生点按候选、保存、刷新与返回，键盘 314px 时输入位于可见表单内、保存高度 44px 且不被遮挡。截图和脚本位于 /tmp/model-picker-*，未改动现用服务和原生配置，未调用推理接口。</p>
</section>

<section id="task-native-session-design" lang="zh-CN">
  <h2>任务会话与 native 托管设计 · 2026-10-22</h2>
  <p>设计与实施记录。完整 HTML 入口：<a href="docs/design/20261022-任务会话与工作习惯/index.html">任务、会话与工作习惯</a>；<a href="docs/design/20261022-任务会话与工作习惯/verification.html">原型验证记录</a>；<a href="docs/design/20261022-任务会话与工作习惯/implementation.html">实际实现与验收</a>。</p>
  <h3>产品设计</h3>
  <p>首页中间保留 Main，右侧任务栏展示任务及可点击项目归属；进入会话直接打开绑定原会话。用户确认结束前保留原身份与筛选；工作习惯只影响新任务，续改复用原工作区和智能体。</p>
  <h3>用户故事</h3>
  <p>用户能从首页直接进入专业或 native 会话，补充修改后仍回到原任务；也能点击项目名进入所属项目，返回保留筛选、搜索和位置。</p>
  <h3>技术设计</h3>
  <p>native 拟统一托管在 ~/.roami/agents/native/时间戳-随机后缀/，以 .session.json 记录身份关联、.chat.jsonl 记录对话和工具调用，context 与 blobs 保存检查点及大输出。现有 SQLite 继续负责在线事务与调度，事务 outbox 串行补写日志；关闭保留记录，恢复不重放工具副作用。模块、接口、迁移与故障验收在完整稿中定义。</p>
  <h3>设计验证</h3>
  <p>Chrome 原型 51 项、Android 真机 9 项检查通过；仅验证设计交互、布局和示例记录格式，不代表真实文件托管、数据库迁移或故障恢复已实施。</p>
</section>

<section id="task-native-session-implementation" lang="zh-CN">
<h2>native 会话托管实施 · 2026-10-22</h2>
<p>首页任务栏与详情直达原会话和项目；桌面在 Main 右侧打开 native，手机为全屏单返回栏。记住筛选、选择、位置及草稿；等待验收与终态详情不轮询。项目目录提供 native 入口，不移动首页任务主列表。</p>
<p>schema 12 登记稳定 native 身份和父子关系，以同事务 outbox 生成私有 JSONL、校验 gzip 分段；七天前正文在无在途 turn、保留最近两轮且可精确恢复时改为认证引用。备份格式 3 同时包含数据库、native 目录和附件；关闭保留历史，恢复不重放工具。采用带来源、修订与有效范围的工作习惯，只影响新项目任务，续改保持原 Agent / branch / workspace。</p>
<p>设计原型与真实实现的目录、接口和验收差异见上述实际实现 HTML；开发文档中文是 i18n 例外，产品文字均走 i18n。代码未部署。</p>
</section>

<section id="duplicate-preference-reconciliation" lang="zh-CN">
  <h2>重复偏好记忆修复 · 2026-10-22</h2>
  <h3>产品设计</h3>
  <p>显式记忆请求即时保存，后台提取不因标题不同或包含“帮我记下”前缀再增加一条有效记忆。确认为个人长期偏好后保留长期记录，对话副本转为历史记录，保留来源和删除／忘记关联。启动时整理已有提升关系中同源、同内容的重复副本，不做模糊语义合并。</p>
  <h3>用户故事</h3>
  <p>用户说一次记住偏好，列表和召回只得到一条有效记忆；重复后台提取不增加副本。历史来源可追溯，删除后不回退到旧副本；不同内容、来源、项目和任务保持各自范围。</p>
  <h3>技术设计</h3>
  <p>memory/intake.py 复用显式请求正文解析；memory/preference.py 在现有来源校验下按正文、来源 ID 和指纹匹配，复用已有记录或提升后 supersede 本地副本；memory/jobs.py 在提取提交和启动恢复时调用。保留 memory_edges，更新 memory_epoch，写入沿用数据库事务。历史整理仅处理已有提升关系、范围一致且长期目标仍有效的记录，不增加轮询或模型调用。</p>
  <h3>验收记录</h3>
  <p>仓库 full 门禁通过，Python 全量 880 个用例通过；记忆相关 57 个用例覆盖新写入、重复提取、历史整理幂等、来源、范围、过期及删除关联。隔离 Unix HTTP 服务配合固定模型响应验证截图原文只返回一条长期偏好、来源未变、跨用户不可见及删除后零条；历史种子从两条整理为一条。验收文件为 /tmp/duplicate-memory-acceptance.json 与同名 PNG，现用服务和记忆未修改。</p>
</section>

<section id="memory-browsing-design" lang="zh-CN">
  <h1>记忆浏览设计 · 2026-10-22</h1>
  <div id="memory-browsing-prototype">
    <p>运行 <code>cd frontend &amp;&amp; node scripts/build-memory-design.mjs</code>，生成 /tmp/memory-browsing-design.html 与独立原型。原型复用项目主题、i18n、图标、断点与 MobileSubPage，只使用内存示例，不连接业务 API，也不保存生产偏好。</p>
    <p><a href="/api/file/serve/tmp/memory-browsing-design.html">打开设计与可点击原型</a></p>
    <iframe title="记忆浏览原型" src="/api/file/serve/tmp/memory-browsing-prototype.html" width="100%" height="760" sandbox="allow-scripts allow-forms"></iframe>
  </div>
  <h2 id="memory-browsing-product">产品设计</h2>
  <h3>问题与目标</h3>
  <p>现有目录把类型“偏好”与范围“个人／对话／项目／任务”放进同一筛选；同一行反复展示标题、正文、展开和来源按钮。列表内展开挤乱阅读位置，手机来源弹窗截断长内容。统一目标是让用户快速回答：记住了什么、适用于哪里、来自哪句话、如何纠正。</p>
  <h3>入口与信息架构</h3>
  <p>桌面首页保留右侧“任务／消息／记忆”工作台；记忆头部的展开入口进入完整浏览，设置旧入口继续兼容。手机从已有记忆入口打开全屏二级页，不增加主导航项。目录默认“已记住”，旁边为“待确认”和“每日足迹”；“待确认”同时容纳候选与冲突，冲突显示文字提示，计数为零则隐藏。足迹是使用统计，不混入可复用记忆。</p>
  <p>首层只放搜索和范围选择，默认全部范围。个人长期、项目、对话、任务是范围；偏好、事实、决策、摘要是类型，收进可展开筛选。选择项目／对话／任务范围后，完整实现提供对应实体选择，不能把“范围类别”冒充某个实体。“对话”筛选指存放在该对话的记忆；个人长期单独列出，不用“当前可用”暗示当前回答已采用。</p>
  <h3>列表与详情</h3>
  <p>列表使用平面行：短标题、最多两行正文摘要、适用范围和更新时间。去掉日期主分组、永久总数栏、每行来源与展开按钮；整行可键盘和触摸打开详情。非当前范围显示具体项目／对话／任务名称，缺失名称显示“来源不可用”等可读状态，完整 ID 仅在技术详情中。搜索支持标题、正文，范围选项和类型共同过滤，空结果提供清除筛选；只有一页时不显示分页。</p>
  <p>完整桌面浏览为列表与详情并排，两区独立滚动；窄工作台在同一面板内从列表切详情，返回恢复筛选和滚动位置，不新增第三栏。详情依次呈现完整内容、真实状态、适用范围、来源原文和折叠变更记录。个人长期说明“可在其他对话中检索使用”，不声称每次都会使用，也不填造召回次数或最后使用时间。</p>
  <p>来源在详情中直接预览原句、对话名称和时间，打开来源对话定位原消息；返回记忆恢复位置。多来源分别展开，来源变化或不可用显示相应状态和恢复动作，不清空记忆正文。归并的旧对话副本放进变更记录，只保留一条有效目录项；不在客户端做模糊去重，不隐藏未确认的真实冲突。</p>
  <h3>待确认、删除和足迹</h3>
  <p>候选详情先展示内容和来源，再确认记住或拒绝。冲突同时展示现有记忆与待确认内容，确认替换前使用短确认框，旧版本保留。来源变化需重新核实，不能在未加载可靠来源时确认。删除记忆与彻底忘记继续放在更多菜单，确认文案明确“保留来源”和“屏蔽后续上下文”的区别，沿用后端真实语义；失败保留列表、详情和选择，不伪报成功。</p>
  <p>每日足迹按日期、项目浏览，列表仅呈现对话轮数和任务完成数，详情展开已有活动统计；没有记录的指标显示“未记录”，不补零。原型使用明确的示例统计，不推断生产活跃度。</p>
  <h3>手机与状态反馈</h3>
  <p>列表、记忆详情和来源对话都是 URL 管理的全屏二级页，只使用一层等高返回栏及一个内容滚动容器，保留四个底部入口。返回不叠加 overlay history；候选确认栏位于滚动区外，由 MobileSubPage 统一避让安全区和键盘。搜索、过滤、详情返回保留当前位置。图标有可访问名称，触控目标至少 44px，悬停只对鼠标生效。加载采用占位；后台更新失败保留最近列表，显示短错误和重试，不新增永久刷新按钮。</p>
  <h2 id="memory-browsing-stories">用户故事</h2>
  <ol>
    <li>我在工作台扫一眼就能看懂已保存的偏好和适用范围，不必逐条展开，也不会看到归并后的两条副本。</li>
    <li>我可以搜索 Codex，点开记忆看到原话及来源对话；查看来源后返回原来的列表位置。</li>
    <li>我可以区分个人长期与某个项目／对话／任务的规则，不误以为已保存就意味着每次回答都会采用。</li>
    <li>我能查看待确认内容，发现与现有偏好冲突时先对比原文，再决定替换或拒绝；网络失败不丢失当前查看内容。</li>
    <li>我在手机上能完成搜索、筛选、读全文、查看来源、返回与删除确认，长内容不被小弹窗截断。</li>
    <li>我可以单独查看每日足迹；它不挤占偏好和知识的目录，不把未知统计当作零。</li>
  </ol>
  <h2 id="memory-browsing-technical">技术设计</h2>
  <h3>代码与模块架构</h3>
  <pre>frontend/src/components/agent/
AgentMemory.tsx            视图、范围／类型筛选、URL 和选择状态
MemoryList.tsx             平面列表、搜索结果、分页与滚动恢复
MemoryDetail.tsx           全文、范围、来源、候选／冲突与操作
memory-record.ts          目录、详情、来源与活动的类型及格式
useMemoryCatalog.ts        节点／所有者／筛选缓存、过期结果隔离与请求合并
agent-memory-events.ts     复用会话事件失效缓存，刷新已挂载目录
memory-browser-route.ts    复用 agent-page-route 的入口、详情和来源深链
MobileSubPage              手机唯一返回栏、滚动区、键盘与安全区
prototypes/memory-browser.tsx       本轮隔离交互稿
prototypes/memory-browser-data.ts   明确的示例来源与冲突数据
scripts/build-memory-design.mjs     从本节提取设计并打包单文件 HTML</pre>
  <h3>查询、状态与接口边界</h3>
  <p>沿用 GET /memories/catalog、GET /memories/{id}/sources、POST /memories/{id}/confirm 和 DELETE /memories/{id} 的所有者与范围边界。目录状态名映射为已记住 active、待确认 candidate＋conflict、每日足迹 category=activity；候选＋冲突必须在服务端统一筛选、排序、计数和分页，不能客户端分别抓一页再拼接。范围类别筛选同样在服务端分页前处理，具体实体继续传 projectId／conversationId／taskId，类型单独使用 kind。</p>
  <p>已补充只读详情 GET /memories/{id}/detail 与按需历史 GET /memories/{id}/history，支持 active／candidate／conflict 的详情与关联当前版本，返回可读实体名称、来源状态和受所有者约束的归并／修订历史。历史只沿可信 canonical_key、supersedes_id、memory_edges 及相同来源指纹追踪，不因共享一条来源就把不同内容合并为版本。来源证据加载及确认提交继续复验，客户端不从标题或摘要推断冲突。原 GET /memories/{id} 的有效记录语义保持；目录新增 state=review 与 scope，GET /memories/facets 返回同一视图下的可读实体选项及待确认数量。确认提交携带 expectedCurrentId，来源及版本变化返回冲突，保留当前内容供重新核实。</p>
  <p>扩展现有 home/memory/{origin} 路由的记忆详情／来源状态，保留节点参数和来源返回路径；旧 settings/agent/memory 链接映射到完整目录。筛选保存在 URL，草稿和滚动按节点／视图保留；回退、刷新和横竖屏不丢选中项。复用已有事件与可见性刷新，不新增逐条轮询；详情与来源按需加载，忽略过期结果并合并并发请求，辅助失败不覆盖正文。未知召回关系不展示，真实召回证据仍从对应回复的执行记录查看。</p>
  <h3>设计阶段交付与验收边界</h3>
  <p>设计阶段交付可点击示例原型；以下为原型阶段的隔离边界，正式实现见落地修订。原型复用项目主题令牌、图标、全局 i18n、useLayout 与 MobileSubPage；中英文切换只翻译界面，示例用户原文保留中文。浏览器原型使用 sandbox、内存偏好和禁出网 fetch，不写实际服务配置。底部主导航为宿主环境示意，本轮可操作范围为记忆浏览及其详情、来源、筛选、候选确认、删除和返回。开发者设计正文使用中文，属于 i18n 文档例外。</p>
  <p>验收计划：桌面完整浏览与工作台、手机真机搜索／筛选／返回／滚动／键盘；中文深色和英文浅色；加载、失败与空结果；确认替换、拒绝、删除取消及来源变化；页面无文档或横向溢出。原型验证不等于业务接口已实现，落地验收另需服务端范围与分页、所有者隔离及来源失效测试。</p>
  <h3>原型验收记录</h3>
  <p>前端 typecheck、i18n（3471 个键）、hover、127 个测试文件／907 个用例和生产构建通过，构建保留已有大块体积提示。桌面验证目录／详情、工作台内返回、搜索空态、冲突对比及确认取消、拒绝、来源跳转、变更记录与活动详情；中文深色和英文浅色各在 320、390、820、1100、1280、1600、1920 宽度检查，共 14 组无文档或横向溢出，浏览器无脚本错误。</p>
  <p>Redmi Note 8 真机以 392 CSS px／coarse 指针验证真实触摸命中、来源对话、Android 返回、候选对比及滚动；展开长内容后滚动由 0 变为约 136px。隔离 HTTPS 预览中实测键盘 314px，--kb 同步、底栏隐藏、搜索保持可见。静态原型启动与真实应用一样启用 VirtualKeyboard 覆盖模式；真机键盘验收使用安全上下文，不以 HTTP 预览替代。</p>
  <p>设计、独立原型与截图为 /tmp/memory-browsing-*；校验记录含 validation.json、width-validation.json 和 phone-validation.json。产物仅使用示例内容，未替换生产页面或修改生产记忆。</p>
  <h3>落地修订 · 2026-10-22</h3>
  <p>用户确认后，实际 AgentMemory 已替换为同一套目录／详情组件，完整页面、桌面工作台和手机入口共用查询与路由。删除旧卡片组件和样式；完整页面打开期间只保留原对话事件连接，不再挂载隐藏的第二份记忆工作台。旧设置地址继续显示完整目录。范围、类型、实体、搜索、分页与选中项进入 URL，搜索和筛选替换当前记录，选择详情增加一条历史；Android 返回逐层恢复，列表滚动按节点及筛选保留。</p>
  <pre>agent-runtime/src/roami_agent/memory/
  catalog.py       服务端范围类别、候选并集、计数分页与实体目录
  detail.py        所有者隔离的详情、当前版本、精确归并与修订历史
  evidence.py      有界来源原话、来源变化和不可用状态
  preference.py    同一来源／相同正文的偏好复用与旧副本归并
  records.py       确认的版本守卫与原有删除／彻底忘记语义
server/http.py → Go /api/agent 网关 → 上述目录与详情服务</pre>
  <p>历史只读展示最近 50 项，并如实标明截断；归并仅认明确关联、同一所有者、相同来源指纹及去除“记住”前缀后完全一致的正文。遗漏或已彻底忘记的来源同时退出目录、历史和候选计数。来源不可用时仍可阅读待确认正文，但不能确认；服务端提交再次校验来源和当前版本。目录无常驻轮询，复用现有会话记忆事件和可见性更新，历史只在展开后加载。</p>
  <p>运行验收使用 /tmp/roami-mem-browser 内的独立配置、数据库、Unix socket 与私有 tmux 服务，Go 网关对接实际 Python 运行时；注入确定性模型和示例来源，未使用生产模型凭证，也未改写生产记忆。质量脚本修正了删除旧组件后仍扫描不存在文件的问题。</p>
  <h3>实现验收记录</h3>
  <p>PR 整合复查补充：终端标签恢复与变更仅覆盖 terms／active，并保留当前 URL 的记忆筛选、页码和选中项；回归覆盖初始化、异步恢复及随后切换终端标签，避免刷新后丢失记忆深链。</p>
  <p>桌面真实服务已验证单条偏好及归并历史、来源跳转与浏览器返回、活动详情、旧设置链接、候选冲突对比及取消。中文深色、英文浅色分别检查 320、390、820、1100、1280、1600、1920 七档宽度，14 组均无文档或横向溢出。工作台详情替换列表，返回后滚动位置由 380px 恢复为 380px；模拟删除请求失败时，正文和选中项保留。</p>
  <p>Redmi Note 8 真机在 392 CSS px／coarse 指针下完成真实触控搜索、来源跳转、Android 返回、候选确认、冲突取消与删除取消。HTTPS 键盘实测 314px，搜索框可见且底栏隐藏；长详情真实手势滚动约 450px。手机只有一个返回栏和一个内容滚动容器，底部四个主入口均完成真实点按，关键控件命中区至少 44px，安全区正常，无横向或文档滚动。</p>
  <p>前端 128 个测试文件／913 个用例通过；typecheck、i18n（3483 个键）、hover 与生产构建通过，保留已有大块体积提示。Go 测试和 887 个运行时用例通过，覆盖候选并集分页、独立范围、不放宽召回、来源失效、当前版本冲突、所有者隔离、忘记后的隐私及精确历史；full 门禁通过，最终记录为 /tmp/memory-browser-quality-accepted.log。实现仍在独立工作区，未自动部署至正在使用的服务。</p>
</section>

<section id="agent-runtime-distribution-design" lang="zh-CN">
  <h1>一条命令安装 Roami · 2026-10-23</h1>
  <p>状态：已实现，安装与守护验收见本节末尾；尚未合并发布到公开安装入口。</p>
  <h2>产品设计</h2>
  <h3>用户只执行一条命令</h3>
  <pre><code>curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash</code></pre>
  <p>沿用当前仓库与入口。macOS、Ubuntu 用户使用同一条命令；无需 clone 仓库，无需安装 Python、uv、pip、Node 或 Go，无需激活 venv 或手动拉起智能体服务。bash 不直接下载 URL，因此公开入口采用 curl 下载并交给 bash。模型服务凭证仍由用户在网页设置中填写。</p>
  <p>安装器自动识别系统及 CPU，下载完整包，安装私有运行时，注册现有 systemd／launchd 服务，启动并验证本机模型设置接口。成功后只显示访问地址、首次设置登录口令的提示和日志位置。重复执行同一命令即升级；默认不要求用户选择安装类型或 Python 版本。</p>
  <h3>推荐决策</h3>
  <table>
    <thead><tr><th>方式</th><th>用户体验</th><th>结论</th></tr></thead>
    <tbody>
      <tr><td>完整包带 Python、应用 wheel 和依赖 wheel</td><td>一次下载；环境安装不再访问 PyPI</td><td>默认方案</td></tr>
      <tr><td>安装器在线下载 uv／Python，再安装依赖</td><td>命令也只有一条，但依赖多个外部下载源</td><td>可作为开发路径，不作为默认发布安装</td></tr>
      <tr><td>直接压缩构建机的 venv</td><td>携带绝对路径和平台绑定，换目录容易失效</td><td>不采用</td></tr>
    </tbody>
  </table>
  <p>默认包携带固定版本的 CPython 独立发行版；在用户机器的最终安装目录创建 venv，再使用包内 wheel 离线安装。包体积、下载时间和安装磁盘占用由实际构建测量，本方案不预报数字。运行时环境准备完成后不再移动目录。</p>
  <h3>边界与失败反馈</h3>
  <p>“无需预装开发工具”限定为 Roami 与智能体运行时；现有会话功能所需 tmux 继续由安装器探测并按系统安装，必要时明确提示包管理器权限。Chrome、ADB、KVM 沿用可选功能策略，其安装失败不伪报智能体安装失败。完整包下载后，Python／依赖安装可断网完成，不等于 Chrome、tmux 等宿主工具也离线可装。</p>
  <p>下载、校验、建环境或预检失败时保留现有版本，报出失败步骤和重试入口；首次安装失败不得打印“完成”。模型尚未配置时设置表单应可打开；服务故障与模型连接／认证错误分开显示。安装完成不声称用户已配置模型或可使用未登录的专业 Agent。</p>
  <h2>用户故事</h2>
  <ol>
    <li>第一次安装的人复制一条命令，结束后直接打开网页填写模型地址和密钥。</li>
    <li>没有 Python、uv、Node、Go 的 Mac 或 Ubuntu 机器，也能安装并打开智能体设置。</li>
    <li>已有用户再次执行原命令升级，配置、登录口令、对话和模型密钥保留。</li>
    <li>准备新版本时断网或依赖损坏，旧版本继续可用，重新执行命令能重试。</li>
    <li>重启电脑或智能体进程崩溃后自动恢复，用户无需再运行第二条启动命令。</li>
  </ol>
  <h2>技术设计</h2>
  <h3>发布资产</h3>
  <p>发布四份完整资产：roami-linux-amd64.tar.gz、roami-linux-arm64.tar.gz、roami-darwin-amd64.tar.gz、roami-darwin-arm64.tar.gz。当前裸二进制保留为高级使用入口；安装器默认选择完整包，不悄悄退回缺少运行时的裸二进制。</p>
  <pre>roami-&lt;os&gt;-&lt;arch&gt;.tar.gz
  bin/roami                     Go 主程序，继续内嵌前端
  runtime/python/               固定构建的 CPython 3.12 独立发行版
  runtime/wheels/               roami_agent 及全部生产依赖 wheel
  runtime/requirements.lock.txt  从 uv.lock 导出的构建输入与上游哈希
  runtime/requirements.txt       当前平台实际 wheel 的精确版本与哈希
  runtime/pyproject.toml         运行时识别与构建元数据
  manifest.json                 版本、源提交、目标平台、文件哈希、Python 构建、协议版本
  licenses/                     Python 与依赖发行许可
  runtime/.venv/                目标机生成，不在压缩包中</pre>
  <p>构建固定 Python 补丁版本与独立发行版构建号，不使用浮动 latest。现有 uv.lock 是唯一依赖解析来源，导出生产依赖，排除 pytest、ruff 等开发组；构建包含 migrations 和 Skill 资源的非 editable 应用 wheel。每个平台收集匹配 ABI／架构的全部 wheel；缺少 wheel 时构建失败，不能把源码编译留给用户。Linux 的 glibc 下限与 macOS 最低版本根据实际 Python 和 wheel 清单锁定，并以相应系统实测后公布，不把 Linux 包声称为支持 Alpine/musl。</p>
  <h3>安装与目录</h3>
  <pre>~/.local/bin/roami                 稳定入口
~/.local/share/roami/
  releases/&lt;version&gt;-&lt;manifest-hash&gt;/
    bin/roami
    runtime/python/
    runtime/.venv/
    manifest.json
  current                         原子切换的已验证版本指针
~/.roami/                         原有用户配置、模型密钥、数据库、会话与附件</pre>
  <p>系统级安装按实际服务用户解析安装根，保留现有 ROAMI_* 自定义存储路径，不把运行时目录与用户数据库混在一起。运行时查找优先显式 --runtime-dir／ROAMI_AGENT_RUNTIME，再找当前发布目录的 runtime，最后保留源码开发路径。服务启动使用绝对路径，不依赖交互 shell 的 PATH、activate 或工作目录。</p>
  <ol>
    <li>安装互斥锁防止两个安装器同时激活；解析一次具体 release tag，包和校验清单取自同一 release，禁止下载过程中多次解析 latest。</li>
    <li>下载到临时文件，核对摘要及 manifest 平台、版本与路径；拒绝越界归档条目。生产发布必须同时具备主程序和运行时资产。</li>
    <li>把新版本解压到不会再改名的独立最终目录，先标记未完成。使用包内 Python 创建 .venv，通过 ensurepip 和本地 wheel 离线安装精确依赖；无需用户安装 uv 或系统 Python。不写系统 site-packages。</li>
    <li>用候选程序执行原有存储布局预检；在临时配置、数据库、私有 tmux 服务和 socket 下完成初始化及模型设置 GET/PUT/重启恢复预检，不使用真实用户的模型凭证或数据库。</li>
    <li>预检成功后标记 ready。等待现有智能体空闲并有序停止本安装管理的服务；有在途任务或服务归属不明时中止激活并给出重试说明，不终止用户任务。</li>
    <li>必要时先做一致性存储备份，再原子切换 current，同时切换 Go 与 Python 版本；注册／重启原有 systemd 或 launchd 服务。首次从普通二进制入口迁入版本目录时保留原程序备份。</li>
    <li>检查主服务及智能体状态、实际模型设置接口。未配置模型时也必须返回可填写的设置。无服务管理器环境给出明确的前台启动方式，不声称已注册开机启动。</li>
  </ol>
  <p>准备阶段失败不触碰旧版本。激活后失败需区分数据库迁移：未迁移可回切旧程序；已经迁移则先停止新写者，通过现有存储备份恢复完整实例后再回退，禁止只切旧程序读取新 schema。保留上一份可用发布目录；清理必须避开 current、上一版本及仍有进程引用的环境。首版自动回退只承诺已验证的备份／迁移路径，未知写入状态保留现场并报恢复步骤。</p>
  <h3>运行时生命周期</h3>
  <p>Go 主进程统一管理智能体子进程，覆盖安装版、自定义目录启动和 start.sh 开发路径。systemd／launchd 仍只管理一个 Roami 服务，不另让用户配置 Python 服务。默认启动仅运行已准备好的环境，不在服务启动时下载或安装依赖。</p>
  <p>主服务启动时先解析同实例存储、取得运行时独占锁，再启动 Python，等待私有 socket 就绪；异常退出有退避重启。SIGTERM 时先停止接收新工作，按既有任务语义关闭并等待子进程退出。父进程意外死亡通过继承的存活管道关闭通知子进程退出，不能只依赖 Linux 专有机制；运行时锁保证旧写者未退出时不会启动第二个写者。只回收自己启动且身份匹配的子进程，不接管或终止手动启动的运行时。</p>
  <p>Go 与 Python 使用同一实例路径和 Unix socket 解析规则，覆盖 macOS 长 HOME 和 Linux XDG_RUNTIME_DIR 不一致场景；超长路径必须有同用户私有短路径策略或明确可恢复错误。hub 模式不启动本机运行时。独立 roami agent serve 保留供开发与诊断使用，并与自动管理共用单实例锁。</p>
  <h3>代码与模块架构</h3>
  <pre>.github/workflows/release.yml        四平台原生构建／验收与完整资产发布
scripts/build/build-agent-bundle.sh  Python、应用 wheel、依赖 wheel 和 manifest
scripts/build/build-roami.sh         保留 Go／内嵌前端构建
install.sh                          单命令入口、预检、准备／激活与服务登记
scripts/install/agent-environment.sh 目标目录建 venv 和离线依赖安装
cmd/roami/agent.go                  发布目录发现、setup 和 init 兼容
cmd/roami/agent-supervisor.go        Go 管理运行时进程、就绪、退避与停止
cmd/roami/main.go                   standard 启停接入，hub 排除
agent-runtime/src/roami_agent/app.py 运行时锁、父进程存活管道和有序退出
frontend/.../agent-models.ts         区分运行时不可用与模型服务错误
scripts/dev/selftest/agent-install.sh 全新／重复／失败安装回归</pre>
  <h3>实施顺序与验收</h3>
  <p>按“完整资产构建 → 目标机离线环境准备 → Go 生命周期 → 安装器接入 → 错误提示 → 四平台安装验收”实施；这些是开发步骤，最终用户始终只有同一条命令。</p>
  <ul>
    <li>Linux amd64／arm64 与 macOS Intel／Apple Silicon 均使用原生系统验证；至少在干净 Ubuntu 和真实 macOS 完成从公开安装入口到打开设置页的完整流程。</li>
    <li>验收机无预装 Python／uv／Go／Node；完整包下载后禁用外网仍可创建环境、启动服务。生产包不含构建机路径、editable 指针或开发依赖。</li>
    <li>未配置任何模型时设置 GET 成功；用本地模型 fixture 验证配置保存、模型列表、真实对话和重启恢复，不调用付费模型。</li>
    <li>重复安装、同版本重试、升级、下载中断、哈希错误、缺 wheel、环境创建失败和启动失败均有明确结果；准备失败保持旧服务和数据。</li>
    <li>验证路径含空格、长 HOME、自定义数据目录、systemd／launchd 环境、父进程崩溃、重复启动与子进程恢复；不泄漏第二个运行时或改动用户 tmux 服务。</li>
    <li>迁移升级单测和真实备份恢复；同一命令升级后原有口令、模型设置和对话仍可读取。完成仓库 quick／full 门禁及受影响前端检查；真实公开资产尚未发布前明确标记为本地候选验收。</li>
  </ul>
  <h3>实施修订与验收 · 2026-10-23</h3>
  <p>完整包固定 CPython 3.12.13，发布 CI 固定 uv 0.11.2。应用构建为普通 wheel，生产依赖从 uv.lock 导出并带哈希；包内携带 wheel、Python 及许可，目标机通过包内 Python 的 venv／pip 离线创建环境，不依赖系统 Python 或目标机 uv。实际目录为 releases/&lt;archive-sha256&gt;，安装完成后不移动环境。</p>
  <p>原生 CI 发现的兼容修订：macOS 的 /var 与 /private/var 是同一目录，安装测试根统一解析真实路径。cryptography 49 起停止发布 Intel Mac wheel；Intel 构建机使用锁定源码构建当前版本，静态链接经固定 SHA-256 验证的 OpenSSL 3.5.9，部署目标为 macOS 11，随包保留 OpenSSL 许可。构建后用 otool 拒绝系统目录之外的动态库依赖，不要求用户安装 Rust、OpenSSL 或 Homebrew 库。构建输入保留原锁定哈希，目标安装清单由实际 wheel 生成并使用产物哈希；编译仅发生在构建机。</p>
  <p>Go 的 install-bundle 实现安全解包、拒绝链接与越界路径、平台／版本及逐文件哈希校验、运行环境准备和原子指针切换；激活失败恢复原指针，旧裸二进制另行保留。install-probe 使用临时存储与本地模型目录 fixture 验证设置读取、保存和重启恢复。已有环境不会被原地覆盖；升级通过私有 quiesce 入口检查在途工作并短暂停止新写入，失败／超时恢复接收请求，私有入口不公开挂载。</p>
  <p>Go 监督 Python 子进程并在异常退出后指数退避重启；就绪后停止探测定时器，常态不增加健康轮询。继承的存活管道在父进程正常退出或崩溃时通知子进程退出，Python 继续使用原有独占数据库锁。systemd／launchd 负责启动和重启 Go；Linux 保留 KillMode=process，避免重启控制台时杀掉用户 tmux 会话。独立手工运行时保持原归属，安装时要求先停止，不自动接管。</p>
  <p>Unix socket 改为同实例数据目录下的确定路径，不再因交互 shell 与服务的 XDG_RUNTIME_DIR 不同而失联；超长路径使用 /tmp 下按用户隔离、校验所有者与 0700 权限的短目录。内置智能体读取设置不需要先配置模型。运行时不可用时前端显示已有“暂时无法连接智能体”文案，不再提示用户检查模型地址和密钥。</p>
  <p>数据库边界：本版自动安装与升级只接受当前 schema。旧布局沿用安装前检查；schema 不同则在读取检查阶段阻止激活，保留旧服务和数据，要求使用已有离线备份／迁移流程。尚未实现跨 schema 的自动备份恢复，不把程序回切当成数据库回退。默认完整包安装与 ROAMI_NO_SERVICE 手工启动均可用；tmux 仍是宿主依赖，Chrome／ADB／KVM 为独立可选能力。</p>
  <ul>
    <li>Linux 本机通过真实 curl 到 bash 的安装入口，测试 PATH 无 Python／uv／Go／Node；使用临时 systemd／launchd 适配器启动真实服务，不修改宿主常驻服务。覆盖全新安装、重复执行、含空格目录、持久对话与配置、新版本目录切换、启动失败恢复旧版、校验失败保留现有服务和子进程崩溃恢复。</li>
    <li>Ubuntu 24.04 干净容器只准备 curl、CA 和 tmux，运行阶段关闭 Docker 网络；系统无 Python／uv／Go／Node。实际安装完整包、启动 HTTPS、校验内嵌前端、首次设置口令并通过认证网关读取空模型设置。该检查发现最小系统缺失时区数据库，已把 tzdata 加入生产依赖并增加无宿主 zoneinfo 回归。</li>
    <li>Python 集成覆盖父进程 SIGTERM／SIGKILL、子进程强制退出及自动恢复、升级忙状态、升级期间拒绝写入、恢复接收和私有接口所有者隔离；Go 覆盖归档越界与链接拒绝、失败清理、版本指针回退和长目录／不同 XDG 环境。</li>
    <li>桌面实际设置表单可打开；Redmi Note 8 真机为 392 CSS px、compact／coarse，输入框命中高度 44px，真实点按聚焦，键盘 314px，无横向或文档滚动。截图位于 /tmp/roami-install-settings-desktop.png 与 /tmp/roami-install-settings-phone-full.png，触控记录为 /tmp/roami-install-phone-validation.json。</li>
    <li>macOS Intel／Apple Silicon 的 Go 二进制交叉编译通过；四平台原生完整包安装验收已接入发布 CI，全部 bundle 验收成功后才进入 publish。此开发机没有实际运行 macOS 原生安装，不把交叉编译当作该项通过。</li>
    <li>最终 full 质量门禁、Go 测试、908 个 Python 用例、925 个前端用例、typecheck／i18n／hover 和生产构建通过；保留已有前端大块体积提示。最终自动检查与运行证据汇总于 /tmp/roami-install-acceptance.json；测试和演示仅使用临时配置、无付费模型调用，未更新用户现用 Roami 服务。CLI 输出与此开发设计正文按 i18n 规范的终端／开发文档例外保留中文，产品文案复用已有中英文键。</li>
  </ul>
  <h3>依据与当前证据</h3>
  <p>隔离复现记录：/tmp/roami-settings-diagnosis-6bzq3vf4/results.json。只有 Go 主程序时模型设置返回 503 AGENT_RUNTIME_UNAVAILABLE；补启运行时后，即使没有 agent.toml、模型地址和密钥，也返回 200。安装与守护实现已完成；公开版本尚未发布。</p>
  <p>Python 官方将 venv 定义为应在目标位置重建的环境：<a href="https://docs.python.org/3/library/venv.html">venv 文档</a>。独立 Python 发行版归档结构见 <a href="https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html">python-build-standalone 文档</a>；固定 Python 管理方式见 <a href="https://docs.astral.sh/uv/guides/install-python/">uv Python 管理文档</a>。这些支持发行方式选择，不代表上述 Roami 安装实现已通过验收。</p>
</section>

<section id="capability-markets-design" lang="zh-CN">
  <h1>开放能力市场与 MCP 传输接入 · 2026-10-23</h1>
  <h2>产品设计</h2>
  <p>能力中心新增“市场”，首批接入 skills.sh、官方 MCP Registry 和 npm。来源可启停、编辑服务地址，或新增兼容相同接口的来源。搜索按用户操作发起；结果展示名称、摘要、版本，查看时解析真实配置，再进入现有可编辑确认表单。导入成功后在 Skill、MCP、CLI 原分类管理；保留来源、固定版本和 Skill 附件，不覆盖重名项。MCP 不因浏览或保存而启动；CLI 明示首次调用由 npx 下载固定版本，参数使用 args 数组。</p>
  <p>MCP 的本地程序、SSE、Streamable HTTP 三种传输均可新建、编辑、导入、连接和调用。type 与 transport 冲突时拒绝导入；保留现有 HTTPS、凭证环境变量引用、取消和连接生命周期边界。手机详情与来源配置复用全屏 MobileSubPage，表单滚动和保存栏沿用现有令牌。</p>
  <h2>用户故事</h2>
  <ol>
    <li>我能搜索公开技能，查看上游来源和固定提交，确认后保留指令、引用文档、脚本和附件，重启后继续使用。</li>
    <li>我能从官方 MCP 目录选择 SSE、Streamable HTTP 或支持的 npm／PyPI 本地程序配置，修改名称、参数和凭证环境变量引用后保存，再显式连接。</li>
    <li>我能从 npm 查找具有命令行入口的软件包，固定版本并注册；普通库没有入口时给出明确提示，不假装可调用。</li>
    <li>我能停用市场来源而不删除已导入能力；主 Agent、后台工作 Agent 与平台派发的 Codex／Claude 任务共用已安装能力和停用策略，专业任务也能读取 Skill 附件和调用 MCP／CLI。</li>
    <li>我能在手机完成市场搜索、来源配置、详情、确认导入与返回，失败保留输入和最近结果。</li>
  </ol>
  <h2>技术设计</h2>
  <pre>frontend/src/components/capabilities/
  CapabilityMarket.tsx       按需搜索、结果分页、接入选项和导入确认
  MarketSources.tsx          来源配置、启停和完整替换
  CapabilityEditor.tsx       复用导入表单，保留来源、附件与参数模式
agent-runtime/src/roami_agent/server/
  capability_markets.py      所有者检查、私有来源配置、请求合并与缓存
  market_catalogs.py         skills.sh／MCP Registry／npm 只读适配
  skill_package.py           有界附件验证、不可变包目录与完整性校验
  capability_imports.py      原有原子注册、启停及恢复；新增附件与 argv 参数模式
  http.py                    私有接口，由原 Go 登录网关转发
agent-runtime/src/roami_agent/tools/mcp.py
                             SDK stdio／SSE／Streamable HTTP，统一连接 actor</pre>
  <p>GET／PUT /api/agent/capability-markets 管理来源，GET /api/agent/capability-markets/{source}/search 按需搜索，POST /api/agent/capability-markets/preview 获取待确认导入项。来源配置私有文件 0600，原子替换；禁用来源拒绝新查询。目录请求最多四个并行，合并同请求、缓存一分钟，不新增常驻轮询；关闭运行时取消所有目录请求。</p>
  <p>GitHub 技能按固定提交下载，拒绝符号链接、路径穿越和冲突路径，最多 100 个文件、384000 字节，保留仓库许可证。附件随注册数据保存，运行时只读副本按内容散列放在节点 agents/capability-packages 下；旧版本保留以免破坏正在运行的任务。单个带附件的 Skill 请求最多 600000 字节，总目录仍最多 1 MiB。脚本不在导入时执行，后续运行继续经过已有工作目录与进程权限边界。npm 只从包元信息中的 bin 登记命令，固定版本并以 argv 数组调用。</p>
  <p>平台主 Agent、后台工作 Agent 和托管专业任务使用同一注册表。Codex／Claude 任务通过任务级 CLI 入口读取 Skill 和引用、发现 MCP 工具、调用已注册 MCP／CLI；不用为各专业程序另装一份能力。专业程序原有的全局配置继续由其自身管理。Docker／MCPB 和需 OAuth 的条目不伪报已接入；不支持的包装格式明确报告。</p>
  <h3>专业任务接入</h3>
  <pre>executors/roami_cli.py → tools/professional_capabilities.py
  派发提示携带只读目录命令及私有上下文文件路径
cmd/roami/agent-capability.go
  list／show；read／call --context FILE --call REQUEST_ID
server/http.py → ProfessionalCapabilities → Tools.invoke
  校验签名、所有者、运行中任务／尝试、版本、来源和预算
  复用能力启停、参数 Schema、MCP actor、CLI 工作目录与产物外置
conversation/professional_activity.py
  持久执行回执进入现有任务记录及按需详情，沿用秘密字段打码</pre>
  <p>每次专业派发生成 0600 上下文文件，服务端以节点私有密钥签名；提示仅包含路径，不包含签名。上下文绑定所有者、任务、尝试和版本，取消、完成、来源忘记、排队改派或预算到期即拒绝新调用。只允许 Skill 读取、MCP 发现和外部注册操作，不借此开放内部调度工具。执行期间持续复验任务状态，撤销时取消底层操作。</p>
  <p>请求号在执行前原子登记到已有事件存储；相同号和参数返回原回执，不重跑。参数冲突拒绝，进行中或进程重启后的未完成调用保持未知结果，不能自动重放。每个任务最多 1024 次登记、每节点最多 16 个并发、单次最多 90 秒；CLI 等待预算为 100 秒。完成结果与失败进入任务执行记录，主聊天仍只显示任务进度和可行动阻塞。</p>
  <h3>CLI 与 Roami 自主接入 · 2026-10-23</h3>
  <p>终端增加 roami agent capability market sources／search／preview／install，JSON 参数与现有命令族一致。主 Agent 与普通 Worker 通过同一动态 CLI 目录按需发现；专业任务可使用自己的 --context 与 --call。研究只读角色不开放安装。市场指令与描述作为待审阅数据，只有用户要求安装时才执行 install。</p>
  <p>server/market_installations.py 保存最多 32 份、十分钟有效的固定版本预览，CLI 只返回说明摘要、附件名和完整配置，不把附件 Base64 放入模型上下文。安装以 previewId／option／可选 name 选择原包，复用托管注册、名称冲突和原子保存；失败保留预览。来源停用或改址、预览过期均拒绝继续安装；相同选择重试返回同一回执，被编辑或移除后报冲突。sources／search／preview 为读取，install 为写入，沿用当前调用上下文、任务撤销和执行记录。MCP 保持未连接，CLI 首次调用下载的规则保持一致。</p>
  <p>实现模块：tools/market_commands.py 注册按需工具；commands.json 维护公开路径；cmd/roami/agent-market.go 同时服务普通终端及已绑定的 Agent 调用；POST /api/agent/capability-markets/prepare 与 /install 复用登录网关。平台常驻模型 schema 数量保持原有基础工具集合。</p>
  <h2>调研来源</h2>
  <ul>
    <li><a href="https://github.com/vercel-labs/skills">skills.sh 安装工具与公开源码</a></li>
    <li><a href="https://modelcontextprotocol.io/registry/registry-aggregators">官方 MCP Registry 聚合接口</a></li>
    <li><a href="https://github.com/openclaw/clawhub/blob/main/docs/http-api.md">ClawHub 公开搜索与下载 API（后续适配来源）</a></li>
    <li><a href="https://skillsmp.com/developers">SkillsMP API（后续适配来源）</a></li>
    <li><a href="https://smithery.ai/docs/api-reference/servers/download-server-bundle">Smithery 下载接口（后续适配来源）</a></li>
    <li><a href="https://glama.ai/mcp/reference">Glama API 与署名要求（后续适配来源）</a></li>
  </ul>
  <h2>验收</h2>
  <p>仓库 full 门禁通过，包含 Go 全量测试和 940 个运行时用例；前端 129 个文件、930 个用例通过，typecheck、i18n（3537 个键）、hover 与生产构建通过。最后对执行目录投影和 CLI 返回状态的调整另通过专业接入 12 个定向用例及 Go CLI 包全量测试。格式与静态检查通过，构建保留原有大块提示；最新完整日志为 /tmp/roami-market-quality-platform.log。</p>
  <p>隔离 Go 登录网关与真实 Python 运行时已完成 skills.sh 上的 find-skills、官方目录中的 Context7 配置和 npm Prettier 固定版本导入。重载注册数据后，Prettier 实际输出 3.9.10，SSE 服务实际返回 market smoke。SDK 的 stdio 子进程、SSE 和 Streamable HTTP 实服均验证初始化、认证、发现及调用；来源禁用、重名、原子失败、重启恢复、附件路径与符号链接保护有回归覆盖。</p>
  <p>Redmi Note 8 真机在 392 CSS px／coarse 下完成市场搜索、来源编辑保存、SSE 新建连接、真实手势滚动，以及 Vercel React Best Practices 的 76 个文件下载、修改名称、确认导入、Skill 详情与返回。只有一个二级页返回栏；列表手势由 0 滚至约 418px，文档保持 0，无横向溢出。键盘实测 314px，保存按钮高 44px、底边约 440px，位于 766px 视口的键盘上方并能真实点按。紧凑标签栏的市场项宽 44px，完整可见。</p>
  <p>桌面检查 320、390、820、1100、1440 宽度，页面与文档无横向溢出，文档不滚动，浏览器无脚本错误；中文深色与英文浅色分别核对。证据与截图保存于 /tmp/roami-market-*，包括 live-evidence、call-evidence、phone-import-evidence、phone-sse-evidence 和 width-evidence。开发实例使用独立数据目录、数据库、Unix socket 与记录过身份的 tmux 服务；不部署到用户现用服务。</p>
  <p>专业接入使用真实 Go CLI、私有 Unix socket、Python 运行时与隔离 tmux，Codex／Claude 的 TUI 使用确定性离线测试程序，不消耗模型调用。两类会话均从派发提示读取私有上下文，成功读取已导入 find-skills、执行固定版本 Prettier（3.9.10）、发现并调用真实 SSE 服务；每次任务的四个调用进入执行记录，重复请求返回同一回执，取消后的调用被拒绝。定向用例另覆盖上下文伪造、跨所有者、旧版本、已结束尝试、忘记来源、改派、停用、目录越界、并发重复、运行时关闭及重启恢复。原始证据为 /tmp/roami-market-professional-evidence.json；测试结束已关闭确切执行会话并通过隔离启动器清理私有 tmux 服务。</p>
</section>

<section id="mobile-document-access-20261024" lang="zh-CN">
  <h1>手机文档预览与保存 · 2026-10-24</h1>
  <h2>产品设计</h2>
  <p>聊天中的任务产物链接和附件在手机内打开全屏二级页，保留返回和下载。PDF 逐页绘制，PPTX 沿用本地渲染器并隔离页面内容；文件页和任务详情复用同一预览。Android 保存使用已信任的服务器证书及登录态，系统保存框保留中文原名，文件写入完成后才提示成功，失败清理本次创建的残缺文件。</p>
  <h2>用户故事</h2>
  <p>用户在聊天里点开 PDF 或 PPTX 即可查看、翻页或滚动，然后返回原对话；点下载能选择保存位置并得到原文件。跨节点链接保留来源节点，外链及显式下载继续正常导航。</p>
  <h2>技术设计</h2>
  <p>file-link 识别产物内容地址并按需读取元信息；MobileFilePreview、TaskArtifactPreview 与文件页复用 documents/DocumentPreview、PdfDocument。PDF.js 与 Worker 按需加载，画布限制像素预算；PPTX 页面使用禁脚本和外部网络的 sandbox。DocumentDownload 使用同源 OkHttp、CookieManager、Tls 和 ACTION_CREATE_DOCUMENT，DocumentName 解析 UTF-8 Content-Disposition。WebMessage 下载入口仅注入受信任服务器来源、仅接受主框架消息；保留普通 DownloadListener 兜底，已由网页接管的附件预览不再触发下载。APK 升级为 0.3.9，保留现有签名。</p>
  <p>验收：Redmi Note 8 的 Chrome 和正式签名 App 在自签 HTTPS 下完成 PDF 绘制与翻页、PPTX 触控滚动和返回；两份文件通过系统保存框保留中文及加号文件名，手机文件 SHA-256 与服务器原件分别一致。接口要求 HttpOnly 登录 Cookie，确认原生保存携带登录态。跨节点链接与显式下载通过回归检查；前端完整检查、仓库 full 门禁及 Android 单元测试和签名构建通过。测试材料使用隔离示例，不外传用户文档。</p>
</section>

<section id="rsi-experiment-workflow" lang="zh-CN">
<h2>RSI 实验 Workflow · 2026-10-24</h2>
<h3>Product Design / User Stories</h3>
<p>开发版“设置 / 实验”用可点选七节点显示评测、Codex复盘、Codex汇总Issue、Codex修复、独立验收、草稿PR和观察。用户配置机器、日程、预算、Codex额度和重试，再预览运行；运行记录和每日Issue独立查看。普通安装版不注册入口或挂载评测组件。</p>
<h3>Technical Design</h3>
<pre>SettingsPage → ExperimentWorkflow / AgentImprovement → 所有者Go网关
→ development-only HTTP → ImprovementControl / ResearchWorkflow
POST preview：只读预估最大配对预留；PUT research：限额字段与修订号校验</pre>
<p>固定每日完整60项、Codex三角色、冻结验收和最少两天观察。可信仓库、命令和源码范围不从Web改写；部分入队失败重用请求键，模型异常记录脱敏error_code。图表及真实诊断边界见<a href="docs/design/20261022-roami-agent-rsi/automation-roles.html#workflow">具体设计</a>；诊断问题已汇总为<a href="https://github.com/ybz21/Roami/issues/443">Issue #443</a>。原始60项尝试未形成有效全套成绩，机制补测20/20；日程未启用。</p>
<p>验收：quick/full通过，Python1238项、前端132文件/960项通过；新增预览、有限配置、流异常及发行隔离的定向Python39项通过。桌面320–1920宽度与Redmi Note 8真触控验证节点点选、配置保存、预算预览、单返回栏与零溢出；普通版深链不请求RSI。界面验收使用隔离示例配置，与真实诊断成绩分开。</p>
</section>

<section id="experiment-run-engineering" lang="zh-CN"><h2>实验分组与Workflow工程合同 · 2026-10-24</h2><h3>Product Design / User Stories</h3><p>实验与“这台机器”同级，RSI为其子页；未来OKR可注册，未实现入口不展示。用户分别配置下一次Workflow和查看指定Run；历史运行显示冻结配置、逐节点状态与产物，不能拼接全局最新动作。</p><h3>Technical Design</h3><p>定义版本 → Run快照 → 节点Attempt → 产物索引 / 状态事件 / 副作用outbox。复用已有评测和Codex执行器；主账本同事务关联requests/cycles/actions，不增加第二套调度状态来源。默认合同和恢复、权限、落盘协议见<a href="docs/design/20261022-roami-agent-rsi/workflow-engineering.html">工程设计与交互原型</a>及<a href="docs/design/20261022-roami-agent-rsi/workflow-contract.json">机器可读默认合同</a>。前期10项用独立原型验证；现已迁移到RunRecords，按次运行页面和GitHub诊断发布见下节。已实际跑完：5项生成截断、1项预算阻塞、4项机制通过；生成与Codex共311,036 Token，7节点/9 Attempt及26份文件完整性复核通过，复盘首次准入阻塞后保留记录并压缩证据恢复。</p></section>

<section id="rsi-pipeline-delivery-20261024" lang="zh-CN">
<h2>RSI运行闭环 · 2026-10-24</h2>
<h3>Product Design / User Stories</h3>
<p>开发版设置的实验/RSI提供独立运行地址、逐节点职责/状态/文件、GitHub汇总Issue及本地问题列表；从历史运行复测相同Case，区分仍存在、未复现、未验证、未覆盖和合同变化。普通安装不启用。</p>
<h3>Technical Design</h3>
<p>RunRecords在同一私有SQLite保存Run/Attempt/Case/Issue/Observation/Effect；EvaluationWorker复用单队列，PipelineReportWorker用Codex复盘和问题排序、程序脱敏并幂等发布GitHub。PipelineRuns按Run读取状态和hash校验产物，结束记录不轮询。正式源码修复沿用ResearchWorker与独立验证、发布、观察门禁。</p>
<p><a href="docs/design/20261022-roami-agent-rsi/workflow-engineering.html">架构图、执行合同与验收边界</a>。历史10项已自动发布Issue #445；同组10项复测真实任务0/6、机制4/4；Issue #446保留19项仍存在、8项未验证。全仓full门禁通过，Python1249项、前端963项、桌面9档和Android真机触控/滚动通过。复杂产物校准未完成，正式每日调度不冒充已验收。</p>
<section id="background-task-list-20261024" lang="zh-CN">
  <h1>后台任务列表整理 · 2026-10-24</h1>
  <h2>产品设计</h2>
  <p>手机筛选使用简短标签与轻量选中态，常用中文宽度下完整显示五项。任务采用平面行，标题、真实状态、执行器和时间构成主体，日期分组弱化；分隔线归属整条任务。原会话改为行尾终端图标入口，提供可访问名称；项目链接按需显示。桌面工作区复用同一列表层级。</p>
  <h2>用户故事</h2>
  <p>用户能快速扫描任务主题与状态，点标题查看详情，点行尾图标进入原会话；保留筛选、返回与滚动位置。长标题和项目名不撑宽页面，触屏入口保持至少 44px 命中区。</p>
  <h2>技术设计</h2>
  <p>AgentTasks.tsx 的 TaskRow 使用独立任务按钮、项目链接和会话按钮，避免嵌套交互。agent-tasks.css 统一网格行、日期、筛选与触屏命中区，移除 agent-workspace.css 和 native-session.css 中分散的列表样式。时间只显示时分，日期由已有分组标题承载；复用 SVG 图标、主题令牌与 i18n，不改变任务请求和刷新逻辑。</p>
  <h2>验收</h2>
  <p>仓库 quick 门禁通过；前端 129 个文件、936 个用例通过，typecheck、i18n、hover 和生产构建通过。构建保留已有大块体积提示。桌面检查 320、390、820、1100、1440 宽度及中英文／深浅主题，并检查首页工作区；Redmi Note 8 在 392 CSS px／coarse 下完成五项筛选、刷新保留选择、详情返回、原会话入口、真实手势滚动与四个底部主入口点按。筛选命中区至少 44px，会话入口为 44×52px，文档不滚动且无横向溢出。证据位于 /tmp/task-page-{phone,desktop}-acceptance.json，截图为 /tmp/task-page-after-phone.png 与 /tmp/task-page-after-workspace.png。使用隔离示例数据与私有 tmux 服务，不修改现用服务。</p>
</section>

<section id="rsi-artifact-calibration-repair-20261024" lang="zh-CN">
<h2>RSI产物评分与修复 · 2026-10-24</h2>
<h3>Product Design</h3>
<p>实验页为记忆角色提供可选模型与推理强度；历史Run单列产物评分用量。未保存配置不能启动诊断。评分校准不满足时保留待评，问题列表不能因代码已修改就显示修复。</p>
<h3>User Stories</h3>
<p>维护者先审阅12项独立完整/缺陷样本，再运行双模型校准；每一分绑定原始证据。超时后先对账，避免重复费用。修复记忆截断和题面歧义后，查看同合同复测证据；题目修订单列为不可比较。</p>
<h3>Technical Design</h3>
<pre>离线材料生成 → 人工参考 → 两个视觉模型 → 校准证书 → 固定7项产物评分
Run配置快照 → 独立Agent镜像 + 冻结渲染镜像 → 生成/评分分别计量
异常用量 → 阻止后续付费 → 请求ID对账 → 明确恢复
Issue证据 → 补丁 → 独立检查 → 同合同复测 → 连续日观察</pre>
<p>artifact_review显式提供证据标签与输出上限；ContainerExecutor分离被测镜像、渲染镜像和可选记忆路由；EpisodeBudget/ChatCompletionsProvider用上下文限定的opaque请求ID关联上游日志，普通请求不增加评测标识。PipelineRunner预留每个产物评分预算，未知用量停止后续生成；RunCosts阻止未知计量后的新付费复盘。MemoryJobs不重放确定性无效输出；corpus新版本显式包含公开前置条件，旧冻结数据不变。</p>
<p>真实校准完成4项双评，PPT可用性有分歧，第5项超时且用量未知，未签发证书。人工标注、完整校准、正式7项评分和真实问题复测仍待完成；当前不能宣称Issue #446已修复或已降低Token。</p>
</section>

<section id="rsi-recovery-accounting-20261024" lang="zh-CN">
<h2>RSI失败恢复与预算 · 2026-10-24</h2>
<h3>Product Design</h3><p>开发版Workflow可分别配置Main、Worker和记忆的模型/推理强度；空值继承现有角色默认。Case不再因前序任务占满共享额度而完全没有启动机会。历史题目和失败记录不覆盖。</p>
<h3>User Stories</h3><p>维护者看到预算拒绝、实际取消和模型失败的不同证据。已知调用只结算一次并归还未用额度；对已结束的未知调用可本机显式隔离，保留全额预留及证据，不把未知费用算作零。新独立测试使用剩余额度，原请求不能重放。</p>
<h3>Technical Design</h3><pre>Run角色配置 → 冻结路由与模型hash → Case启动预留 + 共享总池
MeteredModel：逐次推进绑定请求ID → 明确本地拒绝 / 供应商响应 → 关闭并结算
Operation：running → completed（实际结算） / unknown → 本机显式quarantined（全额保留）
新题：公开字段类型 / 费用与滑点 / 分页元数据 → 新合同 → 独立判定</pre>
<p>operation_accounting统一新付费操作的准入；隔离只接受未知终态和本机证据，不提供Web绕过。measurements和model_gateway显式关闭异步流，避免ContextVar跨任务重置；executors在原期限内等待已运行的维护作业。containers公开有界输入文件目录，不提供隐藏判定数据。正式每日60项与连续观察不变，校准不足仍不计产物通过。</p>
<p>单次输出额度修订：Main和Worker独立配置，空值按角色模型、上下文窗口和Case/整轮剩余预算逐次分配；未配置模型上限时保留一半可用额度给后续步骤。RequestBudgetModel在创建供应商前校验两层余额，计量仍由Case和整轮各自记录一次；本地拒绝不能伪造未知费用。框架实跑优先使用OpenCode与DeepSeek Flash，Native的20项机制在无网络容器逐项验收；评分校准及未知账目仍保持独立门禁。</p>
<p>Native专项执行合同修订：容器请求明确指定内置Native Worker，允许如实报告复杂任务，并用当前请求中的原文形成explicitExecutor与userQuote。此前禁止显式Native选择会让合法的复杂任务进入不存在的专业CLI发现；v4执行器指纹保留这项环境变化，不将旧失败记录改成通过。生产路由规则及明确执行器的来源验证不放宽。Worker的通用交付指令同时要求对视觉产物做可用的本地渲染，检查SVG文字边界和遮挡；无法渲染时保留验证限制。</p>
<p>Worker执行环境修订：普通bash命令使用非登录shell，继承已准备的PATH及虚拟环境；避免登录配置覆盖渲染依赖。回归测试运行PATH中的真实可执行文件，并确认未读取登录profile。显式argv仍允许调用者选择登录shell。</p>
<p>2026-10-25实证：Native机制20/20通过；真实CODE-01通过独立检查，79,420 Token/16次请求，Main/Worker自动输出额度超过8192并随余额变化，过程仍保留TASK_RESULT_REQUIRED与WORKSPACE_REQUIRED恢复记录。OpenCode加deepseek-4.1-flash完成真实文件创建、3项独立测试、重复启动幂等和原对话续接，成功轮42,958 Token/8次请求；本轮含两次失败尝试共169,683 Token，全部结算。前端966项及生产构建通过；桌面7档宽度、中英深浅主题与Redmi真机确认保存、键盘、滚动、返回及44px按钮命中区。原10项的两份产物仍待独立评分，人工参考分未确认，Issue #446未关闭；合同修订不作为旧题收益证据。汇总证据位于/tmp/roami-rsi-continue-report/，未部署现用服务。</p>
<p>最终整仓full门禁通过，包含Go测试、运行时1281项、前端检查和生产构建。首次整仓检查遇到Xvfb在5秒内未就绪，独立桌面组6项通过后，在降低并发负载的完整重跑中未再出现该错误；保留两次检查日志，不修改或跳过该测试。</p>
</section>

<section id="rsi-conflict-recovery-20261025" lang="zh-CN">
<h2>RSI冲突恢复与预算证据 · 2026-10-25</h2>
<h3>Product Design</h3><p>文件冲突返回明确的恢复步骤：重新读取、核对当前内容和hash后修改，保留其他人的编辑，不用shell绕过校验。诊断运行同时记录原题额度和本轮实际分配额度，避免把共享预算压缩误判为原题预算不足。</p>
<h3>User Stories</h3><p>Worker误用新建模式或遇到并发修改时，能读回最新内容后继续完成原任务。维护者能区分Token、调用次数、时限和未知用量阻塞，而不是只看到委派失败；失败仍阻止成绩通过。</p>
<h3>Technical Design</h3><p>ToolGateway对FILE_CHANGED补充恢复指令；仅文件写入冲突标记writePublished=false，源hash校验保持原样。模型侧图片文件read仅返回hash、大小和分页元信息，contentOmitted=true，不把base64字节当作可视输入塞进模型上下文；底层WorkspaceFiles读取和受控视觉观察保持原有接口。Worker指令要求自行读取现有文件；无图像观察能力时使用DOM、布局和行为检查并报告限制。PipelineRunner在evaluate产物中保存每个Case的原始／有效limits、已知用量、共享上限和后续Case预留。evaluation_tasks只从当前修订的最新失败Attempt提取四种已知预算错误，ContainerExecutor保留该根因；任意模型文本仍只产生通用失败。</p>
<p>产物路径识别同时支持Markdown加粗、中文括注、真实换行及模型输出的转义换行，避免把说明文字并入路径或遗漏README；仍使用原有工作区和文件类型边界。</p>
<p>版本绑定修订：同一任务、修订和Attempt的Main完成回合如果通过文件工具修正了产物，TaskDeliverables按成功工具回执中的sha256创建新的私有快照，保留旧版历史。文件内容不匹配回执时拒绝发布；其他任务的回合、未记录的外部修改以及已删除产物不能借此替换或恢复。使用文件线程池校验暂存内容，不增加后台轮询。</p>
<p>定向112项通过，包含两次文件冲突及并发修改保护、图片元信息与底层原字节接口、当前修订预算根因保留、任意错误文本隔离、原始384,000／有效268,000额度证据，以及加粗路径的两份文件持久交付。上一轮DEMO两项补测实际分配208,000而原题为384,000；已纠正PR #448及Issue #446中的“原Case上限”说法。完整384,000额度下DeepSeek轮仍失败，用量323,370，保留失败；图片元信息修订后以GLM Worker和180,000诊断额度完成，118,408 Token／18请求，容器外硬检查通过、质量待评。路由与额度不同，不据此宣称同条件收益。使用真实生成文件做零模型调用的交付适配器回放，HTML和README在工作区删除后仍可按原hash读取。评分校准仍要求人工参考分。</p>
</section>

<section id="native-session-experience-20261025" lang="zh-CN">
  <h1>本地智能体会话与产物 · 2026-10-25</h1>
  <h3>品牌标识修订 · 2026-10-25</h3>
  <p>产品设计：Roami 自身的智能体统一使用现有蓝色 logo-mark.svg，在项目会话列表、会话详情、任务身份和 Native 执行记录中裸露展示，保留现有尺寸与状态提示。</p>
  <p>用户故事：用户在桌面和手机上通过 Roami 品牌标识识别自身智能体，专业智能体继续使用各自品牌。</p>
  <p>技术设计：icons.tsx 导出 RoamiLogo，直接引用既有 SVG 资产；NativeProjectSessions、NativeSession、AgentTasks、AgentTaskActivity 与 AgentActivity 复用该组件，不改写专业 AgentKind 或服务端协议。</p>
  <p>验收：typecheck、i18n（3814 个键）、hover、137 个文件／991 项前端测试及生产构建通过；桌面与 Redmi Note 8 真实触控检查会话列表、详情、对话／产物切换、品牌图片加载与无横向溢出，深浅主题均可读。前后截图和检查记录位于 /tmp/roami-logo-20261025，示例内容与现用实例隔离。</p>
  <h2>产品设计</h2>
  <p>项目列表的本地智能体复用专业会话的图标、单行标题、状态、时间和平面分隔线，整行进入会话。详情使用紧凑身份栏与对话／执行过程／产物三个入口；长用户需求收为三行，可显式展开。底部统一输入卡跨入口保留草稿并续接原任务，失败不清空，关闭仍需确认。</p>
  <p>产物页先显示真实任务结果与验收状态，再列文件。按当前执行／历史执行分组，提供名称、文件类型、大小、生成时间、预览和下载；无执行归属的文件单列，不猜测版本。图片、PDF、PPTX、文本和 HTML 复用安全预览，其他格式保留下载。手机预览是全屏二级页，返回原产物列表；无法留存的文件明确提示。产物存在或执行器声称完成都不改写任务状态。</p>
  <h2>用户故事</h2>
  <ul>
    <li>用户在同一项目中能像打开 Codex 一样识别和打开本地智能体。</li>
    <li>用户直接在会话中查看中间输出和工具调用，展开查看结果，再追加要求，沿用原任务与会话。</li>
    <li>用户可以区分本次与旧版文件，在手机预览、返回并下载，不会把旧产物误认作本次交付。</li>
  </ul>
  <h2>技术设计</h2>
  <pre>NativeProjectSessions → 既有 native-sessions 目录与 session 路由
NativeSession → useAgentTask + native conversation + 原任务 steer
  → TaskProcess / TaskResult（按需读取执行记录）
  → NativeSessionArtifacts → TaskArtifactPreview / MobileSubPage
NativeConversation → ChatMessage / ToolRun / ToolView + TaskDescription（三行用户正文）</pre>
  <p>复用既有节点感知接口、版本号与幂等请求键、草稿持久化及任务变更事件。沿用既有端点，补齐会话的工具消息与状态，不新增结束任务轮询。产物合并目录与 delivery 后按 ID 去重，按 metadata.runId 区分执行。页面使用既有主题、国际化、SVG 图标和输入卡样式。验证覆盖续聊失败和重试、过程按需加载、产物分组与预览、结束后不轮询，以及桌面和 Android 真触控、键盘与返回。</p>
</section>

<section id="native-session-inline-tools-20261025" lang="zh-CN">
  <h2>会话内完整过程修订 · 2026-10-25</h2>
  <h3>产品设计与用户故事</h3>
  <p>本地会话直接按原顺序展示用户要求、助手中间输出、工具调用与结果、最终回复；不要求切到执行过程才看到工具。用户展开命令查看输出，相邻同类工具沿用专业会话的分组，失败与进行中保持可见。产物和续聊保留原设计。</p>
  <h3>技术设计</h3>
  <pre>NativeSessions.conversation（分页、所有者校验、工具结果与状态）
→ nativeTranscript（转为既有 Msg / Block，按调用 ID 配对）
→ ChatMessage / ToolRun / ToolView（Codex 与 Claude Code 同一份渲染器）</pre>
  <p>工具入参和输出复用执行记录的脱敏与大小上限；原始 content_json 同步使用脱敏结果。跨页工具结果按 turn_id 与 provider call ID 归并，加载旧页后恢复配对；归档内容沿用校验后的透明恢复。工具状态通过幂等键索引读取，不扫描全表，不新增轮询。已结束但缺少结果的调用显示结果未知，不保留假运行中状态。中间文字属于可见转录，不合成模型内部推理。</p>
  <h3>验收 · 2026-10-25</h3>
  <p>Go 全量通过；Python 格式、静态检查及 1267 项测试通过，包含新增的工具消息、脱敏、跨页配对、归档恢复与所有者隔离回归。前端 typecheck、i18n（3793 个键）、hover 与 135 个文件／978 项测试通过；全量前端检查使用 4 个 worker，避免本机同时执行其他工作树检查造成超时。full 命令的首次压缩与另一构建争用 dist，已停止并行构建并单独顺序重建成功；未将该次 full 命令标为整体通过。生产构建保留已有大块提示。</p>
  <p>生产包在桌面 320、390、820、1100、1440、1920 宽度和中英文／深浅主题检查通过。Redmi Note 8 在 392 CSS px／coarse 下完成真实点按和手势：会话内中间输出、Read、命令展开、相邻工具分组、执行记录、产物分组、Markdown 预览与返回、原任务续聊，以及四个底部入口。过程滚动约 299px；键盘实测 314px，发送按钮底边约 434px，位于键盘上方并可真实点按；页面无横向或文档滚动。截图和请求回执使用隔离示例，不代表真实模型交付；下载检查验证节点感知地址与文件名，未把链接检查称为 Android 落盘验收。</p>
  <p>证据位于 /tmp/native-ui-20261025，包含前后桌面／手机截图、after-desktop.json、after-phone.json、phone-navigation.json、native-runtime.log、vitest-final.log 与 build-final.log。测试实例使用独立端口和记录过身份的 tmux 服务；不修改现用服务。</p>
</section>

<section id="conversation-ui-unification-20261025" lang="zh-CN">
  <h1>统一对话界面 · 2026-10-25</h1>
  <h2>产品设计</h2>
  <p>首页、Codex、Claude Code 与本地子智能体使用专业会话的消息气泡、工具行与输入卡。文字区、底部工具条、圆形发送／停止按钮、字体、留白与命中区共用组件和样式。工具条左侧提供添加与模式，右侧提供模型、已有语音功能与主动作；窄屏可换行，主动作始终可达。首页保留对话／任务选择、项目、执行器、模型与推理强度；专业会话保留真实权限模式、模型、文件和终端控制；子智能体继续原任务，任务详情、产物和关闭放在添加菜单。</p>
  <h2>用户故事</h2>
  <ul><li>用户在四类对话间切换时，输入、发送、停止和查看输出的位置与样式一致。</li><li>用户在首页直接选择对话或任务模式，并保留项目、执行器、模型、附件与排队；专业会话的权限与模型继续由原 CLI 确认。</li><li>手机用户使用 Enter 换行、可见按钮发送，输入法确认候选词不误发；失败保留草稿，弹出键盘后所有动作可点。</li></ul>
  <h2>技术设计</h2>
  <pre>chat/ConversationComposer.tsx + conversation.css
  文本区、附件／提示／选项插槽、统一工具条、发送／停止与键盘规则
  ← AgentChat / ChatShell（Codex、Claude Code、OpenCode）/ NativeSession
chat/Message.tsx
  共用正文、气泡与复制，开放消息附加动作
  ← AgentMessageView（首页提问、附件、记忆与已读标记）/ NativeConversation / 专业会话
ComposerPlus / AgentComposerPlus / AgentModelPicker
  继续承担各自真实配置与接口，只统一触发控件和锚点</pre>
  <p>网络请求、草稿、排队、附件与提交协议留在原控制器；公共输入组件不调用服务端。移除首页和本地会话重复的输入卡样式覆盖，布局只走 useLayout。验证覆盖中文输入法、手机 Enter、发送失败、停止两阶段、模式／模型操作、队列与消息已读，以及桌面和 Android 真触控、键盘和返回。</p>
  <h3>验收记录</h3>
  <p>quick 质量门禁通过（Go 全量、Python 静态检查／格式／1267 项测试、前端 typecheck／i18n／hover）；最终前端 136 个文件、982 项测试通过；生产构建及压缩成功，保留已有大块体积提示。公共输入回归覆盖输入法组合、桌面 Enter／Shift+Enter、手机 Enter、停止与发送并存、仅附件发送和模式控件不误提交；既有队列、失败草稿、提问、记忆与导航测试继续通过。</p>
  <p>桌面与 Redmi Note 8 真机分别检查首页、Codex、Claude Code、本地子智能体。四类输入框的字体、行高、留白、背景、边框、圆角与发送尺寸通过实际计算样式比对；手机按真实能力换行，不增加无效控件。手机检查模式、模型返回、工具展开、手势滚动及原任务续聊；键盘实测 314px，发送按钮底边约 411px，位于键盘上方。桌面在 320、390、820、1100、1440、1920 宽度检查中英／深浅主题，无横向与文档滚动。</p>
  <p>前后截图、生产包页面检查、真机键盘截图和请求回执位于 /tmp/conversation-unify-20261025，入口为 comparison.html。截图和执行内容使用隔离示例；未以示例回执声称真实模型或现用 tmux 会话执行通过。本轮改前快照包含此前已完成的本地会话改动。测试服务使用独立端口和隔离启动器。</p>
</section>

<section id="composer-controls-design-20261025" lang="zh-CN">
  <h1>输入区控件重设计 · 2026-10-25</h1>
  <h2>产品设计</h2>
  <p>按用户修订，固定为正文与单排工具栏两层。正文留足输入空间；工具栏仅保留加号、模型、思考程度、语音与发送／停止。身份不重复展示；模式、项目和执行器进入加号。模型使用可收缩的剩余空间，动作固定宽度。输入卡使用既有表面、14 圆角与令牌留白，去掉聚焦时厚重的光晕；配置控件无常驻描边，只有主动作实心。桌面与手机使用同一结构，窄屏优先给模型分配剩余宽度，全文可在选择面板读取，不把发送挤到第三排。</p>
  <p>按用户修订，不常驻显示上下文。首页与专业会话保留已有加号中的上下文／压缩入口，不增加 native 上下文接口或请求。</p>
  <p>模型与思考选择共享克制的触发样式。首页使用 main 配置；native 使用 worker 默认配置，选择面板明确提示影响后续 native 任务，运行时禁止改配；不把全局默认值伪装成某条已结束执行的真实模型。专业会话沿用 CLI 的模型／思考选择，不在网页乐观伪报修改成功。输入区不显示 native 或内置智能体身份，身份沿用页头。</p>
  <p>语音在四类输入框的同一位置，点击或按住录音、取消、转写沿用已有语音能力。识别只追加到当时的草稿，不自动发送、不覆盖后来输入，也不串到另一会话；未配置、非安全上下文、拒绝麦克风均给出已有恢复提示。语音快捷键优先交给正在录音或已聚焦的可见输入框，未聚焦时默认首个可见输入框；不会同时启动两路录音。</p>
  <p><a href="/api/file/serve/tmp/composer-controls-20261025/design.html">打开交互设计稿</a>；稿内可切换手机／桌面、深浅主题、加号、模型、思考程度和录音状态。示例语音只演示状态，不访问麦克风。</p>
  <h2>用户故事</h2>
  <ul><li>我可以持续看到完整度足够的模型与当前思考程度；手机上话筒和发送位置稳定。</li><li>我可以在 native 里使用语音追加要求，确认文字后再发送；切换会话时不会把旧录音写入新草稿。</li><li>我可以从加号切换对话／交办任务、选择目标与执行器，需要时查看上下文；默认工具栏保持简洁。</li><li>我能明确区分首页配置、后续 native 默认配置和专业 CLI 会话设置，保存失败不改变当前确认值。</li></ul>
  <h2>技术设计</h2>
  <pre>chat/ConversationComposer + conversation.css：固定单排加号／配置／语音与主动作；沿用发送、停止、IME 与附件插槽
agent/AgentComposerPlus：模式、项目与执行器进入加号；沿用按需上下文查询
agent/useAgentModels + AgentModelPicker：显式 main／worker 作用域，保留原子保存与失败重试
chat/ChatShell：转录状态映射模型、思考与上下文；原 CLI 命令及提示面板
agent/AgentChat + NativeSession：各自原草稿控制器、语音追加与快捷键可见性
chat/VoiceInput + icons：统一图标；disabled／会话切换时取消录音，异步结果防串会话
</pre>
  <p>不引入音频自动发送、不更改 CLI 凭证和默认权限。不新增上下文接口或轮询。样式验收覆盖 320／390／820／1100／1440／1920、深浅主题、中英文、粗指针 44px、软键盘与真实触控；协议回归覆盖 worker 修改不写 main、错误保留值、跨会话转写丢弃与模式选择保留草稿。</p>
  <p>专业 Claude 思考入口采用官方交互命令，参考 <a href="https://academy.claude.com/tutorials/choosing-the-right-effort-level-in-claude-code">Claude Academy：effort 交互入口</a>；Codex 继续现有 /model 的模型和推理选择路径。</p>
  <h3>验收记录</h3>
  <p>最终功能回归为 137 个前端测试文件、988 项用例通过，包含 worker 修改不写 main、中文输入法、手机 Enter、队列与草稿、跨会话转写丢弃、延迟授权释放及共享快捷键只触发一个输入框。样式收尾后的语音 5 项回归、typecheck、i18n（3807 个键）、hover 与生产构建／压缩通过。保留已有大块体积提示。本轮只修改前端与设计文档；后端沿用上一轮已通过的 Go／Python 检查，不重复运行无关检查。</p>
  <p>桌面和 Redmi Note 8 分别检查首页、Codex、Claude Code、本地子智能体：默认工具栏恰好五个控件，一排展示，没有身份与上下文重复；模式／目标／执行器进入加号且切换保留草稿。桌面检查 320、390、820、1100、1440、1920 宽度、中英和深浅主题；长模型与英文 Extra high 单独验证，所有控件中心可命中，无横向和文档滚动。手机验证粗指针 44px、模型与思考选择、真录音、转写加入原草稿、上滑取消、原任务续聊和软键盘；实测键盘 314px，发送按钮底边约 430px，位于键盘上方。</p>
  <p>录音通过真实 MediaRecorder、WAV 转换与上传；Android 使用真机麦克风，桌面因浏览器麦克风访问被环境拒绝，先确认错误提示，再使用 WebAudio 测试音源验证录音链路。转写响应、模型配置及执行回执均使用隔离接口，不作为真实 ASR 准确率或模型执行证明。录音状态使用柔和强调色，发送保持工具栏唯一实心主动作。</p>
  <p>证据位于 /tmp/composer-controls-20261025：设计稿 design.html，实际前后对比 comparison.html，桌面／手机 JSON、长模型和上滑取消检查、model-writes.jsonl、cli-commands.jsonl、生产包截图与语音链路回执。运行实例使用隔离启动器和独立端口，未修改现用服务。</p>
  <p>合入前已同步 main 的 RSI 修复；复核补齐按 turn_id 隔离供应商工具调用 ID，防止不同轮次重名工具的结果与错误状态互相覆盖。更新后的前端全量 137 个文件、991 项用例通过；包含同名调用跨轮次回归。合入阶段的整仓门禁与审查记录随 PR 提供。</p>
</section>

<section id="host-process-diagnostics-20261025" lang="zh-CN">
  <h1>本机进程诊断路由修复 · 2026-10-25</h1>
  <h2>产品设计</h2>
  <p>本机进程、CPU、内存与负载查询由 Main 直接调用受管只读快照，不要求用户提供目录、不新建项目或后台任务。resourceOnly 仍只允许浏览器导航与观察，不将“只读”误解为通用本机执行权限。快照只展示进程名称及资源指标，不返回命令参数和环境变量，不提供终止进程或修改系统的操作。</p>
  <h2>用户故事</h2>
  <p>用户询问“帮我看下当前机器的进程占用情况”时，能在原对话收到真实节点数据。没有代码工作区或其他任务占用工作区时仍可查询；采集失败明确报告不可用，不通过换目录、重复委派或网络检索修复。进程 CPU 百分比解释为 ps 生命周期平均值，单次快照不作为持续异常证据。</p>
  <h2>技术设计</h2>
  <pre>Main / Worker → bash argv: roami agent host processes --input {"limit":10}
→ commands.json / ToolDirectory → host_processes（effect=read）
→ 固定 ps argv + Linux /proc/meminfo + os.getloadavg
→ CPU / RSS 排序、采集时间、指标口径和不可用字段 → 原对话 reply</pre>
  <p>host_processes.py 独立负责采集和解析，worker_catalog 注册并允许 Main 调用；沿用工具上下文、所有者校验、禁用策略与执行回执。ps 使用最小环境、固定参数和 5 秒超时，不接收 cwd、任意 argv 或 shell 字符串；进程输出只读 comm。Linux 提供整体内存与 swap，其他环境无法读取的指标保持 null。工具发现增加本机语义词，主指令、bash 描述、resourceOnly 字段说明和 WORKSPACE_REQUIRED 恢复提示指向相同入口。Go 命令映射继续从同一 JSON 内嵌读取，不新增公开无认证接口或轮询。</p>
  <p>问题证据：原请求先在 Main 因 WORKSPACE_REQUIRED 拒绝 ps，随后被委派到 resourceOnly 并以 TOOL_UNAVAILABLE 失败；换普通目录重试又撞到已跟踪任务的工作区。修复保持浏览器隔离与代码工作区锁，仅补齐本机只读诊断入口。</p>
  <h2>验收记录</h2>
  <p>52 项定向回归通过，覆盖目录发现、排序与单位、缺失指标、采集超时／失败、参数限制、Research 拒绝和禁用策略，以及原始 ps 失败后直接恢复、无后台任务的完整对话。独立临时数据库完成真实 ps 与 /proc 采集。当前配置的 deepseek-4.1-flash 对原问题连续三轮均直接调用 host_processes，回执为 read/succeeded、无后台任务、对话正常结束；没有模拟模型选择或系统输出。三轮使用隔离数据目录与禁用执行的 CLI 路径，不写现用任务、不启动专业会话。证据位于 /tmp/host-process-fix-20261025，未部署现用服务。</p>
  <p>新增英文仅用于模型指令、工具协议定义和 CLI 帮助；遵循国际化规范中的协议字段、终端输出与开发文档例外，不新增界面文案。</p>
  <p>最终 quick 质量门禁通过：Go 全量、Python 静态与格式检查及 1324 项测试、前端 typecheck／i18n（3814 个键）／hover、秘密扫描与文件策略。Research 恢复提示收尾后另跑 23 项相关回归通过；没有前端代码变更，未重复运行前端功能测试与构建。</p>
</section>

<section id="host-execution-scope-20261025" lang="zh-CN">
  <h1>通用本机执行作用域 · 2026-10-25</h1>
  <h2>产品设计</h2>
  <p>修订 PR #452 的处理边界：目录是代码任务的上下文，不是所有本机操作的前提。与项目文件无关且已获用户授权的本机操作由 Main 显式调用 bash scope=host，不创建项目、不借用目录、不误派浏览器 Research。不按进程、磁盘、网络或服务名称增加专用路由。原 host_processes 保留为可选结构化只读接口，不再是提示与恢复的必经入口。</p>
  <h2>用户故事</h2>
  <ul>
    <li>用户查询本机状态或要求执行与项目无关的命令时，没有项目也能取得真实命令结果。</li>
    <li>用户继续代码任务时，保留原任务、目录和执行器；本机作用域不改变已有工作区绑定。</li>
    <li>用户停止命令后，子进程被回收；大输出保留所有者隔离的完整记录。</li>
  </ul>
  <h2>技术设计</h2>
  <pre>Main → bash {argv 或 command, scope:"host"} → ToolDirectory / Tools.validate
→ shell（Main 且无 taskId / workspace / cwd）→ 临时当前目录 → 既有 process.execute
→ 凭证过滤、进程组取消、完整输出外置 → tool_calls（scope、write、真实状态）
Worker → bash scope:"workspace"（默认）→ 原目录绑定与根目录检查
Research → 原浏览器导航／观察协议</pre>
  <p>host 是执行作用域，不是只读权限或文件系统沙箱；通用命令一律保守记录 write，不根据命令名推断安全。用户授权仍由原会话与指令约束，不能从网页、记忆或工具结果取得新授权。临时当前目录只避免继承服务代码／数据目录，不限制绝对路径；需保留的文件产物继续使用真实工作区。Main 指令、工具描述、resourceOnly 说明和错误恢复统一描述作用域；移除本机诊断关键词路由。已注册 Roami 命令继续走原参数、角色和回执协议，不能同时指定 host。Worker／Research 不获得 host，运行时再校验 taskId 和 workspace，默认行为保持原工作区约束。</p>
  <h2>验收记录</h2>
  <p>quick 门禁通过：Go 全量、Python 1342 项测试、格式与静态检查、前端 typecheck／i18n（3814 个键）／hover、秘密扫描与文件策略。新增 18 项回归覆盖 ps／df／uname、任意程序与管道、凭证过滤、角色与工作区拒绝、禁用策略、输出所有者隔离、取消／失败清理和通用恢复。真实模型 deepseek-4.1-flash 对磁盘、系统架构、时间时区、网卡名称四类请求均直接选择 host、执行真实命令，未产生后台任务。全部使用隔离临时数据；没有前端界面变更，未部署现用服务。</p>
  <p>证据位于 /tmp/host-execution-20261025：targeted.log、live-main.json、validation.html／png、quick.log；完整门禁与提交钩子回执见 full.log、commit.log，结果随 PR 提供。</p>
</section>

<section id="rsi-verification-scope-20261026" lang="zh-CN">
  <h2>RSI 验证范围修订 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>Worker 用直接覆盖用户验收条件的检查验证产物；临时探针与产品分开，已有浏览器或测试工具足够时不另造验证驱动。区分检查脚本错误与产品缺陷，完成必要验证后交付真实文件和结果，未验证项明确保留。</p>
  <h3>User Stories</h3>
  <p>用户收到请求的页面和运行说明，不会混入临时自测界面；已有回归测试继续保留。维护者能对照同路由、同题目和同额度的独立执行记录，判断任务是否真正完成。</p>
  <h3>Technical Design</h3>
  <p>修改 server/configuration.py 的 WORKER_INSTRUCTIONS，不改变判定器、预算准入、任务状态、模型路由或冻结题目。没有新增固定步数与时限；达到用户验收条件才结束，检查未完成不冒充成功。隔离容器继续从真实任务状态和容器外判定取得结果。</p>
  <p>improvement.Dockerfile 固定已验收的 Playwright 1.64.1，并按<a href="https://playwright.dev/python/docs/browsers">官方浏览器安装方式</a>安装匹配的 Chromium headless shell。PLAYWRIGHT_BROWSERS_PATH 指向公共只读目录，构建时验证默认 chromium.launch()，移除不能配置 Python 默认启动路径的 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH。运行时仍无网络、非 root 且根文件系统只读；冻结评分渲染器不变。</p>
  <p>RequestBudgetModel 向 Main／Worker 提供当前已计量的剩余额度及输入保守预留估计，在余量接近当前请求成本时提示优先必要工作与真实交接。提示本身计入准入预留，额度不足或用量未知仍在创建提供方之前拒绝；Memory 的结构化输入不加提示，调用方历史不修改。预算信息不含判定器、参考答案或完成证明。评测输入变化单列为 container-uds-v5-budget-status；不把 v5 与旧 v4 的用量差当成同合同优化收益。</p>
  <h3>验收状态</h3>
  <p>修改前主分支 5775296 的 DeepSeek Main/Worker 基线在原 384,000 Token Case 额度内仍因 RSI_TOKEN_BUDGET 失败，实际 326,601 Token／22 次请求。修改指令后的两次同条件复测分别用 180,961／182,290 Token、各 19 次请求完成 Native 执行并保存 HTML 与 README；初始 5 卡、新增、拖移及刷新保留硬检查均通过。两次均 hard_passed=true、pending=true、passed=false，质量尚未评分，不作为正式全套或稳定收益证明。</p>
  <p>浏览器零模型对照：旧镜像默认启动失败、指定系统 Chromium 可用；新镜像默认启动及键盘操作可用，三次均为非 root、只读根文件系统、无网络容器。v4 组合镜像仍出现一次预算失败（297,815 Token／20 次请求），页面检查通过不掩盖任务失败。</p>
  <p>v5 两次独立诊断分别使用 289,200 Token／25 次请求、240,676 Token／21 次请求；Native Attempt 均 succeeded，任务等待验收，两份必要文件的已存储 SHA 均匹配工作区最终文件。功能硬检查全部通过，但 hard_passed=true、pending=true、passed=false，未计为正式质量通过。新增预算提示在受压调用中实际出现；角色隔离、共享预留、提示开销和未知用量边界回归通过，最新 full 共 Python 1,346 项、Go、前端检查与生产构建通过。校准、正式全套验收与连续观察仍独立保留，#443／#445／#446 不因本轮诊断关闭。</p>
</section>

<section id="rsi-quant-correction-replay-20261026" lang="zh-CN">
  <h2>RSI 修正结果重跑合同 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>独立验证器按原题区分静态诊断与程序生成的修正结果。QUANT-03 的 analysis.py 只须重新生成 corrected.json；result.json 的诊断字段仍独立校验，不增加题目没有要求的重生条件。其他量化题仍要求重新生成 result.json，修正文件的提交值与重跑值仍须同时符合冻结数值合同。</p>
  <h3>User Stories</h3>
  <p>实现符合原题时，不会因静态诊断没有被程序重写而误报验证中断；修正结果错误、缺失、与提交不一致时仍失败。维护者看到允许公开的验证失败码，不会收到任意异常文本或凭证。</p>
  <h3>Technical Design</h3>
  <p>authored_grading.RERUN_ANALYSIS 对未重生的输出返回空值；QUANT-03 的 reproducible_code 对比 corrected_expected，其他题仍对比 expected。corrected_run_verified、冻结材料保护、报告来源与数值误差均保持。验证异常只额外保留四个既有白名单代码；其他异常只记录类型。评测协议单列 container-uds-v9-quant-correction-replay，不篡改旧 trial 或复用旧版完整成绩。</p>
  <h3>验收证据</h3>
  <p>真实子进程回归覆盖只生成 corrected.json 的合法程序、错误修正值、提交值与重跑值不一致、静态诊断保留、其他量化题仍须重生主结果，以及异常代码白名单与私有文本隔离；定向 40 项通过。冻结 v6 QUANT-03 产物的零模型重放已从文件缺失中断进入真实数值检查，但其 corrected 结果仍不合格，案例继续失败，原 trial SHA 不变。另行尝试的 v8 操作序列指令候选两项仍预算失败，已拒绝采纳，原 Worker 指令恢复；547,016 Token / 38 请求全部已知并结算。正式评分与连续观察仍未完成，父 issue 保持开放。</p>
</section>

<section id="rsi-explicit-request-deadline-20261026" lang="zh-CN">
  <h2>RSI 模型请求期限修订 · 2026-10-26</h2>
  <h3>Product Design</h3>
  <p>评测沿用显式提供方请求超时与 Case 总期限；未设置请求超时不能暗中变成 60 秒。容器网关保持同一取消、用量结算与未知保护，长请求不得绕过原题期限或 Token 上限。</p>
  <h3>User Stories</h3>
  <p>请求在题目期限内持续生成时不会被未配置的短超时截断；用户设置的 30 秒等短期限继续生效。已经失败的尝试保留，先核对宿主真实用量再决定独立候选复验。</p>
  <h3>Technical Design</h3>
  <p>NativeFilesExecutor 对 Main、Worker、Memory 设置 min(Case 秒数, 显式 route.timeout_seconds 或 Case 秒数)，移除隐含 60 秒回退；原外层整个执行、任务及容器期限保持。模型合同 hash 纳入提供方超时，评测协议单列 container-uds-v10-explicit-request-deadline；不把新期限下的成绩拼入旧 v6/v9。</p>
  <h3>验证与边界</h3>
  <p>定向 26 项通过，覆盖未配置、显式短期限、长期限被 Case 截断、Main/Worker 不同设置、Memory 继承及期限进入合同 hash。本次 v9 Sol Worker 候选因隐含请求期限失败，实际 42,904 Token / 8 请求全部已知并结算，未改现用配置；候选与延迟代理对照的最终结果另附 PR。先前完整 60 项与质量评分、连续观察状态保持。</p>
</section>
