package okr

import (
	"errors"
	"io/fs"
	"os"
	"strings"
	"unicode/utf8"
)

type projectMainDefinition struct {
	SchemaVersion    int      `json:"schemaVersion"`
	Role             string   `json:"role"`
	InstructionsFile string   `json:"instructionsFile,omitempty"`
	Skills           []string `json:"skills,omitempty"`
}

var builtinProjectSkills = []string{
	"skills/okr-planning/SKILL.md",
	"skills/metric-collection/SKILL.md",
	"skills/swarm-execution/SKILL.md",
}

func seedGuidance(root *os.Root, name, content string) error {
	f, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, fs.ErrExist) {
		return safeFile(root, name)
	}
	if err != nil {
		return err
	}
	_, err = f.WriteString(content)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func (s *Store) seedWorkflow(root *os.Root, projectID string) error {
	if err := seedGuidance(root, "AGENTS.md", projectDailyWorkflow); err != nil {
		return err
	}
	project, err := os.OpenRoot(s.projects()[projectID])
	if err != nil {
		return err
	}
	defer project.Close()
	return seedGuidance(project, "AGENTS.md", projectAgentEntry)
}

func seedProjectCapabilities(root *os.Root) error {
	files := map[string]string{
		"README.md":             projectBundleReadme,
		"agents/main.md":        projectMainInstructions,
		builtinProjectSkills[0]: planningSkill,
		builtinProjectSkills[1]: collectionSkill,
		builtinProjectSkills[2]: executionSkill,
	}
	for name, content := range files {
		if _, err := root.Lstat(name); errors.Is(err, fs.ErrNotExist) {
			if err := atomicFile(root, name, []byte(content)); err != nil {
				return err
			}
		} else if err != nil {
			return err
		} else if err := safeFile(root, name); err != nil {
			return err
		}
	}
	if _, err := root.Lstat("agents/main.json"); errors.Is(err, fs.ErrNotExist) {
		return writeJSON(root, "agents/main.json", projectMainDefinition{1, "main", "main.md", builtinProjectSkills})
	} else if err != nil {
		return err
	}
	return safeFile(root, "agents/main.json")
}

func projectSkills(root *os.Root, main projectMainDefinition) ([]ProjectSkill, error) {
	if main.SchemaVersion != 1 || main.Role != "main" || main.InstructionsFile != "" && main.InstructionsFile != "main.md" || len(main.Skills) > 16 {
		return nil, ErrInvalid
	}
	result := make([]ProjectSkill, 0, len(main.Skills))
	seen, total := map[string]bool{}, 0
	for _, name := range main.Skills {
		parts := strings.Split(name, "/")
		if len(parts) != 3 || parts[0] != "skills" || !identifier.MatchString(parts[1]) || parts[2] != "SKILL.md" || seen[name] {
			return nil, ErrInvalid
		}
		body, err := readFile(root, name, maxMemory)
		if err != nil {
			return nil, err
		}
		total += len(body)
		if len(body) == 0 || !utf8.Valid(body) || total > maxMemory {
			return nil, ErrInvalid
		}
		seen[name] = true
		result = append(result, ProjectSkill{parts[1], name, string(body), hashText(body)})
	}
	return result, nil
}

const projectBundleReadme = `# Project OKR workspace

This directory belongs to this project. It is created only for a saved OKR.

- okr.json: objective, long/short KRs, methods and confirmed metric definitions.
- dashboard.json: registered HTML/chart components, order and metric bindings.
- data/observations.jsonl: dated, versioned facts; a missing value is unknown.
- data/reviews.jsonl and evidence/: reviews and their original evidence snapshots.
- connectors/<metric-id>/: source definition and reviewable implementation references.
- agents/main.json and main.md: on-demand coordinator configuration and instructions.
- agents/swarm.json: the existing managed team's binding; its board/chat remain authoritative.
- skills/: project capabilities used by goal discussions and managed team context.
- memory/team.md and decisions.jsonl: durable knowledge, separate from proof of execution.
- state/current.json and confirmed-revisions/: confirmed version pointer and immutable snapshots.

Discuss the objective, KRs, methods, metrics and sources before saving changes. The same validated definitions drive the pages; editing a draft does not silently replace the confirmed version. Use revision-checked save/sync and actual source collection. Connector source references explain the built-in collector; editing them does not execute arbitrary code. A configured skill describes work, not proof that the work ran. Record actual task runs, media and external receipts separately.
`

const projectMainInstructions = `# Project coordinator

Use this project's confirmed OKR, dashboard, dated evidence, skills and team memory. Discover the current project_okr_context/project_okr_update capabilities; do not guess paths, credentials or project identity. Project context fixes the authorized project.

For a new goal, reason with the user about outcome KRs, shorter experiments, methods, metrics, units, dates and sources. The number and meaning of KRs/widgets follow the goal. Get confirmation before saving configuration or connecting an account. Missing observations remain unknown. Read the current revision before every change.

Use the skills listed in main.json as project guidance. Dispatch authorized work to the bound managed Swarm, using its shared board and group chat. Match each task to its KR, method, workspace, inputs and acceptance evidence. Read actual current-run deliverables before independent verification. Members cannot verify themselves. External actions require actual platform receipts and the user's decision boundary.

Use observed results to propose the next experiment. Keep memory concise and factual. A draft, a skill, an executor success or an idle session is not a completed publication or a configured daily schedule. Never change model routes, parameters, spending limits or accounting.
`

const planningSkill = `---
name: okr-planning
description: Discuss and revise this project's objective, KRs, methods and dashboard bindings.
---

Read the bound project's current context. Explain the outcome, proposed KRs, shorter experiments, methods and metric definitions before saving. Decide their count and composition from this goal. For each metric establish unit, date window, baseline availability and source identity. Get the user's confirmation on targets and sources. Then save through the registered project operation with the observed revision. Preserve existing methods and widgets unless explicitly changing them. Supported widgets are keyResults, metricTrend and nextAction; arbitrary HTML scripts are not an executable dashboard protocol. Report a save only after its real successful receipt.
`

const collectionSkill = `---
name: metric-collection
description: Collect real dated observations through this project's confirmed source bindings.
---

Read current metric definitions and connector.json. The github built-in collector reads public repository identity, stars and forks through the registered collect operation. It appends actual dated observations; it does not invent earlier history. Manual-source metrics require observed account, date, measurement window and evidence before record. Browser/phone access must use an authorized managed task, the current device or browser observation, and real receipts. Missing login or data is unknown, never zero. A local Go reference is documentation, not permission to run edited code. Re-read on revision conflicts. Keep same-day corrections as new versions.
`

const executionSkill = `---
name: swarm-execution
description: Execute, independently review and iterate using the bound managed Swarm.
---

Use the existing Swarm ID, shared board/chat and this project workspace. Declare KR/method, owner, inputs, concrete artifacts, dependencies and acceptance for every task. Serialize conflicting writers and device actions. Pause dispatch, stop execution and steer are distinct controls; use their actual receipts. Never bypass an unknown prior writer or relabel an old artifact as a current run.

After delivery, independently read the current run and source evidence. Main may use the scoped verification capability for supported artifact tasks, never member self-verification. External actions keep their real receipt and user decision gates. Publication preparation, upload, submission, review and public availability are separate states. Reconcile an unknown write on the same resource instead of replaying it. Reflect on dated results and propose the next measurable experiment; do not infer causation from activity counts alone.
`

const projectAgentEntry = `# Project agent instructions

Before OKR work, read .roami/okr/AGENTS.md, the confirmed .roami/okr/okr.json,
the bound team's current board/chat and .roami/okr/memory/team.md.
Follow the daily artifact and multi-agent collaboration contract there.
Keep this file's existing project rules when extending it.
`

const projectDailyWorkflow = `# Daily OKR work and multi-agent collaboration

## Shared authority

Use the confirmed okr.json and dashboard.json in this directory. The bound Swarm
in agents/swarm.json owns the shared board, group chat and current task state.
Main coordinates; members work on the same project directory, not private copies
of the goal. Read agents/main.md, the configured skills and memory/team.md.
Instructions and plans never prove execution, verification or publication.

## Daily artifacts

Use the project's local timezone (Asia/Shanghai unless explicitly configured).
Place new deliverables under project-relative YYYY/YYYYMM/YYYYMMDD/, for example
2026/202611/20261104/. The month segment must agree with the day; 202610/20261104
is invalid. Never move an old output into today and claim it was produced today.

Within the day use x-content/, bili-video/, data/, reflection/ or a short method
ID appropriate to this project. Each worker writes its own task/revision/run
subdirectory: <method>/<task-id>/r<revision>/<run-id>/. Preserve original filenames
and use new versions instead of overwriting another worker's output. A task that
crosses midnight keeps its run directory; the next day's index links to it.

Keep README.md and manifest.json at the day root. Main owns these two shared
indexes; workers report candidates in the group chat. Each manifest entry records
relative path, KR/method, owner, taskId, revision, runId, producedAt with timezone,
bytes, SHA256, upstream evidence and verification status. Data also records asOf
and source/account; collection time and metric date are different. A migrated
copy records its original path/date/hash and migratedAt; it is not a new run.
Daily directories and indexes are created when work actually happens, not as
empty promises for future days. Paths and indexes do not replace host artifacts.

For X retain copy, image, ALT text, exact account, reviewed version and receipt.
For video retain script, source recordings, voiceover, subtitles, cover, final
MP4 and decode/review evidence. Store publishing receipts beside the delivered
content: prepared, selected, uploaded, submitted, reviewing, public or blocked
are distinct states. A URL without a verified platform receipt proves no post.
Do not put credentials, cookies or tokens in deliverables or daily indexes.

## Roles and control

Main reads the confirmed KR/method, plans owners and dependencies, assigns bounded
work with acceptance criteria, resolves blockers and independently verifies the
current run's artifacts. Main controls pause/resume/stop/steer through the host;
members cannot accept their own work or edit host task state. A real resume
receipt supersedes an old temporary planning pause; external action approval
still applies to the exact content/account. Never infer publish permission from
a changed label or another member's assertion.

Content members create real files; the video member produces and checks actual
media. A data member collects dated facts from confirmed sources, never invented
zeros. A reflection member compares outcomes to the experiment, identifies
uncertainty and proposes the next change; Main/user decide and dispatch it.
One member owns a file, account or device action at a time. Serialize browser and
phone operations; unknown outcomes are reconciled on the same resource before
retry. Do not bypass a busy task, old pending tool or login/approval boundary.

Use the same group chat for handoffs, blockers, candidate artifacts and decisions.
Report task/revision/run and paths rather than only saying done. @leader addresses
Main; a member mention addresses its real task. To change an existing task, use
the task page or directed chat and preserve host revision checks. A plan-only
member has no executable session; Main must dispatch it first.

## Daily execution, reflection and memory

At the start of work read today's index, confirmed targets, team memory, recent
review and current board. Produce bounded artifacts, report them, and let Main
read actual current-run bytes and dependency evidence before acceptance. External
actions require their platform receipt and the user's decision boundary.

Record real metric observations through the revision-checked project operation;
do not hand-edit confirmed snapshots or replace observations.jsonl history. Keep
same-day corrections as new observations. At day end compare evidence, results
and unknowns; write reflection and the next experiment in the daily directory.
Main merges lasting facts into memory/team.md with its current hash and records
decisions through the supported operation. Memory is concise knowledge, not raw
logs or proof that a publication succeeded. The loop is execute, observe, reflect,
decide, then execute again. A daily plan is not an installed recurring scheduler.
`
