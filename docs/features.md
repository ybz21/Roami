# Roami feature inventory

**English** | [简体中文](features.zh-CN.md)

Updated 2026-10-23 against the current Roami mainline and product entry points.
This includes configurable integrations and explicitly marked experimental capabilities.
See the [README](../README.md) for the product tour and the [Roadmap](../ROADMAP.md) for planned work.

Some capabilities require the corresponding software, device, account, permissions, or model service.

## 1. Remote access and multiple devices

- Self-hosted web console accessible from a computer, tablet, or phone browser.
- Native Android client and installable home-screen web app.
- Projects, tasks, files, and sessions live on the development machine; host work continues after a client disconnects.
- Persistent theme, language, quick commands, and workspace preferences; node-specific session and workspace restoration.
- Desktop navigation, project/session tree, workspace tabs, adjustable splits, file/Git inspectors, and terminals.
- Four phone destinations: Home, Projects, Tools, Settings; secondary pages for messages, tasks, and memory.
- Software-keyboard handling, safe areas, touch targets, back navigation, and pull to refresh.
- HTTPS by default, self-signed CA installation guidance, and access through an existing VPN, HTTPS proxy, or tunnel.

Sources: [routing](../frontend/src/app/AppRoutes.tsx), [navigation](../frontend/src/app/navigation.ts), [mobile setup](deploy/mobile.md).

## 2. Control professional coding agents

| Agent | Available capabilities |
|---|---|
| Claude Code | Installation discovery, version checks, installation/updates, launch command, model configuration, quota information, persistent terminal, conversation reader, coding-task delegation |
| Codex | Installation discovery, version checks, installation/updates, launch command, model configuration, available quota information, persistent terminal, conversation reader, coding-task delegation |
| OpenCode | Installation discovery, version checks, installation/updates, launch command, model configuration, persistent terminal, supported conversation reading |
| Pi | Installation discovery, version checks, installation/updates, launch command, model configuration, persistent terminal |

- Manage agents in the capability center; inspect detected version, executable location, and verifiable login state.
- Open a terminal for CLI login, interaction, and model selection.
- Save and apply model-provider presets, credential references, and supported configuration recovery.
- Read output, send follow-up instructions or confirmation keys, and take over the terminal from any client.
- Recognize supported running, idle, and confirmation states; show context, duration, or quota when reliably available.
- Conversation rendering with messages, code, Markdown, diffs, collapsible tool activity, copying, and file references.
- Original agent TUIs remain available. Login, quota, and conversation support depend on CLI versions, providers, and observed evidence.

Sources: [agent catalog](../frontend/src/components/capabilities/AgentCatalog.tsx), [installation/version discovery](../internal/agentinventory/), [conversation components](../frontend/src/components/chat/).

## 3. Built-in assistant and conversations

- Streaming conversations, follow-up instructions, generation cancellation, and history recovery.
- Drafts, copying, code blocks, Markdown, and clickable file/artifact links.
- File and image attachments, upload, paste, and preview; image input follows configured model capabilities.
- Main/Worker model configuration, model discovery, testing unsaved configuration, and generation parameters.
- Context inspection, manual compression, automatic context management, and traceable compression state.
- Desktop task, message, and memory workspace beside the conversation, with persistent visibility preferences.
- Conversation branches, source navigation, linked messages, and task navigation.
- Built-in access to files, Shell, HTTP, Skills, MCP, browser, and registered capabilities.

Sources: [assistant interface](../frontend/src/components/agent/), [runtime](../agent-runtime/README.md).

## 4. Tasks, execution, and delivery

- Start tasks from natural language or a project; select an existing project/session or a new working directory.
- Choose built-in execution or supported professional coding agents while retaining task identity and conversation origin.
- Parent/child tasks, queues, concurrency, dependencies, task revisions, and follow-up work.
- Add instructions, continue, cancel, accept work, and inspect verification state.
- Continue work in the original professional-agent session with terminal and workspace context attached.
- Actual preparation, queued, running, waiting, verification, success, failure, interruption, and cancellation states.
- Separate task outcomes, human decisions, and executor reports, with inspectable artifacts and evidence.
- Artifact previews/downloads, original file sources, execution attempts, and error details.
- Inspect task-owned resources such as browsers; pause, resume, or take over supported resources.
- Recovery after interruption/restart, idempotent submission, execution reconciliation, and uncertain-result records.
- Linked tool, task, and model traces with timing and usage.

Sources: [task interface](../frontend/src/components/agent/AgentTasks.tsx), [runtime](../agent-runtime/README.md), [execution CLI](../cmd/roami/agent-execution.go).

## 5. Memory and working experience

- Personal, project, conversation, and task scopes; preferences, facts, decisions, and summaries.
- Saved, candidate, and activity views; filtering by scope, entity, kind, and date.
- Keyword and Chinese search, with conversation/task/document/artifact evidence.
- Manual memory creation, background candidate extraction, confirmation, and rejection.
- Editing, versions, provenance, forgetting, and withdrawal of source influence.
- Daily work activity and summaries organized in the configured time zone.
- Duplicate-preference handling and source validity; retrieval retains scope and provenance constraints.
- Memory management in Settings and the Home workspace; full secondary pages on phones.

Sources: [memory interface](../frontend/src/components/agent/AgentMemory.tsx), [memory service](../agent-runtime/src/roami_agent/memory/).

## 6. Projects and organization

- Register an existing repository, clone, create a directory, or initialize a Git repository.
- Pinning, display names, default agent, and default base branch.
- Project-level tasks, sessions, worktrees, swarms, activity, and pending work.
- Entry points for existing tasks/worktrees and new isolated workspaces.
- Project activity, branch state, running/waiting sessions, and work awaiting completion.
- Open terminals, conversations, files, and Git from the project.
- Remove project registration independently of session and directory lifecycles.

Sources: [projects](../frontend/src/components/projects/Projects.tsx), [project API](../backend/api/project.go).

## 7. Git, worktrees, and agent races

- Status, diffs, stage/unstage, discard, commits, and commit details.
- Push, pull, fetch, synchronization, and remote branch information.
- Branches, tags, stash, commit graph, and supported checkout/merge/rebase/reset operations.
- Create, list, and compare worktrees, including committed and uncommitted differences from a base.
- Attach sessions to worktrees, fork child sessions, and fork work into a new worktree.
- Merge to the base, finish, remove, prune, and check occupancy/uncommitted changes.
- Read branch-associated PR information through an installed, authenticated GitHub CLI.
- Run competing agent attempts in independent worktrees, select a result, merge, and clean up.

Sources: [Git API](../backend/api/git.go), [worktree API](../backend/api/worktree.go), [races](../backend/api/race.go).

## 8. Persistent sessions and terminals

- Real tmux-backed Shell sessions, development servers, logs, and agent TUIs.
- Create, strictly target, rename, close, and recover sessions; persistent session history.
- Child sessions, parent/child relationships, session trees, windows, and panes.
- Tabs, standalone terminals, font size, copying, redraw, and reconnection.
- Alternate-screen TUI scrolling, narrow-screen redraw, and input handling.
- Phone key bar, arrows, independent send box, and software-keyboard clearance.
- Quick commands, environment management, and multiline prompt submission.
- Running/waiting/idle/history states and resource information.
- Machine-readable CLI output, screen capture, logs, and key/prompt submission.

Sources: [session CLI](development/session-cli.md), [terminal interface](../frontend/src/components/terminal/).

## 9. Swarm orchestration

- Goal, working directory, Leader, members, roles, and duties.
- Claude Code/Codex members and template-based collaboration instructions.
- Member topology, dependencies, task state, completion, and unlocking.
- Shared plaza messages, listening, human follow-ups, and member reports.
- Work board, assignments, pending decisions, and collaboration progress.
- CLI creation/inspection/control and the Web collaboration workspace.

Sources: [swarm interface](../frontend/src/components/swarm/Swarm.tsx), [swarm CLI](../internal/cli/swarm/).

## 10. Capability center and market

- Seven categories: Agents, Plugins, Skills, MCP, CLI, Tools, Market; category URLs and deep links.
- Search, provenance, descriptions, actual state, details, and management of mutable entries.
- Skill creation, templates/Markdown preview, SKILL.md upload/paste, editing, and removal.
- Local-process and remote MCP configuration, JSON import, explicit connection, tool discovery, and connection state.
- CLI executable, argv, working directory, input replacement, creation/import/edit/removal.
- Inspect built-in tool parameters and read/write properties.
- Search skills.sh, MCP Registry, and npm; preview packages and confirm edited configuration before import.
- Add/edit/enable/remove market sources and retain import provenance.
- Persistent managed configuration, duplicate checks, batch validation, environment-based secrets, and built-in protection.
- Managed capabilities serve the built-in assistant; professional CLIs retain their own Skill/MCP configuration.

Sources: [capability interface](../frontend/src/components/capabilities/), [persistence and market](../agent-runtime/src/roami_agent/server/).

## 11. Files and editing

- Directory tree and flat list, hidden files, sorting, path entry, and navigation.
- Filename/content/global search and navigation to matching lines.
- Create files/directories, upload files/folders, download, rename, copy, move, delete, and inspect properties.
- Monaco editor, file tabs, split panes, draggable tabs, preview, and source view.
- External-change detection and reloading open files.
- Markdown, Mermaid, images, HTML, PDF, and Office previews; some formats need conversion dependencies.
- Relative assets/links in HTML and authenticated file-access links.
- Drag or reference files into terminals, agent input, and conversations.

Sources: [file workspace](../frontend/src/components/files/), [file API](../backend/api/files.go).

## 12. Browser mirror and automation

- Mirror the host's real Chrome with existing login state, tabs, and browser data.
- Create/switch/close tabs; navigate, back, forward, reload, and group tabs.
- Click, type, scroll, keyboard interaction, adaptive quality, and stream state.
- Headed/headless mode, executable, profile, size, scale, and restart settings.
- Health checks, reconnection, sleeping background pages, and reclamation settings.
- `roami chrome` locators, text/attributes/DOM, forms, page scripts, screenshots, PDF, and recording.
- Task-owned browser resources, observations/actions, navigation, and human takeover.
- Host browser start page, bookmarks, and opening externally.

Sources: [browser interface](../frontend/src/components/mirror/BrowserView.tsx), [automation](../backend/browser/automation/).

## 13. Android device and emulator mirror

- Mirror a connected physical Android device or emulator.
- Discover USB devices, network ADB targets, and existing local AVDs.
- Taps, swipes, text, system keys, application listing/launch, and UI structure.
- Quality/stream state, dependency checks, connection tests, start/stop, and connect/disconnect.
- AVD device/system-image selection, creation progress, deletion, and lifecycle management.
- Unauthorized/offline USB recovery guidance and wireless-debugging switching.
- Host requirements such as KVM; device operations require corresponding ADB authorization.

Sources: [device backend](../backend/phone/), [phone mirror](../frontend/src/components/mirror/PhoneView.tsx).

## 14. Native Android app and home-screen web app

- Android 8.0+ APKs, distributed as consistently signed server Release attachments.
- Multiple saved server environments, selected-environment startup, and shake to return to environment selection.
- WebView with the current workspace, native bars, safe areas, and keyboard handling.
- Self-signed certificate confirmation and remembered trust.
- File selection/upload/download and on-demand microphone permission.
- Foreground-service connection for session/task/assistant notifications without Google push services.
- Allow/Deny actions for supported session confirmations in notifications.
- Home-screen widget for running sessions and pending work, opening sessions, and submitting tasks; state-driven app badges.
- APK download from the server installation page and system-installer updates; app/server versions are independent.
- Android/iOS home-screen web app, Web Push configuration, and installation guidance.
- Service Worker snapshots of selected recent content for offline viewing: notifications, session/project overview, and recent conversations.

Notifications, badges, and Web Push depend on permissions, system settings, and network access.
The Android app is a remote client; device mirroring is a separate capability.

Sources: [Android project](../mobile/android/), [mobile setup](deploy/mobile.md).

## 15. Reminders, messages, and proactive foundations

- One-shot, relative-time, and daily time-zone-aware reminders.
- Explicitly subscribed model-generated daily briefings with sources, results, and cancellation.
- Notifications categorized as outcomes, human decisions, reminders, and suggestions.
- Category preferences, time zone, quiet hours, hidden previews, and suggestion frequency.
- Message center, source navigation, read state, and App/Web Push delivery records.
- Opt-in task-event suggestions with provenance and usage records.
- Separate management of reminders, briefing generation, suggestions, and task execution.

Sources: [reminders and delivery](../agent-runtime/README.md), [message settings](../frontend/src/components/settings/agent-message-settings.tsx).

## 16. Built-in plugins and integrations

| Plugin | Capabilities | Requirements |
|---|---|---|
| Host Monitor | CPU/GPU/memory/disk/network/temperature, trends, status bar, and existing swap-management commands | Host tools; system privileges for swap operations |
| Cron | Interval, daily-time, and supported cron schedules; Agent/Shell execution, preview, run now, history | Configured jobs and running scheduler |
| Keepalive | Selected-session guarding, quiet-time/rule-based follow-ups, dry runs, history | Explicit session guarding opt-in |
| Review Mesh | Claude/Codex peer review, structured findings, idle triggers, feedback | Relevant CLIs and review configuration |
| IM Bridge | Feishu bot bidirectional text, group mentions, direct messages, owner binding, concierge, task delegation, results/notification replies | Feishu application, messaging permissions, configured agent |

- Package/local-directory/upload installation, details/configuration, enable/disable, uninstall, and built-in restoration.
- Manifest-driven configuration, masked secrets, commands, permission declarations, audit, and logs.
- Builtin, Node, and exec runtimes; SDK, development scaffold, validation, and local execution commands.
- Plugin-owned status, configuration, and private persistent storage.

Roami's DingTalk provider is currently an extension placeholder. Universal messaging and the personal digital twin integrate SuperWork in the [Roadmap](../ROADMAP.md).

Sources: [plugins](../plugins/), [plugin development](../plugins/README.md).

## 17. Multiple machines and resources

- Standalone-node and hub modes in the same program.
- One-time enrollment tokens, outbound node connections, and persistent credentials.
- Switch machines to access their projects, sessions, terminals, files, browsers, and capabilities.
- Hub/node online state, latency, resource snapshots, session counts, and connection events.
- Node-health trends and host-monitor entry points.
- Optional P2P/WebRTC direct connections and fallback, with STUN, timeout, and transport settings.

Direct connections depend on configuration and network conditions.

Sources: [cluster interface](../frontend/src/components/cluster/), [connectivity deployment](deploy/frp.md).

## 18. AI activity

- Activity overview, date-based heatmap, and project activity.
- Aggregate available session, conversation, task, tool, and model-usage records.
- Linked Git activity, projects, historical archives, execution, and delivery records.

Sources: [activity interface](../frontend/src/components/mobile/MobileHome.tsx), [activity API](../backend/api/daily-activity.go).

## 19. Settings, security, and operation

- Searchable settings, theme/language/density, keyboard shortcuts, status bar, and quick commands.
- Assistant models, memory, messages, professional agents, browser, devices, and voice services.
- Recording/transcription through supported Doubao/Volcano and compatible interfaces.
- Environment variables, synchronization preview, and pushing session environments.
- Initial password setup, password changes, optional TOTP, and failed-login lockout.
- HTTPS root CA/leaf certificates, certificate downloads, and secure contexts.
- Full Linux/macOS x86-64/ARM64 bundles with private Python and production dependencies.
- Linux systemd/macOS launchd service, update detection, runtime supervision, and idle-upgrade coordination.
- Unified database status, backup/restore, layout migration, and recovery for managed runtime data/artifacts.

Sources: [settings](../frontend/src/components/settings/), [installer](../install.sh), [storage CLI](../cmd/roami/).

## 20. CLI and automation interfaces

| Entry point | Scope |
|---|---|
| `roami server` | Console, address, frontend, and TLS settings |
| `roami session` | Sessions, windows/panes, screen/input/history, ancestry, swarms, environments |
| `roami project` | List/details/create, preferences, sessions, activity, registration removal |
| `roami agent` | Conversations, messages, tasks, execution, artifact reports, reminders, memory, notifications, capabilities, traces |
| `roami chrome` | Browser navigation, observation, interaction, screenshots, PDF, recording, page lifecycle |
| `roami adb` | Host ADB passthrough |
| `roami plugin` / `roami <plugin>` | Plugin installation/development/configuration/commands/status/audit |
| `roami auth` | CLI login, logout, identity |
| `roami db` | Database status, backup, restore, migration |
| `roami help` / `version` / `completion` | Discovery, version, Shell completion |

Sources: [unified CLI](../cmd/roami/cli.go), [session commands](../internal/cli/).

## 21. Conditional and experimental capabilities

- **Linux X11 Computer Use:** screenshot observation, clicks, keys, and typing through an existing desktop adapter; requires runtime opt-in, X11, and a vision-capable Worker model.
- **iOS device/simulator mirror adapter:** macOS simctl/idb backend code exists; source explicitly retains real-Mac/device integration validation. Listed as experimental.
- **Image input, browser/desktop observations, P2P, and device operations:** enabled according to provider capabilities, configuration, and host environment; actual availability is reported.

Sources: [Computer Use](../agent-runtime/README.md), [iOS adapter](../backend/phone/ios.go).

## 22. Ancillary interfaces

- Host browser start-page and site-bookmark reading/saving.
- Basic player, team, lineup, and transfer-record data APIs, accessed through the API.

Source: [server routes](../backend/server/server.go).

## 23. Next stage

- Agent RSI and a recursive self-improvement loop.
- Reuse SuperWork messaging to integrate Feishu, DingTalk, and WeChat into a personal digital twin that replies to group/direct conversations.
- OKR breakdown, daily autonomous execution, delivery, and review.

Delivery goals and milestones for these three tracks live in the [Roadmap](../ROADMAP.md).
