# Roami

**English** | [Simplified Chinese](README.zh-CN.md)

> **Turn your development machines into an always-on AI coding workstation.**

**Roami** lets you **connect back to your own development machines from anywhere,
at any time, using a phone, tablet, or laptop.** You can keep coding, run tests,
watch logs, debug in a browser, and supervise Claude Code, Codex, or other AI
coding agents while the real work continues on the machine that owns it.

It solves a concrete problem: **complex development work should not be broken
apart by your device, network, or schedule.** Your code, terminals, dev
services, browser, and agents all keep running on the development machine. You
can switch devices, disconnect, leave your desk, and come back to the same
working scene. Unless you close them intentionally, the work does not disappear
because a local terminal exited, a browser tab closed, or a laptop lid shut.

**Roami at a glance:**

- **Everything is organized by project**: each repository becomes a mission
  control with its tasks, worktrees, agent formations, and activity — the
  workbench is a battle map of what needs you across all projects.
- **Remote development without losing the scene**: check progress from a phone,
  add instructions from a tablet, take over coding from a laptop, while the
  working context stays on the development machine.
- **Long tasks keep running**: tests, builds, migrations, logs, and debugging
  sessions survive lid closes, network drops, and device changes.
- **AI agents become manageable**: describe a task and an agent starts working
  in an isolated worktree; watch it as a terminal or as a rendered conversation,
  and send follow-ups from any device.
- **Complex work can be orchestrated**: race two agents on the same task, or
  split a goal across a swarm with dependencies, a board, and a shared feed.
- **More than one machine**: a laptop, a workstation, and a Jetson can all sit
  behind one console — switch between them from the same window, and one page
  tells you whether they are all healthy.

Roami is not another cloud IDE. It connects to your real development machines and
puts projects, terminals, browser, files, tasks, and AI agents into a remotely
controllable workspace. What you see is a console; behind it is still the
development environment and toolchain you already use.

![Roami — the workbench on the left, a live Claude Code session on the right](docs/screenshots/hero.en.png)

<sub>One window: what needs you across every project, and the agent that is working right now.</sub>

## Core Capabilities

- **A project is the unit of work**: sessions, tasks, worktrees, and agent
  formations all hang off the repository they belong to — open a project and
  everything about it is one screen away.
- **Close the lid, the work keeps running**: terminals, dev servers, tests, and
  agent conversations live on the development machine — a dropped network or a
  shut laptop never kills the scene.
- **Any device is the same desk**: open the Web console from a phone, tablet, or
  laptop and land back in the exact project you left — zero install, no native
  app to update.
- **Describe a task, an agent takes it**: type what you want, and Claude Code or
  Codex starts in an isolated worktree on its own branch — race two agents on the
  same task and keep the better result.
- **Read agents, don't decode them**: a running Claude Code or Codex session can
  be read as a real conversation — messages, diffs, and folded tool runs — or as
  the raw terminal, whichever you need at that moment.
- **Formations split one goal across many hands**: hand the API to one member,
  the frontend to another, tests to a third — a shared board and message feed
  keep them in sync, and dependencies unlock the next step automatically.
- **The debugging browser and a real phone live on the dev machine too**: login
  state, screenshots, and repro flows stay put, so remote UI debugging picks up
  right where it was.
- **Built for humans and agents to share one workspace**: take over from the Web
  console by hand, or let agents read state, collect output, and keep pushing.

## Screenshots

**The workbench answers one question: what needs me?** Projects that are waiting
on you come first, each with its running tasks, worktree count, and swarms —
then recent activity across every repository.

![Workbench: what needs you, per-project tasks, and recent activity](docs/screenshots/workbench.en.png)

**Read the agent, not the terminal.** The same Claude Code or Codex session can
be rendered as a conversation: messages, code blocks, diffs, and folded tool runs,
with a status bar for mode, context use, and elapsed time — and a box to reply in.

![A Claude Code session rendered as a conversation](docs/screenshots/chat.en.png)

**Or take the raw terminal, because it is a real tmux session.** Full TUI
fidelity, tabs that persist per machine, a file drawer and Git panel one click
away, and — on a phone — a key bar and voice input.

![The same session as a live terminal, with the toolbar and mobile key bar](docs/screenshots/terminal.en.png)

**A formation, at a glance.** A live topology of every member, a shared
collaboration wall, a drag-to-flow board, and an inbox of items waiting for
review — a goal split across agents stays legible.

![Swarm dashboard: topology, plaza, and board](docs/screenshots/swarm.en.png)

**Many machines, one console.** The hub page says in one line whether the hub is
healthy, lists every machine with its latency, CPU, memory, and session count,
and keeps a log of what happened lately — who dropped, who came back, and how
long they were gone.

![Hub page: hub health, machines, and the recent event log](docs/screenshots/hub.en.png)

**Settings you can actually find things in.** Search across every setting by
name, description, or key; categories are grouped by scope — what follows you
between machines, what belongs to this machine, and what applies to the whole
cluster.

![Settings: search, category tree, and one page per category](docs/screenshots/settings.en.png)

**Browse and edit files without leaving the console.** Folders and files in two
resizable columns, a preview on hover, and drag a path straight into a terminal
or an agent prompt.

![File workspace: folder column, file column, and preview](docs/screenshots/files.en.png)

**Drive a real browser from the console.** The dev machine's Chrome is mirrored
into the console — open tabs, navigate, click, and type. Debug a web app, keep a
login session, or let an agent reproduce a flow, all on the development machine.

![Browser mirror: a live Chrome tab driven from the console](docs/screenshots/browser.en.png)

**Control a real phone from the console.** Mirror an Android device over adb — the
live screen, streaming stats, and remote nav bar — to reproduce mobile flows or
check an app right next to your terminals.

![Phone mirror: a live Android device inside the console](docs/screenshots/phone.en.png)

## Mobile: work from anywhere

**Your whole workspace fits in a phone.** Open the console in any mobile browser —
no app to install — and land back in the same projects, tasks, and agents.
A bottom bar carries the five places you actually go, and a session dock keeps the
running agent one tap away.

![Roami on a phone: the workbench and the session dock](docs/screenshots/mobile-office.en.png)

**Talk to an agent from your phone.** Open a session and read it as a
conversation — the same cards, diffs, and status bar as the desktop — then type or
dictate a follow-up and keep the task moving without a laptop.

![Chatting with Claude Code on a phone](docs/screenshots/mobile-chat.en.png)

## Why It Exists

Remote development is easy for small tasks. Once the work becomes complex, it
starts to hit many breakpoints:

- dev servers need to keep running
- tests, logs, and builds need multiple terminals
- browser state matters for reproducing bugs
- agents need isolated context and follow-up instructions
- long tasks should keep running while you are offline
- you need to quickly understand, per project, what is still running and what
  is waiting for you
- and once there is more than one machine, you need to know which one a session
  is even on

Roami treats the development machine as the single real working scene. The server
keeps work alive, and the Web console lets you reconnect from any device. When
automation is needed, scriptable interfaces expose sessions, tasks, logs, and
agent orchestration.

## Typical Use

1. Start Roami on your development machine.
2. Open the Web console from a phone, tablet, or another computer.
3. Open a project, enter an existing task or terminal, and continue the
   previous working scene.
4. Describe a new task and let Claude Code, Codex, or another agent run it in an
   isolated worktree on the development machine.
5. Leave the browser or close your local terminal; terminals, services, logs,
   and agents keep running on the development machine.
6. Come back later from any device: the workbench shows which projects need
   input, and each project shows where its tasks got to.

Roami is not mainly "one more terminal tool." It turns the development machine
into a continuously available workspace. The terminals, running services,
debugging browser, AI agent conversations, and task state on that machine do not
vanish just because a local device shut down, SSH disconnected, or a browser tab
closed.

## Install And Start

`roami` is a single binary with an embedded frontend and an integrated session core.
The web console needs no Go/Node/npm on the target; browser automation uses Node and Chrome. Config and data live in
`~/.roami/` (`config.yaml` is generated on first run).

### Option A — install as a service (recommended for always-on / 24×7 machines)

One line downloads the binary and registers it as a persistent **systemd**
service (survives reboots and logout):

```bash
curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash
```

`install.sh` installs `roami` into `~/.local/bin` and sets up a user service —
manage it with `systemctl --user {status|restart|stop} roami`. Env switches:
`ROAMI_VERSION=vX.Y.Z`, `ROAMI_BIN_DIR=DIR`, `ROAMI_SYSTEM=1` (system-wide service,
needs sudo), `ROAMI_NO_SERVICE=1` (install the binary only).

### Option B — run the binary manually

Grab the build for your OS/arch from the
[Releases](https://github.com/ybz21/Roam/releases) page and run it directly (no
service — good for macOS or a quick try):

```bash
# example: Linux x86_64
curl -fsSL -o ~/.local/bin/roami \
  https://github.com/ybz21/Roam/releases/latest/download/roami-linux-amd64
chmod +x ~/.local/bin/roami
roami                    # starts the Web console on 0.0.0.0:13579
```

### Option C — from source (development)

```bash
git clone https://github.com/ybz21/Roam.git
cd Roami
./start.sh --dev       # build CLI/chrome/skills + frontend + backend from source, then run
```

`start.sh` also supports `stop` / `status` / `logs` / `fg`; plain `./start.sh`
runs already-built artifacts without recompiling.

On first launch there is **no password**: open the Web console in a browser and
set one before entering. Change it later under **Settings → Security**, or edit
`~/.roami/config.yaml`. By default the console listens on `0.0.0.0:13579`
(self-signed HTTPS, because microphone and clipboard need a secure context), so
devices on the same LAN can reach it. For remote access, prefer Tailscale,
Cloudflare Tunnel, SSH forwarding, or frp.

Exposing Roami through **frp with HTTPS** so mobile voice input and clipboard
continue to work through the tunnel is covered in
**[docs/deploy/frp.md](docs/deploy/frp.md)** (bilingual).

Full installation, deployment, remote access, and command-line automation notes
live in **[docs/install/](docs/install/)**.

## More Than One Machine

A single Roami is a complete product; you only need this section when you have a
second machine. Every machine keeps running its own sessions, agents, and files —
the hub only routes to them, so nothing about a machine depends on the hub being
alive except reaching it from outside.

**The hub** is the same binary started in hub mode. It runs no sessions, no
agents, and no browser — just the registry, the console, and the tunnel:

```yaml
# ~/.roami/config.yaml on the hub
cluster:
  mode: hub
  public_url: https://roami.example.com    # the address machines dial back on
```

**Each machine** dials out to the hub with a one-time enrollment token (issue it
under **Settings → Cluster**), then swaps it for a long-lived credential:

```yaml
# ~/.roami/config.yaml on a machine
cluster:
  hub: https://roami.example.com
  token: <one-time enrollment token>
  name: workstation                        # display name, defaults to hostname
```

Because the tunnel is outbound, a machine behind NAT or a home router needs no
port forwarding. From then on:

- the machine switcher in the console (and under **More** on a phone) moves the
  whole workspace to another machine — terminal tabs are remembered per machine,
  so switching back lands you on the same sessions;
- the **hub page** shows hub health, every machine's latency, CPU, memory, and
  session count, plus an event log of drops and reconnects;
- a machine whose numbers keep climbing raises a dot on the navigation rail —
  the health check watches the *shape* of the curve rather than absolute
  thresholds, so a bigger machine doesn't false-positive;
- **Full monitor** on any machine opens the same monitoring panel the
  `roam.host-monitor` plugin draws locally — CPU, GPU, disk, and network history.

## For Claude Code / Codex

If Claude Code, Codex, or another command-line coding tool is installed on the
development machine, the project page is the fastest way to use it: describe a
task and the agent starts in an isolated worktree on its own branch, so parallel
tasks never step on each other. You can also race Claude Code and Codex on the
same task and keep the better result, or run any tool directly inside a
persistent Roami terminal. Execution, output, context, and the follow-up channel
all stay on the development machine — when you return from a phone or tablet,
you can read where it got to and add more instructions.

For more complex work, launch a formation: a swarm splits the goal across
multiple members — one handles the API, one the frontend, one tests. A shared
board and message feed synchronize progress, and dependencies unlock the next
step when earlier work is done.

## Command Line And Automation

Roami also provides command-line entry points for scripts, automation, and AI
agents. This is not the main entry point for most users; start from the Web
console in most cases.

`roami` is the single entry point. Plugin commands are grouped by plugin name
(any unique prefix works). Session operations use `roami session`; unknown session commands are rejected:

```bash
roami help                        # what is installed and how to reach it
roami cron list                   # scheduled tasks
roami im send --text "done"       # message yourself through the IM bridge
roami host stats                  # host resource snapshot
roami session ls                  # sessions — integrated core
roami session swarm ls              # session and swarm operations
roami -addr 0.0.0.0:13579         # no subcommand: start the web console (unchanged)
```

Underneath:

- `roami session`: manages persistent sessions, background tasks, agent workers, swarms,
  and machine-readable state.
- `roami chrome`: drives Chrome on the development machine for UI debugging,
  screenshots, form flows, and automated validation.

Plugins extend the console itself — `roam.host-monitor` contributes the resource
monitor, `roam.cron` adds scheduled prompts with its own configuration panel.
Whatever a plugin declares in its manifest shows up as a `roami <name> <command>`
group with no extra wiring.

Command details are intentionally not expanded on the home page, so the README
does not become a tool manual. When needed, see
**[docs/install/](docs/install/)**, `roami help`, `roami session help`, and `roami chrome help`.

## Development And Contribution

Install the repository Git hooks once per clone:

```bash
bash scripts/dev/install-git-hooks.sh
```

The pre-commit hook runs the quick quality gate. CI runs the full gate on pushes
and pull requests:

```bash
scripts/dev/quality/check.sh quick
scripts/dev/quality/check.sh full
```

Build and run the Web console:

```bash
./start.sh --dev fg
```

Frontend only:

```bash
cd frontend
npm install
npm run dev
```

Backend only:

```bash
TTMUX_WEB_PASSWORD=dev go run ./cmd/roami server
```

CLI smoke test:

```bash
ROAMI_BIN=/tmp/roami bash tests/test-session-cli.sh
```

Agent-facing rules for this repository (design system, i18n, quality gates) live
in **[AGENTS.md](AGENTS.md)** — the single source both Codex and Claude Code read.

## Security Notes

Roami can control your development machine's terminal, files, browser, and
agents. Treat it as close to SSH access. For real deployments:

- Use a strong access password, and enable two-factor authentication when
  needed.
- Prefer Tailscale, Cloudflare Tunnel, SSH forwarding, or frp for external
  access.
- Do not expose the Web console port directly to the public Internet.
- Enrollment tokens are one-time and expire (30 minutes by default); machines
  keep a long-lived credential afterwards, and the hub stores only its hash.
- The diagnostic endpoint (`ROAMI_PPROF`) is off by default and refuses to bind
  anything but loopback.
- Run it only on machines and accounts you trust.

## Docs

- [docs/features.md](docs/features.md) - full feature list
- [docs/install/](docs/install/) - installation and deployment
- [docs/design/](docs/design/) - design docs for swarm orchestration, plaza
  boards, cluster topology, and Web integration
- [backend/README.md](backend/README.md) - backend implementation details

## License

GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE).
