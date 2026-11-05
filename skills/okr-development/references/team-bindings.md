# Bind durable roles without replacing members

A desired role, runtime member, work item, task, run and provider conversation
are different identities. Read the confirmed project and its bound Swarm before
changing a team. Use registered host operations; names and historical suffixes
never prove that two actors are the same.

## Discover and preserve bindings

`projectFiles.teamRoleBindings: true` advertises host support for explicit
`team.roles[].memberId`. Older hosts may omit it; do not probe live saves to
learn a schema. Preserve existing confirmed binding fields even when editing
another part of the goal. An initialization template contains no manufactured
member or provider IDs.

For a supported host, match each confirmed memberId to the exact member in the
same owner's project and Swarm, with the agreed executor. Display names can
differ from registered names. If a requested new role is genuinely missing,
register it through the existing team protocol and use its returned identity.
Do not register a replacement because a task failed, a label changed or the
member awaits user approval. An unbound role remains unbound until a real
member is selected.

The host applies a project revision CAS and checks live team membership. A
member may fill only one role. Omitted/null memberId preserves that role's
previous binding; an empty string explicitly clears it. Changing an executor
requires resolving its existing binding, not silently transferring history.
The mapping changes the current/history view; it never archives or completes
runtime tasks, closes a provider session, or proves that an instance is alive.

## Save a complete configuration

Prefer the registered `project_okr_update` function directly. Read current
`project_okr_context`, copy the supported configuration, and change only the
requested fields. A save payload contains revision, objective, startDate,
endDate, keyResults, metrics, swarm, autoCollect, initiatives, dashboard and team.
Keep existing optional values; omit response-only projectId, projectFiles,
observations, reviews and updatedAt. Do not send a revision-only trial save.

Pass the complete JSON object as function arguments. A JSON file on disk does
not pass its contents to a function automatically. Do not guess CLI options,
wrap managed commands in timeout or pipelines, inspect environment/process
context to reconstruct invocation tokens, or switch to another Main. If the
registered tool fails, read the actual project and report the error before
trying a different operation. Developer terminals can use the installed
revision-checked project CLI according to its help.

## Reconcile interruption and preserve evidence

Stopping a reply does not roll back completed tool writes. After interruption
or an unknown response, reread the confirmed revision, exact bindings and
current receipts before retrying. If the intended mapping is already present,
verify it instead of saving again with a new key or stale revision.

Reread the project after saving. Compare O/KRs, methods, widgets, sources,
observations and reviews; verify that all original member/work/task/revision/run
identities and host states remain. Keep older snapshots and outputs. Normal
bundle publication may update generated builtin reference files; archive their
old bytes and hashes first when historical evidence still references them.
Never replace custom Connector Skills with generated reference code.

Read the current team-memory SHA and append the lasting mapping/continuation
rule through the supported CAS operation. Preserve the old text and its
recoverable history. Pending publication or scheduling decisions remain pending.
A memory write is separate from saving definitions and from task acceptance.

Report the useful result briefly: connected roles, verified outcomes and the
next decision. Internal IDs, hashes, revisions and tool diagnostics belong in
the evidence or details unless the user needs them to recover a problem.
