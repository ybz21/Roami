# Roami Roadmap

**English** | [简体中文](ROADMAP.zh-CN.md)

> From commanding many agents to a personal digital twin that improves itself,
> communicates for you, and works toward your goals every day.

Roami lets you control Claude Code, Codex, OpenCode, Pi, and other agents from a
phone or computer. The next step is a continuous working loop: **learn from
experience, handle communication, and actively advance long-term goals.**

This document describes the next product stage. For what is available in Roami
today, see the [complete feature list](docs/features.md). Messaging will reuse
existing capabilities in the external [SuperWork](https://github.com/blade-hq/super-work)
repository and integrate them with Roami conversations, tasks, memory, and remote
control.

## Three priorities

| Priority | Track | Intended outcome | Roami status |
|---|---|---|---|
| 1 | Agent RSI | Improve the agent from real work and feedback, with measured results | Planned |
| 2 | Universal messaging and a personal digital twin | Handle group chats and direct messages across Feishu, DingTalk, WeChat, and more; reply and dispatch work | Integration planned |
| 3 | OKR-driven autonomous work | Turn goals into actionable work and make progress, deliver, and review every day | Planned |

The ordering expresses product priority. Milestones are completed through actual
implementation and validation; release dates will follow delivery progress.

## 1. Agent RSI: recursive self-improvement

RSI means Recursive Self-Improvement. The goal is to improve the whole agent:
understanding goals, planning, choosing tools, using memory, coordinating other
agents, and verifying delivery. The mechanism that proposes, tests, and selects
improvements should improve through the same process.

### The working loop

1. **Collect experience.** Connect task goals, execution, observed outcomes,
   failures, and user corrections.
2. **Find an improvement.** Identify recurring problems and produce a specific,
   testable hypothesis.
3. **Make the change.** Update prompts, Skills, tool combinations, execution
   strategies, or relevant code, retaining versions and source evidence.
4. **Evaluate it.** Compare with the previous behavior using isolated tasks and
   replay cases; measure success, user intervention, elapsed time, and cost.
5. **Apply and review.** Activate useful changes, observe subsequent work, and
   retain traceable versions and rollback.

### Milestones

- [ ] Unified task experience and feedback records linked to original evidence.
- [ ] Agent-generated improvement tasks using professional coding sessions,
      workspaces, and existing verification capabilities.
- [ ] Baseline cases, replay evaluation, and regression checks with before/after
      results for each change.
- [ ] Improvement activation, ongoing outcome tracking, and rollback.
- [ ] Iteration on the improvement mechanism itself, forming a continuous RSI loop.

### The user-visible outcome

A correction becomes a verifiable behavioral improvement. When a similar task
returns, the agent uses the improved approach. Each active change can explain
which problem motivated it, what changed, what was tested, and whether it helped.

**Existing foundations:** task and execution records, verification, source-backed
memory, Skills/MCP/CLI, isolated workspaces, professional coding agents, and peer
review. The next step connects them into the self-improvement loop.

## 2. Universal messaging: your personal digital twin

Make Roami a digital twin that handles everyday communication on your behalf.
Group chats, direct messages, and work enter one workflow: it understands the
context, remembers your preferences, replies automatically, dispatches work to
the right agent, and returns results to the original conversation.

### Integration direction

**Reuse SuperWork's messaging foundation and connect it to Roami's agents.**
SuperWork already provides multiple accounts, message synchronization, group and
direct conversations, search, sending as the account owner, Hooks, and downstream
delivery. Integrate that foundation with Roami conversations, memory, tasks,
notifications, and remote takeover.

| Channel | Integration goal |
|---|---|
| Feishu | Bring existing messaging into unified group/direct context and task reporting |
| DingTalk | Reuse SuperWork connections and messaging for digital-twin replies and execution |
| WeChat | Join the common channel model for group chats, direct messages, and digital-twin replies |
| More channels | Extend existing connectors and sources through the common integration model |

### Milestones

- [ ] Connect SuperWork accounts, conversations, messages, and events while
      retaining source-platform and account identity.
- [ ] Configure reply rules per account, contact, and group, including mentions,
      continued conversation, and human takeover.
- [ ] Configure the twin's communication style, work preferences, available
      memory, and reply scope.
- [ ] Convert work discussed in messages into Roami tasks, dispatch to suitable
      agents, and support follow-up questions.
- [ ] Return progress, results, and artifacts to the original conversation, with
      processing history in the workspace.
- [ ] Connect Feishu, DingTalk, and WeChat group/direct workflows with consistent
      reply state and cross-device takeover.

### The user-visible outcome

After you leave your computer, your digital twin continues replying and handling
work in the conversations you have configured. From your phone, inspect what it
said, see work in progress, and take over the discussion.

**Existing foundations:** SuperWork messaging, plus Roami's Feishu bot bridge,
agent tasks, memory, and notifications. This track delivers their unified entry
point and the personal digital-twin experience inside Roami.

## 3. OKR-driven autonomous work

Move from assigning individual tasks to giving a goal and sustaining progress.
Provide Objectives and Key Results; the agent interprets the direction, breaks
it into actions, plans daily work, delivers, and adjusts the plan using results.

### The working loop

**OKR → work plan → daily actions → agent execution → deliverables and outcomes
→ KR progress → the next plan.**

- **Model the goal.** Record the Objective, KR metric, baseline, target, cycle,
  owner, and source of outcome data.
- **Break it down.** Create milestones and executable tasks with dependencies,
  priorities, and completion criteria.
- **Act every day.** Select and dispatch work using the gap to the goal,
  existing progress, and available resources.
- **Keep delivering.** Attach artifacts, code changes, communications, and
  verification results to the corresponding task and KR.
- **Review and replan.** Identify blockers and ineffective actions, update the
  next day's plan, and produce a daily review.

### Milestones

- [ ] Personal and project OKR creation, viewing, and updates.
- [ ] Editable milestones, task dependencies, and execution plans generated from goals.
- [ ] Daily scheduling that selects actionable work and retains progress across days.
- [ ] Questions, blocker notifications, plan changes, and human takeover during execution.
- [ ] Tasks and deliverables linked to KRs, with progress based on explicit outcome sources.
- [ ] Daily reviews, cycle retrospectives, and the next action plan.

### The user-visible outcome

After setting a goal, you see concrete daily actions and deliverables. Open your
phone to see what moved forward, why those actions were selected, what needs
your decision, and the remaining gap to each KR. Task completion, artifacts, and
business metrics remain distinct, with evidence behind KR changes.

**Existing foundations:** projects and tasks, agent orchestration, persistent
sessions, scheduled jobs, reminders and daily briefs, notifications, and
traceable execution results. The next step ties scheduling and execution to
OKR goals, metrics, and cycles.

Design proposal (Chinese): [user stories](docs/design/20261030-okr每日行动/user-stories.html),
[product research and interaction](docs/design/20261030-okr每日行动/index.html), and
[technical design](docs/design/20261030-okr每日行动/technical-design.html). These are proposals,
not implemented capabilities.

## How the tracks fit together

| Part | Role |
|---|---|
| OKR | Supplies long-term direction and determines daily priorities |
| Personal digital twin | Receives information, communicates progress, and brings work back to real conversations |
| Agent execution | Uses tools and professional agents to deliver results you can inspect and take over |
| RSI | Improves the next attempt using execution outcomes and user feedback |

The intended result is a **personal digital twin that continuously improves,
communicates for you, and works toward your goals every day**. Roami's remote
console and Android app keep inspection, direction, and takeover in your hands.

## Related documents

- [Roami overview and screenshots](README.md)
- [Complete current feature list](docs/features.md)
- [SuperWork messaging foundation](https://github.com/blade-hq/super-work)
