# Architecture Inventory

## 1. Summary

Task 132의 product doctrine은 코드베이스의 큰 방향과 대체로 맞다. Cambrian은 이미 local runtime, AI bridge, benchmark/proof, improvement loop, template qualification/canary/governance 쪽 구현이 두껍고, Task 134~136으로 local pack installer, local catalog, static web hiring desk가 추가되었다.

전체 판정:

| Area | Status | Summary |
| --- | --- | --- |
| Web Control Plane | partial | static web hiring desk는 있고, remote registry/SaaS runtime은 아직 planned다. |
| Local Cambrian Runtime | implemented / partial | `do`, `continue`, `status`, `doctor`, `summary`, project mode, local catalog, local manifest install, local pack lifecycle(diff/update/uninstall), local pack trust/verify가 구현되어 있다. |
| AI Bridge | implemented | prepare/paste/ingest/review/handoff/resume/materialize/context-hints/checklists가 구현되어 있다. |
| Evidence & Proof | implemented / partial | metrics, benchmark, replay, compare, autonomy board, bottleneck, proof, canary evidence, challenge matrix가 있다. |
| Evolution & Governance | implemented / partial | improvement loop, interventions, keep/dismiss, qualification, canary, promotion/rollback, challenger queue가 있다. Template evolution CLI는 아직 drift가 있다. |

가장 큰 mismatch는 이제 “local installer 부재”가 아니라 “remote registry-backed install은 아직 planned”라는 점이다. 로컬에서는 `cambrian pack list/show/recommend`, `cambrian install pack <id>`, `cambrian install manifest <path>`, `cambrian install list`, `cambrian install show <pack>`, `cambrian install doctor`가 구현되었고, `web/` static hiring desk가 pack detail과 manifest link를 제공한다. 다만 remote pack registry와 SaaS backend는 없다.

Task 141 이후에는 static web catalog와 local runtime 사이에 pull layer가 추가되었다.
`cambrian registry add/list/sync`, `cambrian pack search`, `cambrian pack show --registry`, `cambrian install pack --registry`는 static catalog JSON/YAML 또는 local path registry를 읽고 기존 manifest installer로 설치한다.
SaaS backend, login, payment, cloud execution은 여전히 non-goal이다.
Registry state and cache live under `.cambrian/registries/`; this cache is derived state, not the source-of-truth catalog.

Task 142 이후에는 namespace / version pinning / dependency resolver V1이 추가되었다.
`cambrian install plan`, `cambrian install pack <namespace>/<pack>@<version> --confirm-deps`, `.cambrian/install/graphs/`, `pack_lock.yaml` resolved dependencies가 registry-scale install의 안전 경계를 만든다.
V1은 exact version, minimum version, latest available만 지원하고 complex npm-style semver와 dependency auto-update cascade는 non-goal이다.

## 2. Layer Inventory

### Web Control Plane

Status: partial

Implemented modules:

| Module | Status | Notes |
| --- | --- | --- |
| `web/` static catalog | implemented | landing, pack list, auth-bug-core detail, manifest asset을 제공한다. |
| `tools/generate_web_catalog.py` | implemented | `packs/catalog.yaml`에서 static web catalog를 생성한다. |
| web app/runtime | planned | server, account, registry backend는 없다. |
| install manifest contract | partial | local runtime이 local catalog와 manifest를 소비할 수 있지만, 웹 발급/registry는 아직 없다. |
| public/private registry | planned | architecture direction으로만 존재한다. |

Implemented commands:

| Command | Status | Notes |
| --- | --- | --- |
| `cambrian pack list` | implemented | local catalog 목록을 보여준다. |
| `cambrian pack show` | implemented | local catalog pack 상세와 fit을 보여준다. |
| `cambrian pack recommend` | implemented | current project signal 기반 local pack 추천을 보여준다. |
| `cambrian install pack` | implemented | local catalog alias로 manifest installer를 재사용한다. |
| `cambrian install manifest` | implemented | local manifest install path가 구현되어 있다. |
| `cambrian install list` | implemented | installed pack index를 읽는다. |
| `cambrian install show` | implemented | installed pack provenance 상세를 보여준다. |
| `cambrian install doctor` | implemented | installed pack 참조 무결성을 점검한다. |

Missing/planned pieces:

- Remote registry lookup for pack ids.
- Manifest signing/trust model.
- Published proof sharing workflow.

Risks:

- Product docs correctly say web is a control plane, but web itself is still not implemented.
- 웹 catalog가 없으므로 V1 onboarding은 local catalog와 local manifest 중심으로 설명해야 한다.

### Local Cambrian Runtime

Status: implemented / partial

Implemented modules:

| Module | Status | Notes |
| --- | --- | --- |
| `engine/project_mode.py` | implemented | project mode and `.cambrian/` setup foundation. |
| `engine/project_do.py` | implemented | work loop entry. |
| `engine/project_continue.py` | implemented | session continuation and validation path. |
| `engine/project_context.py` | implemented | context selection support. |
| `engine/project_clarifier.py` | implemented | clarify path. |
| `engine/project_summary.py` | implemented | summary surface. |
| `engine/project_notes.py` | implemented | local notes surface. |
| `engine/project_doctor.py` | implemented | local doctor checks. |
| `engine/project_win_lane.py` | implemented | strongest lane fit and status language. |
| `engine/project_pack_install.py` | implemented | local pack manifest load, plan, install, provenance, list/show/doctor. |
| `engine/project_pack_authoring.py` | implemented | local pack draft, validate, build, and publish-local flow. |

Implemented commands:

| Command | Status | Code Location | Notes |
| --- | --- | --- | --- |
| `cambrian do` | implemented | `engine/cli.py`, `engine/project_do.py` | Work loop entry. |
| `cambrian continue` | implemented | `engine/cli.py`, `engine/project_continue.py` | Continue/validate path. |
| `cambrian status` | implemented | `engine/cli.py` | Compact project/lane/bridge/template status. |
| `cambrian summary` | implemented | `engine/cli.py`, `engine/project_summary.py` | Project summary surface. |
| `cambrian doctor` | implemented | `engine/cli.py`, `engine/project_doctor.py` | Local runtime checks. |
| `cambrian harness show` | implemented | `engine/cli.py`, `engine/project_harness*.py` | Harness surface. |
| `cambrian lane show` | implemented | `engine/cli.py`, `engine/project_win_lane.py` | Lane summary surface. |
| `cambrian pack list` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Local catalog list. |
| `cambrian pack show` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Local catalog detail. |
| `cambrian pack recommend` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Local catalog recommendation. |
| `cambrian pack draft` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Create local pack draft from worker/team/template/lane refs. |
| `cambrian pack validate` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Validate pack draft or manifest. |
| `cambrian pack build` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Build installable `.cambrian-pack.yaml` manifest and SHA-256 report. |
| `cambrian pack release-check` | implemented | `engine/cli.py`, `engine/project_pack_release.py` | Compute maturity/proof summary before publish. |
| `cambrian pack publish-local` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Preview-first local catalog publish; mutation requires `--confirm`. |
| `cambrian pack web-sync` | implemented | `engine/cli.py`, `engine/project_pack_release.py`, `tools/generate_web_catalog.py` | Sync local catalog maturity/proof metadata to static web assets. |
| `cambrian registry add/list/sync` | implemented | `engine/cli.py`, `engine/project_pack_registry.py` | Register and sync static catalog JSON/YAML or local path registry sources. |
| `cambrian pack search` | implemented | `engine/cli.py`, `engine/project_pack_registry.py` | Search local catalog plus synced registry cache. |
| `cambrian pack show --registry` | implemented | `engine/cli.py`, `engine/project_pack_registry.py` | Show static registry pack metadata, maturity/proof status, manifest digest, and install command. |
| `cambrian install pack --registry` | implemented | `engine/cli.py`, `engine/project_pack_registry.py`, `engine/project_pack_install.py` | Fetch/cache registry manifest, verify digest, then reuse manifest installer. |
| `cambrian install plan` | implemented | `engine/cli.py`, `engine/project_pack_dependencies.py` | Resolve namespace/version/dependency graph before install. |
| `cambrian install pack --confirm-deps` | implemented | `engine/cli.py`, `engine/project_pack_dependencies.py`, `engine/project_pack_install.py` | Install dependency graph only after explicit confirmation. |
| `cambrian install pack` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py`, `engine/project_pack_install.py` | Local catalog alias for manifest installer. |
| `cambrian install manifest` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Local manifest-based safe pack install. |
| `cambrian install list` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed pack index. |
| `cambrian install show` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed pack detail. |
| `cambrian install doctor` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed artifact integrity checks. |

Missing/planned pieces:

- Remote registry-backed pack lookup.
- Pack update/uninstall.
- Manifest signing and trust policy.
- A central artifact schema/audit layer that mechanically enforces source-of-truth vs derived artifact boundaries.

Risks:

- Local install is now real, but still V1: fail-closed, no complex merge, no remote registry.
- Current runtime vs future default separation is implemented across many modules, but not yet centrally audited.

### AI Bridge

Status: implemented

Implemented modules:

| Module | Status | Notes |
| --- | --- | --- |
| `engine/project_bridge.py` | implemented | packets and replies. |
| `engine/project_bridge_handoff.py` | implemented | safe handoff routing. |
| `engine/project_bridge_resume.py` | implemented | resume path. |
| `engine/project_bridge_materialize.py` | implemented | materialized analysis/review/plan artifacts. |
| `engine/project_bridge_context.py` | implemented | context hints. |
| `engine/project_bridge_checklists.py` | implemented | checklists and checklist steps. |
| `engine/project_bridge_fastpath.py` | implemented | fastpath records. |

Implemented commands:

| Command | Status | Code Location | Notes |
| --- | --- | --- | --- |
| `cambrian bridge prepare` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Packet generation. |
| `cambrian bridge paste` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Paste path for replies. |
| `cambrian bridge ingest` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Structured reply ingest. |
| `cambrian bridge review` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Reply review. |
| `cambrian bridge handoff` | implemented | `engine/cli.py`, `engine/project_bridge_handoff.py` | Safe workflow handoff. |
| `cambrian bridge resume` | implemented | `engine/cli.py`, `engine/project_bridge_resume.py` | Resume linked work. |
| `cambrian bridge materialize` | implemented | `engine/cli.py`, `engine/project_bridge_materialize.py` | Non-patch artifact materialization. |
| `cambrian bridge context-hints` | implemented | `engine/cli.py`, `engine/project_bridge_context.py` | Context hint surface. |
| `cambrian bridge checklists` | implemented | `engine/cli.py`, `engine/project_bridge_checklists.py` | Checklist surface. |

Missing/planned pieces:

- No provider-native model integration is expected by doctrine, so absence is aligned.
- More end-to-end fixture coverage would make no-retype path confidence easier to audit.

Risks:

- Bridge is one of the most doctrine-aligned areas. Main risk is keeping docs/examples synchronized with exact command names and response contract fields.

### Evidence & Proof

Status: implemented / partial

Implemented modules:

| Module | Status | Notes |
| --- | --- | --- |
| `engine/project_metrics.py` | implemented | weekly metrics. |
| `engine/project_benchmarks.py` | implemented | benchmark case/workset/report foundation. |
| `engine/project_benchmark_compare.py` | implemented | baseline compare. |
| `engine/project_benchmark_replay.py` | implemented | case replay. |
| `engine/project_benchmark_workset_replay.py` | implemented | workset replay and autonomy board. |
| `engine/project_autonomy_bottlenecks.py` | implemented | bottleneck report. |
| `engine/project_benchmark_proof.py` | implemented | proof pack. |
| `engine/project_template_canary_ledger.py` | implemented | canary exposure ledger. |
| `engine/project_template_canary_outcomes.py` | implemented | selected outcome attribution. |
| `engine/project_template_canary_review.py` | implemented | canary freshness review. |
| `engine/project_template_challenge_matrix.py` | implemented | challenge replay matrix. |

Implemented commands:

| Command | Status | Code Location | Notes |
| --- | --- | --- | --- |
| `cambrian metrics week` | implemented | `engine/cli.py`, `engine/project_metrics.py` | Weekly metrics report. |
| `cambrian benchmark case-add` | implemented | `engine/cli.py`, `engine/project_benchmarks.py` | Benchmark case creation. |
| `cambrian benchmark report` | implemented | `engine/cli.py`, `engine/project_benchmarks.py` | Workset report. |
| `cambrian benchmark compare` | implemented | `engine/cli.py`, `engine/project_benchmark_compare.py` | Baseline compare. |
| `cambrian benchmark replay` | implemented | `engine/cli.py`, `engine/project_benchmark_replay.py` | Case replay. |
| `cambrian benchmark replay-workset` | implemented | `engine/cli.py`, `engine/project_benchmark_workset_replay.py` | Workset safe replay. |
| `cambrian benchmark autonomy-board` | implemented | `engine/cli.py`, `engine/project_benchmark_workset_replay.py` | Autonomy board. |
| `cambrian benchmark bottlenecks` | implemented | `engine/cli.py`, `engine/project_autonomy_bottlenecks.py` | Bottleneck report. |
| `cambrian benchmark proof` | implemented | `engine/cli.py`, `engine/project_benchmark_proof.py` | Proof pack. |
| `cambrian template canary-ledger` | implemented | `engine/cli.py`, `engine/project_template_canary_ledger.py` | Canary ledger summary. |
| `cambrian template canary-outcomes` | implemented | `engine/cli.py`, `engine/project_template_canary_outcomes.py` | Outcome attribution. |
| `cambrian template canary-review` | implemented | `engine/cli.py`, `engine/project_template_canary_review.py` | Freshness review. |
| `cambrian template challenge-matrix` | implemented | `engine/cli.py`, `engine/project_template_challenge_matrix.py` | Challenger replay matrix. |

Missing/planned pieces:

- Public/web proof display is planned only.
- Repo-level `.cambrian/` fixture is sparse; most artifact coverage is in modules/tests rather than a representative checked-in example tree.

Risks:

- Evidence layer is broad and mostly aligned, but proof quality depends on benchmark/workset coverage.
- Full test suite can still be affected by unrelated fixture/import issues, so targeted proof tests remain important.

### Evolution & Governance

Status: implemented / partial

Implemented modules:

| Module | Status | Notes |
| --- | --- | --- |
| `engine/project_improvement_loop.py` | implemented | improvement cycles and evaluation. |
| `engine/project_improvement_interventions.py` | implemented | intervention packs and active overlay. |
| `engine/project_improvement_decisions.py` | implemented | keep/dismiss and persistent overlay. |
| `engine/project_template_qualification.py` | implemented | qualification reports and staging hooks. |
| `engine/project_template_qualification_decisions.py` | implemented | qualification accept/dismiss. |
| `engine/project_template_qualification_rollback.py` | implemented | qualification adoption rollback. |
| `engine/project_template_canary.py` | implemented | canary stage/playbook integration. |
| `engine/project_template_canary_report.py` | implemented | burn-in report. |
| `engine/project_template_canary_review.py` | implemented | freshness gate. |
| `engine/project_template_challenge_matrix.py` | implemented | evidence-backed challenger ranking. |
| `engine/project_template_library*.py` | implemented / partial | library decisions and policy. |

Implemented commands:

| Command | Status | Code Location | Notes |
| --- | --- | --- | --- |
| `cambrian improve next` | implemented | `engine/cli.py`, `engine/project_improvement_loop.py` | Select next improvement cycle. |
| `cambrian improve pack` | implemented | `engine/cli.py`, `engine/project_improvement_interventions.py` | Create intervention pack. |
| `cambrian improve apply` | implemented | `engine/cli.py`, `engine/project_improvement_interventions.py` | Apply reversible overlay. |
| `cambrian improve evaluate` | implemented | `engine/cli.py`, `engine/project_improvement_loop.py` | Evaluate cycle. |
| `cambrian improve keep` | implemented | `engine/cli.py`, `engine/project_improvement_decisions.py` | Persist good intervention. |
| `cambrian improve dismiss` | implemented | `engine/cli.py`, `engine/project_improvement_decisions.py` | Dismiss intervention. |
| `cambrian template qualify` | implemented | `engine/cli.py`, `engine/project_template_qualification.py` | Candidate vs reference replay compare. |
| `cambrian template qualify-stage` | implemented | `engine/cli.py`, `engine/project_template_canary.py` | Canary stage. |
| `cambrian template canary-report` | implemented | `engine/cli.py`, `engine/project_template_canary_report.py` | Burn-in report. |
| `cambrian template canary-promote` | implemented | `engine/cli.py`, `engine/project_template_canary.py` | Promotion with gates. |
| `cambrian template qualify-revert` | implemented | `engine/cli.py`, `engine/project_template_qualification_rollback.py` | Rollback qualification adoption. |
| `cambrian template challengers` | implemented | `engine/cli.py` | Challenger queue summary. |
| `cambrian template challenge-board` | implemented | `engine/cli.py` | Board summary. |
| `cambrian template challenge-matrix` | implemented | `engine/cli.py`, `engine/project_template_challenge_matrix.py` | Evidence-backed ranking. |

Missing/planned pieces:

- `cambrian template evolve` and `cambrian template fork` are referenced by docs and some next-action strings, but are not present in current `template --help`.
- The top-level `cambrian evolve` exists, but it is skill evolution, not template evolution.

Risks:

- Template evolution is a doctrine-critical bridge from persistent overlay to reusable defaults, but the exact CLI surface is drifted.
- Qualification code can suggest `cambrian template evolve <candidate>`, which is currently not a valid template command.

## 3. Command Inventory

| Command | Status | Code Location | Notes |
| --- | --- | --- | --- |
| `cambrian pack list` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Local catalog list. |
| `cambrian pack show` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Local catalog detail and fit summary. |
| `cambrian pack recommend` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py` | Current-project local pack recommendation. |
| `cambrian pack draft` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Create local pack draft. |
| `cambrian pack validate` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Validate draft or installable manifest. |
| `cambrian pack build` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Build installable manifest and build report. |
| `cambrian pack release-check` | implemented | `engine/cli.py`, `engine/project_pack_release.py` | Release gate for schema, integrity, compatibility, proof, and maturity. |
| `cambrian pack publish-local` | implemented | `engine/cli.py`, `engine/project_pack_authoring.py` | Publish manifest to `packs/catalog.yaml` with `--confirm`. |
| `cambrian pack web-sync` | implemented | `engine/cli.py`, `engine/project_pack_release.py`, `tools/generate_web_catalog.py` | Regenerate proof-aware static web catalog assets. |
| `cambrian install pack` | implemented | `engine/cli.py`, `engine/project_pack_catalog.py`, `engine/project_pack_install.py` | Local catalog alias for manifest installer. |
| `cambrian install manifest` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Local manifest install with dry-run/json. |
| `cambrian install list` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed pack inventory. |
| `cambrian install show` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed pack detail. |
| `cambrian install doctor` | implemented | `engine/cli.py`, `engine/project_pack_install.py` | Installed pack integrity checks. |
| `cambrian pack verify` | implemented | `engine/cli.py`, `engine/project_pack_trust.py` | Catalog pack or manifest SHA-256 verification. |
| `cambrian install verify` | implemented | `engine/cli.py`, `engine/project_pack_trust.py` | Installed pack lockfile, digest, and artifact ref verification. |
| `cambrian install diff` | implemented | `engine/cli.py`, `engine/project_pack_lifecycle.py` | Installed vs incoming manifest/catalog diff. |
| `cambrian install update` | implemented | `engine/cli.py`, `engine/project_pack_lifecycle.py` | Preview-first update; mutation requires `--confirm`. |
| `cambrian uninstall pack` | implemented | `engine/cli.py`, `engine/project_pack_lifecycle.py` | Preview-first uninstall; mutation requires `--confirm`. |
| `cambrian bridge prepare` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Generates bridge packet. |
| `cambrian bridge paste` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Paste path for replies. |
| `cambrian bridge ingest` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Ingest structured reply. |
| `cambrian bridge review` | implemented | `engine/cli.py`, `engine/project_bridge.py` | Review reply usability. |
| `cambrian bridge handoff` | implemented | `engine/cli.py`, `engine/project_bridge_handoff.py` | Safe handoff. |
| `cambrian bridge resume` | implemented | `engine/cli.py`, `engine/project_bridge_resume.py` | Resume handoff/session. |
| `cambrian bridge materialize` | implemented | `engine/cli.py`, `engine/project_bridge_materialize.py` | Materialize analysis/review/plan. |
| `cambrian bridge context-hints` | implemented | `engine/cli.py`, `engine/project_bridge_context.py` | List context hints. |
| `cambrian bridge checklists` | implemented | `engine/cli.py`, `engine/project_bridge_checklists.py` | List checklists. |
| `cambrian metrics week` | implemented | `engine/cli.py`, `engine/project_metrics.py` | Weekly report. |
| `cambrian benchmark case-add` | implemented | `engine/cli.py`, `engine/project_benchmarks.py` | Add benchmark case. |
| `cambrian benchmark report` | implemented | `engine/cli.py`, `engine/project_benchmarks.py` | Workset report. |
| `cambrian benchmark compare` | implemented | `engine/cli.py`, `engine/project_benchmark_compare.py` | Baseline compare. |
| `cambrian benchmark replay` | implemented | `engine/cli.py`, `engine/project_benchmark_replay.py` | Safe case replay. |
| `cambrian benchmark replay-workset` | implemented | `engine/cli.py`, `engine/project_benchmark_workset_replay.py` | Safe workset replay. |
| `cambrian benchmark autonomy-board` | implemented | `engine/cli.py`, `engine/project_benchmark_workset_replay.py` | Autonomy board. |
| `cambrian benchmark proof` | implemented | `engine/cli.py`, `engine/project_benchmark_proof.py` | Proof pack. |
| `cambrian benchmark bottlenecks` | implemented | `engine/cli.py`, `engine/project_autonomy_bottlenecks.py` | Bottleneck report. |
| `cambrian improve next` | implemented | `engine/cli.py`, `engine/project_improvement_loop.py` | Select next bottleneck/cycle. |
| `cambrian improve pack` | implemented | `engine/cli.py`, `engine/project_improvement_interventions.py` | Create intervention pack. |
| `cambrian improve apply` | implemented | `engine/cli.py`, `engine/project_improvement_interventions.py` | Apply overlay, not source patch. |
| `cambrian improve evaluate` | implemented | `engine/cli.py`, `engine/project_improvement_loop.py` | Evaluate improvement. |
| `cambrian improve keep` | implemented | `engine/cli.py`, `engine/project_improvement_decisions.py` | Keep persistent learning. |
| `cambrian improve dismiss` | implemented | `engine/cli.py`, `engine/project_improvement_decisions.py` | Dismiss intervention. |
| `cambrian template save` | implemented | `engine/cli.py`, `engine/project_templates.py` | Save template. |
| `cambrian template recommend` | implemented | `engine/cli.py`, `engine/project_template_recommend.py` | Recommend template. |
| `cambrian template diff` | implemented | `engine/cli.py`, `engine/project_template_diff.py` | Preview differences. |
| `cambrian template review` | implemented | `engine/cli.py`, `engine/project_templates.py` | Review template. |
| `cambrian template apply` | implemented | `engine/cli.py`, `engine/project_template_apply_guardrails.py` | Explicit apply path. |
| `cambrian template fork` | planned_in_docs_only | none | Referenced by doctrine, absent from `template --help`. |
| `cambrian template evolve` | planned_in_docs_only / drift | none | Referenced by docs and qualification next action; absent from `template --help`. |
| `cambrian template qualify` | implemented | `engine/cli.py`, `engine/project_template_qualification.py` | Qualification compare. |
| `cambrian template qualify-stage` | implemented | `engine/cli.py`, `engine/project_template_canary.py` | Canary stage. |
| `cambrian template canary-report` | implemented | `engine/cli.py`, `engine/project_template_canary_report.py` | Burn-in report. |
| `cambrian template canary-ledger` | implemented | `engine/cli.py`, `engine/project_template_canary_ledger.py` | Exposure ledger. |
| `cambrian template canary-outcomes` | implemented | `engine/cli.py`, `engine/project_template_canary_outcomes.py` | Outcome attribution. |
| `cambrian template canary-review` | implemented | `engine/cli.py`, `engine/project_template_canary_review.py` | Freshness gate. |
| `cambrian template challengers` | implemented | `engine/cli.py` | Challenger queue. |
| `cambrian template challenge-board` | implemented | `engine/cli.py` | Board summary. |
| `cambrian template challenge-matrix` | implemented | `engine/cli.py`, `engine/project_template_challenge_matrix.py` | Replay matrix. |

Command inventory summary for the audited command set:

| Status | Count | Notes |
| --- | ---: | --- |
| implemented | 59 | Bridge, benchmark, metrics, improve, local catalog/install/lifecycle/trust/authoring/release, and most template governance commands. |
| partial | 0 | Partiality is mostly at layer/flow level, not command parser level. |
| planned_in_docs_only | 2 | Template fork/evolve. |
| planned | 1 | Remote/web registry lookup. |
| drift | 1 | `template evolve` is referenced by next-action text but absent as a template command. |

## 4. Artifact Inventory

| Artifact Area | Status | Source-of-truth or Derived | Notes |
| --- | --- | --- | --- |
| `.cambrian/install/` | implemented | source-of-truth plus copied source manifest and lifecycle/trust evidence | Installed pack provenance, copied manifests, `pack_lock.yaml`, verification reports, install plans, diff reports, update records, uninstall plans, and uninstall records. |
| `.cambrian/packs/` | implemented | authoring provenance / derived build records | Pack drafts are editable local authoring records; build/publish records are provenance artifacts. |
| `.cambrian/packs/releases/` | implemented | derived release evidence | Release gate reports with maturity and proof summary. |
| `.cambrian/packs/web_sync/` | implemented | derived sync record | Records static web catalog sync outputs. |
| `packs/generated/` | implemented | generated installable manifest output | Built `.cambrian-pack.yaml` manifests produced by `cambrian pack build`. |
| `packs/catalog.yaml` | implemented | local catalog source-of-truth | `publish-local --confirm` registers built manifests with digest and local trust metadata. |
| `.cambrian/templates/` | implemented | mixed | Template definitions/decisions are source-of-truth; reports, ledgers, outcomes, reviews, matrices are derived. |
| `.cambrian/lane/` | implemented / partial | source-of-truth plus derived profile | Lane playbook is future default source-of-truth; lane profile is derived. Install registers lane candidates without switching current defaults. |
| `.cambrian/bridge/` | implemented | current runtime / derived | Packets, replies, handoffs, materialized artifacts, hints, checklists, fastpath records. |
| `.cambrian/benchmarks/` | implemented | derived proof state plus workset definitions | Cases/worksets can act as configured benchmark assets; reports/compares/replays/proof are derived. |
| `.cambrian/metrics/` | implemented | derived | Weekly metrics and latest metrics reports. |
| `.cambrian/improvement/` | implemented | mixed | Decisions and persistent overlay are source-of-truth; cycles/interventions/evaluations are evidence artifacts. |
| `.cambrian/agents/` | implemented | mixed | Registry/teams/decisions are source-of-truth; trials/boards are derived. |
| `.cambrian/harness/` | implemented | mixed | Decisions are source-of-truth; overlays/suggestions/profile can be derived. |
| `.cambrian/sessions/` | implemented | current runtime | Checked-in fixture includes one session file. |
| `.cambrian/requests/` | implemented | current runtime | Used by work loop, but no rich checked-in fixture tree was found. |
| `.cambrian/patch_intents/` | implemented | current runtime | Bridge and work loop can create patch intent artifacts. |
| `.cambrian/proposals/` | partial / drift | current runtime | Runtime state model names this area, while older patch/proposal paths may still use `.cambrian/patches/`. 확인 필요 before schema cleanup. |

Repository fixture note:

- The checked-in `.cambrian/` directory is sparse and currently contains a session fixture only.
- Most documented artifact areas are validated by code paths and tests, not by a representative committed `.cambrian/` example tree.

## 5. Doctrine Consistency

Aligned points:

- Product positioning is now documented as `AI Worker Installer`.
- Local catalog and manifest install give the AI Worker Installer doctrine a real runtime entry point.
- Internal identity is consistently `local-first`, `file-first`, and `evidence-based harness engineering runtime`.
- Strongest lane is consistently expressed as `Python + pytest + narrow auth/login bug fix` and `Python + pytest + auth/login narrow bug fix`.
- CLI top-level help explicitly emphasizes no automatic source mutation and explicit apply/adoption.
- Bridge, evidence, proof, improvement, canary, challenger governance, and install manifest code broadly match the 5-layer doctrine.
- `validated_proposal_rate` is documented as the north star and present in metrics/proof surfaces.

Drift points:

- Web control plane is correctly non-runtime and has a static hiring desk, but no remote registry/backend exists.
- Remote registry-backed pack lookup is still planned; docs should continue to distinguish local catalog from remote/web registry.
- `cambrian template evolve` and `cambrian template fork` are product-doctrine commands but are not implemented as template subcommands.
- `engine/project_template_qualification.py` can emit `cambrian template evolve <candidate>` as a next action, but that command is absent.
- Runtime state model names `.cambrian/proposals/`; current patch flow may still use older `.cambrian/patches/` conventions. 확인 필요 before renaming or migration.

## 6. Critical Architecture Gaps

1. Web control plane is static-only; there is no remote registry, manifest publishing backend, or account model.
2. Remote registry-backed pack lookup is missing; V1 supports local catalog and local manifest install.
3. Template evolution CLI is drifted: `template evolve` and `template fork` are referenced but not implemented.
4. Source-of-truth vs derived artifact boundaries are documented but not centrally audited by a schema or doctor.
5. Full repository test proof can still be blocked by unrelated fixture/import issues, so targeted tests remain the reliable gate.

## 7. Recommended Next Tasks

1. Harden local catalog and manifest install with more real pack fixtures and doctor checks before adding remote registry behavior.
2. Add remote registry lookup only after the static web/catalog contract proves stable.
3. Align template evolution terminology: either add `template fork` / `template evolve` or rewrite docs/next-actions to the actual command surface.
4. Add an artifact layout smoke test or doctor section that classifies `.cambrian/` paths as source-of-truth, current runtime, future default, or derived.
5. Add a representative `.cambrian/` fixture for the strongest lane showing install, templates, lane, bridge, benchmarks, metrics, improvement, and sessions.

## 8. Non-Goals / Do Not Build Yet

- Do not build cloud execution.
- Do not build browser-based code execution.
- Do not build provider-specific deep AI orchestration before bridge/local proof remains stable.
- Do not add multiple simultaneous active canaries.
- Do not auto apply, auto adopt, auto promote, or auto stage challengers.
- Do not implement a marketplace before local pack install and proof semantics stay stable.
- Do not migrate artifact schemas until the source-of-truth vs derived boundary is mechanically audited.

## 9. Final Verdict

Cambrian is ready for carefully scoped feature work in local install, bridge, evidence, and evolution areas because those layers are now materially implemented and doctrine-aligned.

Cambrian can now claim a local catalog, local manifest install, and static web hiring desk path, but not the full remote registry-backed install loop. The remaining product-front-door gap is remote discovery and registry trust, not local installation.

Recommended gate before broad product-facing web work:

```text
local catalog and manifest install remain green
install doctor catches broken references
static web catalog stays derived from packs/catalog.yaml before remote lookup
```

The current architecture is not an agent feature pile. It is a local evidence-based harness runtime with bridge/proof/evolution machinery, a local pack catalog plus installer, and a first static hiring desk. The next gap is the remote hiring desk: registry trust, manifest publishing, and proof-backed catalog distribution.
