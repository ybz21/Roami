# RSI module architecture

`service.ImprovementStatus` is the public composition root used by the runtime and HTTP API.
It constructs repositories and lifecycle coordinators. Module dependencies point down the table;
workflow code does not open the RSI ledger or execute SQL, and presentation code does not mutate
run or research state. `tests/test_improvement_architecture.py` enforces these boundaries.

| Layer | Responsibility | Main modules |
| --- | --- | --- |
| `entrypoints/` | Command parsing and process entry | `cli`, `import_diagnostic` |
| `service.py` | Runtime composition and orchestration before queries | `ImprovementStatus` |
| `presentation/` | Owner-scoped API projections | `status`, `run_overview`, `run_results` |
| `workflows/` | Case execution, observation, verification and publication | `run_lifecycle`, `research_worker`, `source_revision`, `github_publication` |
| `persistence/` | Ledger schema, transactions, ownership checks and read models | `run_repository`, `research_repository`, `research_projection`, `publication_outbox` |
| `evaluation/` | Frozen suites, fixtures, grading and sandbox execution | `case_catalog`, `authored_fixtures`, `grading`, `benchmarks/`, `execution/` |
| `integrations/` | Files, processes, GitHub, Codex, models and accounting adapters | `artifact_files`, `source_workspace`, `github_client`, `codex_cli`, `model_gateway` |
| `domain/` | Pure comparison, acceptance, scoring and configuration rules | `comparison`, `source_acceptance`, `scoring`, `contracts` |

`domain/` has no filesystem, process, network or database access. Evaluation may depend on domain
rules and adapters. Persistence may use evaluation contracts; neither imports workflow or views.
The sandbox execution adapters read the sandbox's own runtime database as evidence. This is
separate from the RSI ledger, whose SQL is confined to `persistence/`.

## Repository ownership

`RunRepository` owns run identities, stage records, frozen context and query selection.
`RunArtifacts` stores and indexes artifacts; `RunCosts` accounts for cost snapshots.
`RunLifecycle` coordinates requests and freeze/capture operations. `ResearchProjection` refreshes
the research read model in one repository transaction rather than exposing SQL to that workflow.

`ResearchRepository` owns the durable action queue and its lease/owner checks. Its configuration,
cost accounting and reports are composed from `ResearchConfiguration`, `ResearchCosts` and
`ResearchReports`; they reuse the repository transaction when an operation must be atomic.
Publication uses an outbox and verifies the action lease through a repository method before an
external write. An executor's success claim does not bypass verification or close an issue.

The runtime and RSI use `providers.factory.configured_provider`; lower-level modules no longer
import application bootstrap merely to construct a provider. RSI review and source revision use
`workflows.model_calls` for durable, metered model responses.

## Cases and frozen identities

The canonical catalog is the repository's `cases/` directory; a wheel includes it under
`roami_agent/improvement/cases/`. Each case has `CASE.md`, `case.json` and `materials.json`.
The material manifest records generated or imported inputs, tools and acceptance provenance.
QUANT-02 also ships its actual public input, standard-library generator and tool requirements.
Only declared, bounded files inside the case directory can become catalog resources. Resource
SHA256 values enter the new authored suite's origin; runtime receipts and private judge answers
remain separate. See [the Case format](../../../../cases/README.md).

This refactor does not rewrite ledger schemas or historical run artifacts. New authored suites
use `roami-authored-40-v14`; existing frozen v12/v13 suites remain intact. Grader fingerprints include
all extracted domain and evaluation Python sources so a rule change cannot silently reuse an
old grader identity. Existing public `python -m ...improvement.cli`, `container_agent` and
`import_diagnostic` entry points remain small shims; private imports use the actual new modules.

Shared daily accounting requires rebuilding `improvement.Dockerfile` after upgrading. The image
label `org.roami.rsi.shared-daily-policy=2` identifies support for forwarding the host policy into
the Native executor and deferring fee admission to the configured Go gateway. Missing token counts remain
unknown evaluation evidence; they do not introduce a second spending gate when the configured Go gateway
allows the request. Shared-mode preflight rejects older images before model execution, so an old
image cannot silently retain per-case token, request or missing-usage caps. Explicit legacy mode stays supported.
