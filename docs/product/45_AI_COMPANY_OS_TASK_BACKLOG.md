# AI Company OS Task Backlog

## 0. Fixed Direction

```text
Cambrian은 프로젝트 안에 검증 가능한 학습형 AI 회사를 설치하고,
그 회사가 24시간 멈추지 않고 프로젝트를 끝까지 이끌어
완성도 높은 제품을 만들게 하는 AI Company OS다.
```

이 문서는 `42_TEN_YEAR_ARCHITECTURE.md`와 `43_AGENT_MARKETPLACE_FUTURE.md`를 실제 구현 순서로 쪼갠 task source-of-truth다.

사용자가 `다음단계`라고 말하면 먼저 이 문서를 읽고, `status: pending` 중 가장 앞 task를 선택한다.

## 1. Next-Step Operating Rule

```yaml
next_step_rule:
  source_of_truth: docs/product/45_AI_COMPANY_OS_TASK_BACKLOG.md
  selection:
    - read this document first
    - select the first task with status: pending
    - do not skip ahead unless a blocker is recorded
  after_implementation:
    - update status
    - update evidence
    - record tests
    - keep next_task accurate
  idea_intake:
    - accept only if it supports AI Company OS direction
    - attach to an existing OS task when possible
    - do not create marketplace-first work before runtime/proof maturity
```

## 2. Direction Filter

모든 task는 아래 질문을 통과해야 한다.

- 프로젝트 이해를 높이는가?
- 24시간 운영 루프가 멈추지 않게 하는가?
- 외부 AI를 더 좋은 일꾼으로 배치하는가?
- 검증과 proof를 강화하는가?
- 실패를 다음 기본값 개선 후보로 바꾸는가?
- 나중에 마켓에서 거래 가능한 회사 구성물로 남는가?

통과하지 못하면 `non_goal` 또는 `future_after_proof`로 분류한다.

## 3. Task Backlog

### OS-01 Mission Control

```yaml
status: completed
why: 프로젝트를 끝까지 이끌려면 최종 목표, 현재 단계, 다음 행동, 완료 기준이 한 곳에 있어야 한다.
goal: auto report가 mission status, current phase, next task, blockers, completion score를 보여준다.
implementation:
  - define a project mission state model under local Cambrian runtime state
  - connect mission status to auto report and boardroom summary
  - expose next task selection based on this backlog and current runtime evidence
  - keep mission state local and evidence-backed
completion_criteria:
  - auto report includes mission_status
  - mission_status includes final_goal, current_phase, next_task, blockers, completion_score
  - first pending OS task can be selected deterministically
  - mission status does not claim completion without release/proof evidence
tests:
  - mission status appears in auto report
  - missing mission evidence produces caution, not fake confidence
  - first pending task resolves to OS-01 until completed
  - python -m pytest -q tests/test_auto_mission_control.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py creates .cambrian/auto/mission.yaml on auto init
  - engine/project_auto_mode.py adds mission_status to auto report and boardroom summary
  - tests/test_auto_mission_control.py verifies mission status, missing evidence caution, and boardroom propagation
next_task: OS-02
```

### OS-02 24H Auto Completion Loop

```yaml
status: completed
why: Cambrian의 핵심은 한 번 작업하는 것이 아니라 프로젝트가 끝날 때까지 계속 안전하게 전진하는 것이다.
goal: boardroom -> plan -> run -> ingest -> validate -> recover/release 루프가 중간 실패 후에도 다음 안전 행동으로 이어진다.
implementation:
  - define an auto completion loop state that can run bounded cycles repeatedly
  - add stop conditions for input_required, authority_required, release_gate_go, and hard safety block
  - preserve every cycle as evidence
  - keep source changes behind explicit authority
completion_criteria:
  - auto cycle can determine its next safe command after success, failure, or missing input
  - blocked cycles produce recovery or input request, not duplicate plans
  - done/release states stop instead of spinning
tests:
  - successful cycle advances to validation or release gate
  - failed cycle creates recovery plan
  - input_required pauses loop
  - release_gate_go stops current loop
  - python -m pytest -q tests/test_auto_cycle.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py writes .cambrian/auto/cycle_state.yaml with latest cycle status, stop condition, evidence refs, and next decision
  - engine/project_auto_mode.py records stopped cycles for input_required, release_gate_go, auto_done, authority_required, and hard_safety_block
  - tests/test_auto_cycle.py verifies waiting-for-result next decision, recovery cycle, input pause, release gate stop, authority stop, and blocked-cycle evidence
next_task: OS-03
```

### OS-03 Boardroom Operating Loop

```yaml
status: completed
why: 24시간 운영은 실행만으로 되지 않고, 방향/위험/검증/릴리즈 판단을 반복하는 회의 구조가 필요하다.
goal: CEO/CTO/COO/PM/QA/Release 역할의 boardroom decision이 다음 plan에 실제 반영된다.
implementation:
  - make boardroom decisions role-specific and evidence-cited
  - map each handoff status to boardroom decisions and plan steps
  - record decision lineage from report to boardroom to plan
completion_criteria:
  - boardroom decisions cite report evidence
  - plan records source decision refs
  - stale boardroom decisions are blocked
tests:
  - boardroom decision changes when report handoff changes
  - stale boardroom cannot create plan
  - role-specific decisions appear in plan evidence
  - python -m pytest -q tests/test_auto_boardroom.py
  - python -m pytest -q tests/test_auto_boardroom.py tests/test_auto_cycle.py tests/test_auto_next_iteration.py tests/test_auto_release_gate.py tests/test_auto_run_limits.py tests/test_auto_mission_control.py tests/test_ai_company_os_task_backlog.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py attaches report evidence refs and evidence citations to every boardroom role decision
  - engine/project_auto_mode.py records decision_lineage from report -> boardroom -> decision -> plan
  - engine/project_auto_mode.py attaches role-specific boardroom decisions and decision_evidence_refs to plan steps
  - tests/test_auto_boardroom.py verifies cited decisions, stale boardroom blocking, and role-specific plan evidence
next_task: OS-04
```

### OS-04 External AI Worker Bridge

```yaml
status: completed
why: Cambrian은 모델이 아니라 외부 AI를 프로젝트 회사의 노동력으로 배치하는 운영체계다.
goal: Claude, Codex, GPT, Cursor가 역할, 스킬, evidence, result contract를 받은 worker처럼 작동한다.
implementation:
  - include mission context, company roles, selected skills, evidence paths, risk boundaries, and result contract in job packets
  - keep provider-specific behavior behind adapters
  - require result intake instead of trusting raw AI replies
completion_criteria:
  - job packet includes mission, role, skill, evidence, validation, and contract sections
  - auto task directive and bridge packet agree on required result contract
  - provider identity is recorded without provider lock-in
tests:
  - bridge packet contains selected worker context
  - missing evidence is marked weak/manual_review_required
  - AI reply without required contract is rejected
  - python -m pytest -q tests/test_auto_worker_bridge.py
  - python -m pytest -q tests/test_auto_worker_bridge.py tests/test_auto_run_limits.py tests/test_job_start_runtime_contract.py::test_job_start_marks_weak_evidence_for_manual_review tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py adds provider-neutral auto external AI worker bridge context to linked auto task packets
  - engine/project_auto_mode.py aligns directive and packet auto_step_result_contract hashes
  - engine/project_auto_mode.py records mission, role, selected skills, evidence, risk, validation, and result contract sections in bridge packets
  - tests/test_auto_worker_bridge.py verifies worker packet context and invalid auto worker replies are rejected
next_task: OS-05
```

### OS-05 Validation / Proof Loop

```yaml
status: completed
why: 완성도 높은 제품은 성공 주장보다 검증 증거로 판단해야 한다.
goal: proof 없는 성공은 release로 가지 않고, validation command와 evidence와 release gate가 판단한다.
implementation:
  - connect mission completion to validation evidence and release gate verdict
  - separate preflight, runtime evidence, proof, and release claims
  - surface proof gaps in auto report
completion_criteria:
  - release path requires validation evidence
  - proof gaps block GO or produce CONDITIONAL/NO-GO
  - success rate is not shown without runtime evidence
tests:
  - no proof produces no fake success claim
  - release gate blocks missing validation evidence
  - proof evidence appears in report
  - python -m pytest -q tests/test_auto_release_gate.py
  - python -m pytest -q tests/test_auto_release_gate.py tests/test_auto_mission_control.py tests/test_auto_boardroom.py tests/test_auto_run_limits.py tests/test_ai_company_os_task_backlog.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py adds proof_summary with preflight, runtime evidence, proof evidence, release claim, and proof gaps
  - engine/project_auto_mode.py blocks success-rate claims unless runtime proof is ready
  - engine/project_auto_mode.py makes release gate GO depend on proof_ready and runtime_validation_evidence
  - tests/test_auto_release_gate.py verifies no fake success claim, missing-proof blocking, and proof evidence in report
next_task: OS-06
```

### OS-06 Recovery Loop

```yaml
status: completed
why: 24시간 운영은 실패를 만나도 멈추지 않고 안전한 보정 작업으로 전환해야 한다.
goal: rejection -> correction -> resolved -> next guidance 폐루프가 유지된다.
implementation:
  - keep invalid result rejection records
  - generate correction directives and corrected result templates
  - mark rejection resolved when corrected result is ingested
  - carry resolved mistakes into next guidance without auto-promoting memory
completion_criteria:
  - invalid result creates rejection and correction packet
  - corrected result resolves previous rejection
  - next task guidance includes prior contract failure warning
tests:
  - rejection/correction/resolved flow is preserved
  - resolved rejection no longer blocks next report
  - prior contract error appears in next directive
evidence:
  - engine/project_auto_mode.py result rejection and correction flow
  - engine/project_auto_mode.py records recovery_loop summary with rejection -> correction -> resolved -> next_guidance
  - engine/project_auto_mode.py carries resolved contract failures as candidate warnings without auto-promoting memory
  - tests/test_auto_run_limits.py invalid result correction coverage
  - python -m pytest -q tests/test_auto_run_limits.py::test_auto_step_ingest_rejects_invalid_result_contract
  - python -m pytest -q tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py
  - python -m pytest -q tests/test_auto_release_gate.py tests/test_auto_mission_control.py
  - python -m py_compile engine/project_auto_mode.py
next_task: OS-07
```

### OS-07 Skill Knowledge Ledger

```yaml
status: completed
why: 쓰면 쓸수록 좋아지려면 스킬별 성공/실패/교훈이 자동 후보로 쌓여야 한다.
goal: 스킬별 knowledge candidate가 생성되고, 승인 전에는 candidate로만 job guidance에 사용된다.
implementation:
  - create a skill knowledge ledger for candidate and approved knowledge
  - extract candidates from success, failure, rejection, correction, and resolved evidence
  - attach relevant candidate knowledge to selected skills
  - keep auto_promote false by default
completion_criteria:
  - rejection/resolved flow can create skill knowledge candidate
  - candidate knowledge is shown separately from approved knowledge
  - selected skill guidance includes relevant candidate warnings
tests:
  - evidence-backed candidate is created
  - evidence-less candidate is rejected
  - candidate appears in task directive but not as approved memory
  - python -m pytest -q tests/test_auto_run_limits.py::test_skill_knowledge_candidate_requires_evidence tests/test_auto_run_limits.py::test_auto_step_ingest_rejects_invalid_result_contract
  - python -m pytest -q tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py tests/test_skill_generation.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py writes .cambrian/skills/knowledge_ledger.yaml with candidate and approved knowledge separated
  - engine/project_auto_mode.py creates evidence-backed skill knowledge candidates from successful and blocked step results
  - engine/project_auto_mode.py creates evidence-backed skill knowledge candidates from rejection and resolved flows
  - engine/project_auto_mode.py attaches candidate skill warnings to auto task directives without promoting them as approved memory
  - tests/test_auto_run_limits.py verifies evidence-backed candidates, evidence-less rejection, and candidate-only directive guidance
next_task: OS-08
```

### OS-08 Worker Performance Ledger

```yaml
status: completed
why: 어떤 직원/스킬 조합이 어떤 업무에서 강한지 알아야 회사가 점점 좋아진다.
goal: agent/skill 조합의 검증 통과율, 재시도율, rejection율, blocker율이 기록되고 dispatch에 caution으로 반영된다.
implementation:
  - record worker performance per job result
  - aggregate only after minimum evidence threshold
  - expose low-data caution
  - use performance hints in dispatch without hard-locking choices
completion_criteria:
  - job completion updates worker performance ledger
  - dispatch sees performance hints
  - low sample size prevents overconfidence
tests:
  - successful job improves worker signal
  - repeated rejection lowers confidence
  - low data remains caution
  - python -m pytest -q tests/test_auto_run_limits.py::test_worker_performance_repeated_rejection_stays_low_data_and_penalized tests/test_auto_run_limits.py::test_auto_step_ingest_rejects_invalid_result_contract
  - python -m pytest -q tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py tests/test_skill_generation.py tests/test_auto_worker_bridge.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py writes .cambrian/workers/performance_ledger.yaml with per-event and aggregate worker performance records
  - engine/project_auto_mode.py records result, rejection, blocker, and retry-resolved worker performance events
  - engine/project_auto_mode.py exposes low-data worker performance caution in auto reports, job requests, worker packets, and task directives
  - tests/test_auto_run_limits.py verifies repeated rejection penalty, low-data caution, and directive guidance
next_task: OS-09
```

### OS-09 Relearning / Promotion Gate

```yaml
status: completed
why: 잘못된 지식과 잘못된 회사 구조가 자동 승격되면 쓰면 쓸수록 나빠진다.
goal: 잘못된 하네스, 직원, 스킬, 지식은 promotion이 아니라 review/rebuild 후보로 분리된다.
implementation:
  - route conflicting or failed knowledge to relearning review
  - require user approval or repeated verified evidence before promotion
  - support suppress/archive for bad candidates
completion_criteria:
  - promotion packet separates decision_history, lessons, mistakes, skill knowledge
  - rejected knowledge is not injected into future jobs
  - rebuild candidates are visible without auto-apply
tests:
  - unapproved candidate is not promoted
  - suppressed candidate is not injected
  - repeated verified candidate becomes promotion-ready, not auto-promoted
  - python -m pytest -q tests/test_auto_run_limits.py::test_repeated_verified_skill_candidate_is_promotion_ready_not_promoted tests/test_auto_run_limits.py::test_suppressed_skill_candidate_is_not_injected tests/test_auto_run_limits.py::test_worker_performance_repeated_rejection_stays_low_data_and_penalized tests/test_auto_run_limits.py::test_auto_step_ingest_rejects_invalid_result_contract
  - python -m pytest -q tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py tests/test_skill_generation.py tests/test_auto_worker_bridge.py tests/test_candidate_promotion.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py writes .cambrian/relearning/review.yaml with pending_user_review items for failed knowledge and worker performance
  - engine/project_auto_mode.py marks repeated verified skill knowledge as promotion_ready without auto-promoting it
  - engine/project_auto_mode.py supports suppressed/archived skill candidates and excludes them from future task guidance
  - tests/test_auto_run_limits.py verifies unapproved promotion gate, suppression exclusion, repeated verified readiness, and relearning review routing
next_task: OS-10
```

### OS-10 Company Snapshot / Marketplace-Ready Artifact

```yaml
status: completed
why: 마켓에서 팔 것은 프롬프트가 아니라 검증된 회사 구성물과 proof lineage다.
goal: 하네스, 직원, 스킬, 지식, proof, lineage를 private data 없이 export 가능한 company artifact로 만든다.
implementation:
  - define company snapshot format
  - separate project-private data from exportable proof summary
  - include known limits, provenance, checksum/signature-ready fields
  - keep marketplace as future layer until runtime/proof maturity
completion_criteria:
  - company snapshot can be generated locally
  - snapshot excludes raw private project data
  - snapshot includes proof summary and evolution lineage
tests:
  - snapshot validates schema
  - private data is excluded
  - proof and lineage refs are present
  - python -m pytest -q tests/test_company_snapshot.py
  - python -m pytest -q tests/test_company_snapshot.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_boardroom.py tests/test_ai_company_os_task_backlog.py tests/test_auto_worker_bridge.py tests/test_agent_platform.py tests/test_candidate_promotion.py
  - python -m py_compile engine/project_auto_mode.py
evidence:
  - engine/project_auto_mode.py generates .cambrian/company/snapshots/company-snapshot-*.yaml as a private company snapshot artifact
  - engine/project_auto_mode.py excludes raw private project data and includes only summaries, refs, sha256 fingerprints, proof summary, and lineage
  - engine/project_auto_mode.py marks marketplace sale/proof claims blocked until runtime proof maturity
  - tests/test_company_snapshot.py verifies schema validation, private data exclusion, proof lineage refs, and signature-ready hash
next_task: OS-11
```

### OS-11 First External Recipient Proof

```yaml
status: pending
why: 출시 제품은 만든 사람의 PC에서 되는 것이 아니라, 외부 사용자가 설명 없이 받아 설치하고 안전한 증거를 돌려줄 때 검증된다.
goal: 첫 외부 수령자가 하나의 release bundle을 받아 설치하고, AI Company gold path를 실행한 뒤 private-safe receipt만 돌려주는 폐루프를 증명한다.
implementation:
  - verify the latest install kit release bundle and external alpha bundle before any send
  - include the local MCP adapter path so Claude/Codex/Cursor can operate Cambrian without manual command copying
  - include `cambrian mcp verify --receipt dist/mcp_operability_receipt.json` as the installed MCP proof command
  - include `python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json` as the official local MCP release proof
  - include `docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md` as the official external AI-client connection guide
  - require the AI Company Golden Path to verify the freshly installed `cambrian-mcp` entry point with source-tree PYTHONPATH disabled
  - require release bundle smoke, dispatch-record, and recipient-checkpoint to expose the same `mcp_operability_verified` proof before any send
  - keep the first-recipient private fields outside git, docs, screenshots, and chat
  - require pre-send sequence to return READY_TO_MANUALLY_SEND_ONE before the human sends anything
  - provide an install-kit one-command pre-send sequence that prepares the private workspace, runs operator status, audits send-bypass surfaces, and rehearses the manual-send GO chain without sending
  - provide an install-kit one-command post-send sequence that refuses to record dispatch without `--sent-at-utc`, requires the preserved READY operator-status receipt plus the final manual-send GO receipt, and moves from sent-recorded to recipient checkpoint using private-safe returned receipts
  - validate returned install receipt and gold path receipt without raw private project data
  - validate returned `mcp_operability_receipt.json` as a standalone installed-wheel MCP proof and store only sha256 plus a safe summary
  - prepare a local-only first-recipient private workspace so the operator stores recipient/channel/ack text in private files instead of chat or CLI arguments
  - require the install-kit first-recipient operator status gate to report `READY_TO_MANUALLY_SEND_ONE` before any real manual send
  - make the install-kit operator status CLI print share-safe private file statuses and open gate ids without raw private values or absolute workspace paths
  - require install-kit dispatch-record `SENT_ONE_RECORDED` to reference and verify both a `READY_TO_MANUALLY_SEND_ONE` operator status receipt and a `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt when the first-recipient private path is used
  - update pilot decision only from receipt hashes and share-safe diagnostics
completion_criteria:
  - one recipient can install from the bundle without live chat explanation
  - returned install receipt validates and contains no secrets, raw code, private paths, or private user text
  - returned gold path receipt confirms agent creation, skill generation/search/fusion, harness engineering, evolution apply, and company snapshot
  - returned MCP operability receipt confirms initialize, tools/list, explicit cwd, safe project scan, install confirmation blocking, and no arbitrary shell
  - recipient checkpoint records SENT_ONE_RECORDED or RECIPIENT_GOLD_PATH_CONFIRMED using hashes only
  - pilot decision remains WAITING_FOR_EVIDENCE until real recipient evidence exists
tests:
  - python -m pytest --collect-only -q tests
  - python -m pytest -q tests/test_project_mcp_server.py
  - cambrian mcp verify --receipt dist/mcp_operability_receipt.json
  - python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
  - python scripts/check_external_alpha_first_recipient_operator_status.py
  - python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --workspace-dir <private-workspace-dir>
  - python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py --workspace-dir <private-workspace-dir>
  - python scripts/check_cambrian_install_kit_first_recipient_manual_send_go.py --workspace-dir <private-workspace-dir>
  - python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py --workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>
  - python scripts/check_cambrian_install_kit_dispatch_record.py --recipient-private-file <private-workspace-dir>/recipient-private.txt --operator-dispatch-note-private-file <private-workspace-dir>/operator-dispatch-note-private.md --operator-status-receipt <private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-ready-receipt.json --require-operator-status-receipt --manual-send-go-receipt <private-workspace-dir>/cambrian-install-kit-first-recipient-manual-send-go-receipt.json --require-manual-send-go-receipt --sent-at-utc <sent-at-utc>
  - python scripts/check_external_alpha_first_recipient_pre_send_sequence.py
  - python scripts/verify_external_alpha_release.py
  - python scripts/smoke_external_alpha_release_bundle.py
  - python scripts/smoke_ai_company_gold_path.py
  - python -m pytest -q tests/test_external_alpha_first_recipient_operator_status.py tests/test_external_alpha_first_recipient_pre_send_sequence.py tests/test_external_alpha_release_bundle.py tests/test_ai_company_os_task_backlog.py
evidence:
  - pre-send bundle smoke receipt now records `gold_path_mcp_operability_verified: true`
  - dispatch-record now records `release_bundle_smoke.mcp_operability_verified: true`
  - recipient-checkpoint waiting state now records dispatch MCP proof before private recipient evidence exists
  - recipient-checkpoint can now validate a returned standalone `mcp_operability_receipt.json` without storing raw MCP receipt paths
  - external alpha direct verifier now rejects self-consistent but stale source manifests by comparing current source allowlist bytes and sha256 against the release manifest; focused drift regression test passes
  - external alpha pytest runtime guard now skips only the repeated Windows batch rehearsal for non-release-bundle external-alpha tests; the previously timing-out broad group now passes `54 passed in 9m14s`, while `test_external_alpha_release_bundle.py` still verifies the real batch path
  - external alpha operator status now prints the exact current release ZIP sha256 in the FILL_PRIVATE_FIELDS next action and the `operator_note_confirms_release_hash` open gate, reducing copy/paste drift before the human-only send step
  - external alpha first-recipient preflight and operator status now require a real non-empty private channel value; `private send channel:` with no value, whitespace only, or another placeholder no longer satisfies `operator_note_names_channel`
  - external alpha first-recipient preflight and operator status now reject placeholder-like one-line recipient values such as `<recipient>`, `placeholder recipient`, `replace me`, `TODO`, or `TBD`; `recipient_private_ready` requires one real-looking recipient value
  - external alpha dispatch-record now rejects placeholder, blank, non-ISO, or non-UTC `sent_at_utc` values before `SENT_ONE_RECORDED` can be written; the first-recipient post-send sequence preserves a blocked share-safe receipt when `<sent-at-utc>` is supplied, so placeholder timestamps cannot become send evidence
  - external alpha timestamp regression passed `python -m pytest -q tests/test_external_alpha_dispatch_record.py -k "sent_at or private_sent_hashes" -> 3 passed`, `python -m pytest -q tests/test_external_alpha_first_recipient_post_send_sequence.py -k "sent_at or records_sent" -> 3 passed`, `python -m pytest -q tests/test_external_alpha_dispatch_record.py -> 13 passed`, `python -m pytest -q tests/test_external_alpha_recipient_checkpoint.py -k "records_ack_only_after_dispatch or builder_gold_path or cli" -> 9 passed`
  - external alpha first-recipient private runbook now keeps `<sent-at-utc>` in every post-send command and explicitly says not to use the runbook generation time as send evidence; the refreshed local workspace body sha256 is `3e67cde4e1fc6449de13b1546a0668ae4620ade020ffb67a71f3066ec0fabe5f`
  - external alpha private runbook sent-at regression passed `python -m pytest -q tests/test_external_alpha_first_recipient_send_workspace.py -> 6 passed`; operator status remains `FILL_PRIVATE_FIELDS` with body sha256 `7bf31463ad61efa8ee5dc87d23fca51736fb41ed70fd664a120de1f9f4e7e770`; operator send bypass audit remains `NO_OPERATOR_PREFLIGHT_BYPASS` with body sha256 `776a7d030256c96c846df00c4fe6a37f659c52748aecc936bb541a796a008285`
  - external alpha pilot learning chain now rejects `<sent-at-utc>` at recipient-checkpoint, pilot-review, pilot-evidence, pilot-decision, and pilot-iteration surfaces before any downstream artifact is written, preventing a runbook placeholder from becoming pilot evidence
  - external alpha pilot sent-at placeholder regression passed `python -m pytest -q tests/test_external_alpha_recipient_checkpoint.py tests/test_external_alpha_pilot_review.py tests/test_external_alpha_pilot_evidence.py tests/test_external_alpha_pilot_decision.py tests/test_external_alpha_pilot_iteration.py -k "placeholder_sent_at" -> 5 passed`; broader touched suites passed `23 passed`, `11 passed`, and `16 passed`
  - external alpha first-recipient private runbook now quotes command placeholders such as `"<sent-at-utc>"`, `"<external_alpha_builder_gold_path_share_receipt.json>"`, and `"<continue|fix_before_next|stop_and_redesign>"`, so Bash/PowerShell pass placeholders to Cambrian instead of interpreting `<`, `>`, or `|`; workspace receipt check `private_send_runbook_shell_safe_placeholders` is true with body sha256 `56a628cfedb5fc82007cddcb092f34202121033b0e64fc8da8d93f76bbd61df6`
  - external alpha private runbook shell-safe placeholder regression passed `python -m pytest -q tests/test_external_alpha_first_recipient_send_workspace.py -> 6 passed`; operator status remains `FILL_PRIVATE_FIELDS` with body sha256 `559fbbbb5131436bedcb951d2447d06574092b4ba14e3cead4ecf9d09b31c5f5`; bypass audit remains `NO_OPERATOR_PREFLIGHT_BYPASS`
  - external alpha first-recipient post-send CLI now rejects the shell-safe `<sent-at-utc>` placeholder without echoing it or promoting dispatch evidence; the dispatch record remains `READY_TO_SEND_ONE`, the post-send receipt remains `BLOCKED_AFTER_MANUAL_SEND`, and `sent_recorded=false`
  - external alpha post-send CLI placeholder regression passed `python -m pytest -q tests/test_external_alpha_first_recipient_post_send_sequence.py -k "placeholder_sent_at or cli_rejects_placeholder_sent_at_safely" -> 2 passed`, full post-send sequence suite passed `10 passed`, and focused dispatch-record guard passed `4 passed`
  - external alpha first-recipient post-send sequence now separates builder receipt `requested` from file `present`; a missing or still-placeholder `--builder-gold-path-share-receipt` writes a share-safe `BLOCKED_AFTER_MANUAL_SEND` receipt with `builder_receipt_exists_when_provided=false` instead of crashing or echoing placeholder/local/private values
  - external alpha missing builder receipt regression passed `python -m pytest -q tests/test_external_alpha_first_recipient_post_send_sequence.py -k "builder_receipt or missing_builder" -> 2 passed`, full post-send suite passed `12 passed`, and focused recipient-checkpoint guard passed `4 passed`
  - external alpha recipient-checkpoint now rejects missing or still-placeholder `--builder-gold-path-share-receipt` before JSON parsing or hashing, so common checkpoint/pilot surfaces cannot promote placeholder filenames into builder proof and do not echo placeholder/local/private values
  - external alpha recipient-checkpoint builder receipt placeholder regression passed `python -m pytest -q tests/test_external_alpha_recipient_checkpoint.py -k "builder_gold_path or builder_receipt or placeholder_builder or placeholder_sent_at" -> 5 passed`, full recipient-checkpoint suite passed `17 passed`, and focused pilot review/evidence propagation passed `5 passed`
  - external alpha release chain refreshed to ZIP sha256 `c9a7d88cf5919c351c8c33e3e64333bc0488142cc9d78cea6ed5a5cd4c9c3057`; verify, bundle smoke, operator dispatch packet, bypass audit, manual-send GO rehearsal, post-send rehearsal, pilot learning rehearsal, and final send-chain audit pass
  - first-recipient private workspace scaffold refreshed for the current ZIP; safe operator status is `FILL_PRIVATE_FIELDS` with body sha256 `8fbcb843b25bb0e06c457f3b877a505e579a99aa3fbaf03cafc558b88f8f0b13`
  - full pre-send sequence now blocks only on private fields: `recipient-private.txt=placeholder`, `operator-dispatch-note-private.md` missing private channel and current release hash
  - install-kit sender-side `--verify-release-bundle` now rejects self-consistent but stale release bundles by comparing ZIP payload hashes against current `dist` artifacts; focused stale-bundle regression test passes
  - install-kit operator status now prints the exact current release bundle sha256 in the FILL_PRIVATE_FIELDS next action, reducing copy/paste drift before the human-only send step
  - latest install-kit release bundle recipient-facing boundary now states that local install, MCP, and gold-path receipts are local validation evidence only, not public proof, sale-ready proof, marketplace proof, success-rate proof, or first-recipient confirmation
  - release bundle payload verification and the standalone bundle verifier now require the recipient-facing claim-boundary lines in `START_HERE_CAMBRIAN_INSTALL_KIT.md` and `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`
  - install-kit handoff and send-ready copy-paste messages now carry the same claim boundary, so the actual operator send text says local receipts are local validation evidence only and cannot imply public proof, sale readiness, marketplace readiness, success rate, or first-recipient confirmation
  - release bundle payload verification and the standalone bundle verifier now also require the handoff/send-ready copy-paste claim boundary, so the operator send text is checked as part of bundle proof
  - latest install-kit release bundle was regenerated and smoke-tested with release bundle sha256 `ba629ea6a4db04c43b7f7e1cc7128952b3a1ab3f59805cdc68af25314477bfd9`, smoke receipt body sha256 `541b68b6ab1ad6bf9c99e6b3d75cd9a3a7e46eafcb20a54a16aa27829c4207d9`, all gold path capabilities true, and MCP operability verified
  - install-kit internal ZIP remains `cambrian-install-kit-0.3.0.zip` with sha256 `7fe6142adfe64bf123ac4f5c1f907b5a772fd761924d328116e3c543032bdf51`
  - install-kit release receipt body sha256 is `c1d96d178e4fee354c7ef375281cdb4098e3a1a2fb284b5e261fbbbc30c79003`
  - install-kit handoff body sha256 is `480bca22b4f202176e931115e1c35bcc03364f2971e0bd014f8ca76805ba4cd1`; send-ready is `GO` with body sha256 `19a7a3ec0cb338b48aa4b3b04f4ae586cd181e992e4878561daee3d3b28f347a`
  - install-kit dispatch-record is `READY_TO_SEND_ONE` with body sha256 `79edf546163d8f132b7b94aec188441b66a49441d0db9ec34e12653cfb839c00`
  - install-kit dispatch-record now preserves a hashed copy-paste message policy proving the operator send text names install, gold path, MCP receipt, local-validation-only evidence, public-proof blocking, and real-human-send first-recipient confirmation
  - install-kit recipient-checkpoint remains `WAITING_FOR_RECIPIENT` with body sha256 `7073798b9ed0ec2689f9e0ee65aef370212d8bdc84dcf4de74804d9d3131c39f`; it records `blocking_summary.missing_evidence`, `required_returned_receipts`, `ack_file`, controlled `human_next_steps`, and a manual-send GO pre-send summary so the operator sees that `SENT_ONE_RECORDED dispatch record` is the first missing proof before returned recipient receipts can matter
  - install-kit recipient-checkpoint now preserves the dispatch copy-paste boundary as share-safe hashes and booleans, proving the final recipient proof surface inherited install, gold path, MCP receipt, local-validation-only evidence, public-proof blocking, and real-human-send first-recipient confirmation
  - install-kit first-recipient post-send sequence now mirrors a recorded recipient-checkpoint copy-paste boundary as share-safe hashes and booleans, so the last operator receipt can prove the proof surface inherited the same install/gold-path/MCP and claim-boundary instructions without storing raw send text
  - install-kit first-recipient private workspace is `INSTALL_KIT_FIRST_RECIPIENT_WORKSPACE_READY` with body sha256 `2336da412f886d3235bcf2eec165e51f53d670fe96b10afee8a31c39d38793c3`
  - install-kit first-recipient operator status receipt now defaults to `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `ed7bd2fed9bd82a2438eeede52666a698561aefde396f863f3621b6d2abaae42`, with safe open gate ids until real private fields are filled
  - install-kit first-recipient workspace receipt, private runbook, and operator status board now expose a controlled `human_private_field_checklist` that limits pre-send human edits to exactly two files: `recipient-private.txt` and `operator-dispatch-note-private.md`
  - install-kit first-recipient operator status now requires a real non-empty private channel value; a note containing `private channel:` with no value, whitespace only, or another placeholder remains blocked as `missing_private_channel`
  - install-kit first-recipient operator status now rejects placeholder-like one-line recipient values such as `<recipient>`, `placeholder recipient`, `replace me`, or `TODO`; `recipient_private_ready` requires exactly one real-looking private recipient value
  - install-kit and external alpha dispatch records now reject future `sent_at_utc` values before `SENT_ONE_RECORDED` can be written, so only real past-or-current manual-send timestamps can become send evidence
  - standard first-recipient private workspace dispatch now requires its pre-send proof by default: install-kit requires READY operator-status plus manual-send GO, and external alpha requires a ready preflight receipt before `SENT_ONE_RECORDED`
  - synthetic rehearsal dispatch records now carry `synthetic_rehearsal_boundary` and are rejected by the default dispatch verifier as standalone send evidence; install-kit and external-alpha post-send rehearsal verifiers must explicitly opt in to reading them
  - install-kit synthetic recipient checkpoints now carry the same rehearsal boundary and are rejected by the default checkpoint verifier as standalone recipient evidence; only the post-send rehearsal verifier can opt in
  - external alpha synthetic recipient checkpoints now carry the same rehearsal boundary and are rejected by the default checkpoint verifier as standalone recipient evidence; only the post-send rehearsal verifier can opt in
  - install-kit first-recipient operator status now writes a preserved `cambrian-install-kit-first-recipient-operator-status-ready-receipt.json` whenever verdict reaches `READY_TO_MANUALLY_SEND_ONE`, so post-send status reruns cannot overwrite the pre-send GO proof needed by dispatch and recipient checkpoint; regression coverage proves the ready receipt survives a later `WAITING_FOR_RECIPIENT_RECEIPTS` status rerun
  - install-kit first-recipient operator status `record_dispatch_after_manual_send` command now includes `--operator-status-receipt <private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-ready-receipt.json`, `--require-operator-status-receipt`, `--manual-send-go-receipt <private-workspace-dir>/cambrian-install-kit-first-recipient-manual-send-go-receipt.json`, and `--require-manual-send-go-receipt`, so the copyable operator command cannot bypass or lose the pre-send GO receipt or the final manual-send GO receipt
  - install-kit first-recipient pre-send sequence now writes `cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json` with current blocked body sha256 `7c6be17eb0f6812f0659a670622edcdb97ef4a5fd1a40d4308372b40c63960c4`; it preserves private workspace values, blocks on placeholder private fields, requires the preserved READY operator-status receipt, runs the operator send-bypass audit, and reruns the synthetic manual-send GO rehearsal without contacting a real recipient
  - install-kit first-recipient manual-send GO default remains `BLOCKED_BEFORE_MANUAL_SEND` with body sha256 `d255e3fd6ce71c048c9c1431b07386160cebe836819b6286f543bb11b206f7b8`
  - install-kit first-recipient post-send sequence now writes `cambrian-install-kit-first-recipient-post-send-sequence-receipt.json` with current blocked body sha256 `f89d0e681a33cd002e04c0e26c237f718293ae4a932d58823662ab49d8e33325`; it refuses to record dispatch without `--sent-at-utc`, records `SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT` only through the preserved READY operator-status receipt plus the final manual-send GO receipt, mirrors any recorded recipient-checkpoint copy-paste boundary as share-safe hashes and booleans, and can close `RECIPIENT_GOLD_PATH_CONFIRMED` from returned install/gold-path/MCP receipts plus one `CONFIRMED` acknowledgement without storing raw private values
  - install-kit recipient-checkpoint now rejects missing or still-placeholder returned install, gold-path, and MCP receipt paths before JSON parsing or hashing, so placeholder filenames cannot become recipient proof and local/private values are not echoed
  - install-kit first-recipient post-send sequence now separates returned receipt `requested` from file `present`; a requested-but-missing returned receipt writes a share-safe `BLOCKED_AFTER_MANUAL_SEND` receipt instead of crashing or claiming receipt presence
  - install-kit returned receipt placeholder regression passed `python -m pytest -q tests/test_cambrian_install_kit.py -k "recipient_checkpoint and (missing_returned_receipts or placeholder_returned_receipt or confirms_gold_path or accepts_windows_bom)" -> 6 passed` and post-send missing receipt regression passed `python -m pytest -q tests/test_cambrian_install_kit.py -k "post_send_sequence and (missing_returned_receipt or confirms_gold_path or placeholder_sent_at)" -> 3 passed`
  - install-kit first-recipient private runbook now uses `<real-sent-at-utc>` instead of an auto-generated timestamp in post-send and lower-level dispatch/checkpoint commands, so the operator must replace it with the real UTC manual-send timestamp; dispatch-record rejects placeholder or non-UTC `sent_at_utc` values before they can become send evidence
  - current install-kit first-recipient workspace body sha256 after timestamp placeholder hardening is `56c22f2841a4bdf2d51b465113da1e2cc5a7d882e658743f551e1f75ee7c4860`; operator status remains `FILL_PRIVATE_FIELDS` with body sha256 `4926f480e210b533f6832f1ab98ed023742d1d97386c1517b138acceb210b497`; placeholder post-send attempt remains `BLOCKED_AFTER_MANUAL_SEND` with body sha256 `67a3108cc5a0e6a0e999a6795729869db95ef3bc7d622febb4c6e0a120c1b909`
  - focused timestamp regression passed `python -m pytest -q tests/test_cambrian_install_kit.py -k "sent_at or first_recipient_workspace or post_send_sequence or dispatch_record_accepts_ready_operator_status" -> 10 passed`; install-kit/backlog regression passed `python -m pytest -q tests/test_cambrian_install_kit.py tests/test_ai_company_os_task_backlog.py -> 69 passed`
  - install-kit dispatch-record now blocks `SENT_ONE_RECORDED` unless a required operator status receipt is verified, `READY_TO_MANUALLY_SEND_ONE`, release-hash matched, current `dist` artifact matched, private-hash matched, and the required manual-send GO receipt is verified as `GO_TO_MANUALLY_SEND_ONE` with matching release/operator-status proof
  - install-kit operator send bypass audit now verifies the release doc, first-recipient workspace script, operator-status script, post-send sequence script, dispatch-record script, recipient-checkpoint script, and local private runbook when present; current audit is `NO_OPERATOR_STATUS_BYPASS` with body sha256 `c1c2769e02c248972d4428f18f2ad629767d253282553ada54d079bde34cb0fc`
  - install-kit manual-send GO rehearsal now uses a temporary synthetic private workspace and fixed synthetic `sent_at_utc` to prove `READY_TO_MANUALLY_SEND_ONE` can progress to a temporary `SENT_ONE_RECORDED` dispatch with required preserved ready operator-status and manual-send GO receipts; current rehearsal is `REHEARSAL_PASS` with body sha256 `1ee2dcb227ece6f8ffb380331f01ef2b4674e6e5d79a17d9b4db728743b438fe`, requires `synthetic_dispatch_not_standalone_proof`, and records `real_manual_send=false`, `real_recipient_evidence=false`
  - install-kit post-send checkpoint rehearsal now uses a temporary synthetic private workspace, fixed synthetic `sent_at_utc`, and synthetic returned receipts to prove `RECIPIENT_GOLD_PATH_CONFIRMED` requires install receipt, gold-path receipt, installed-entrypoint MCP receipt, ack hash, dispatch hashes, current-artifact match status, the same preserved `READY_TO_MANUALLY_SEND_ONE` operator-status receipt, and the matching `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt; current rehearsal is `REHEARSAL_PASS` with body sha256 `a2dabb30eede2d565c5725889d693fe507bb9572934a1f61f69539177f75e1b6`, `real_recipient_evidence=false`
  - install-kit release docs and RC checklist now explicitly state that synthetic rehearsal dispatch/checkpoint artifacts are rejected by default verifiers as standalone send or recipient proof
  - install-kit recipient checkpoint now rejects any post-send evidence path unless the operator-status receipt and manual-send GO receipt are supplied and verified, closing the previous route where recipient-checkpoint could indirectly record `SENT_ONE_RECORDED` without the pre-send GO receipt or final manual-send GO receipt
  - MCP installed proof now distinguishes source-tree module receipts from installed `cambrian-mcp` entry point receipts with `server_command_mode`, `installed_entrypoint_command`, and `installed_entrypoint_required_satisfied`
  - `cambrian mcp verify` now returns `NO_GO` when it falls back to `python -m engine.project_mcp_server` without `--source-tree-mode`; source-tree development verification remains available through `python scripts/verify_mcp_operability.py`
  - install-kit recipient checkpoint now rejects returned `mcp_operability_receipt.json` files unless they prove `server_command_mode=installed_entrypoint`, `installed_entrypoint_command=true`, `source_pythonpath_injected=false`, and no arbitrary shell
  - install-kit recipient checkpoint now rejects `RECIPIENT_GOLD_PATH_CONFIRMED` unless the returned install receipt, gold path receipt, and installed-entrypoint MCP receipt are all present; gold path receipt alone can no longer imply returned MCP proof
  - AI Company Golden Path fresh wheel smoke passed with installed `cambrian-mcp` entry point operability: `server_command_mode=installed_entrypoint`, `installed_entrypoint_command=true`, `source_pythonpath_injected=false`, `verdict=GO`
  - root pytest collection now ignores One Good Harness fixture project tests through `tests/conftest.py`, keeping those tests under `scripts/smoke_one_good_harness_fixture.py`; `python -m pytest --collect-only -q tests` now collects `2661` tests without fixture import errors
  - current installed-entrypoint MCP proof passed `cambrian mcp verify --receipt dist/mcp_operability_receipt.json` with receipt sha256 `4a7b717ead9e545f166033da2c6b58b50ad4e6cc11ac1187a08d1841f429c20a`, `server_command_mode=installed_entrypoint`, `installed_entrypoint_command=true`, `source_pythonpath_injected=false`, and `verdict=GO`
  - current AI Company Golden Path smoke passed `python scripts/smoke_ai_company_gold_path.py` with summary sha256 `7d935a6afd8fc5fc75470a8243862353e89c39eeccc7978abdc57058f9d81234` and installed MCP receipt sha256 `d09e31117439723098c7dc6c3faa028beec4add6fdee5a040bfa85c3713bb1d4`
  - install-kit release bundle was regenerated after hash-stability hardening and passes sender-side current artifact verification plus bundle smoke; release bundle sha256 is `ba629ea6a4db04c43b7f7e1cc7128952b3a1ab3f59805cdc68af25314477bfd9`, internal install kit ZIP sha256 is `7fe6142adfe64bf123ac4f5c1f907b5a772fd761924d328116e3c543032bdf51`, release receipt body sha256 is `c1d96d178e4fee354c7ef375281cdb4098e3a1a2fb284b5e261fbbbc30c79003`, and bundle smoke body sha256 is `541b68b6ab1ad6bf9c99e6b3d75cd9a3a7e46eafcb20a54a16aa27829c4207d9`
  - install-kit handoff body sha256 is `cc96ef38d2571972f357aabf29dd85f4c0bde5d0eaae9d7a9ac59605a900a98e`; send-ready remains `GO` with body sha256 `3df6b1113841e4d0d3dda3e85f643248b7f2a3a2c40c3f4059e5c8817a05e1f7`
  - install-kit dispatch-record is `READY_TO_SEND_ONE` with body sha256 `6535c7f1785c29f4dc179cfef188a5b575738e9fda4b963b605fa53c706ad0f4`; install-kit recipient-checkpoint remains `WAITING_FOR_RECIPIENT` with body sha256 `b404e209ac3718da2c1f2ed323507dcfb4eca74dfe0290aba3c1e51eb360e872` and `blocking_summary.missing_evidence` still starts with `SENT_ONE_RECORDED dispatch record`
  - install-kit first-recipient operator status now includes a share-safe `operator_launch_snapshot` with stage, send state, release bundle sha256, sender-side current-artifact match status, MCP smoke proof, private workspace readiness, dispatch state, open gates, next safe action, and the controlled two-file human private-field checklist; current status remains `FILL_PRIVATE_FIELDS` with body sha256 `0fb46b3e51cf4672712e3a59375c2482e58e17ffce6d0307122c453f90cb14c9`
  - install-kit first-recipient operator status now blocks self-consistent but stale release bundles before manual send by reusing `verify_release_bundle_current_artifacts`; a current `dist` mismatch returns `PREPARE_RELEASE_BUNDLE` with open gate `release_bundle_current_artifacts_match`
  - install-kit first-recipient operator status now writes `cambrian-install-kit-first-recipient-operator-status.md`, a share-safe human status board that mirrors verdict, open gates, private file statuses, release bundle sha256, current-artifact match status, MCP smoke proof, and safe commands without raw recipient/channel values; it now includes a controlled command use order plus the post-send recipient checkpoint command with the preserved READY operator-status receipt and returned MCP proof path so the operator does not need to hunt through the private runbook after receipts return
  - install-kit first-recipient workspace and operator status body hashes now exclude `generated_at`, so rerunning the same blocked state does not stale downstream proof hashes or churn the pre-send receipt
  - install-kit handoff, send-ready, dispatch-record, recipient-checkpoint, manual-send GO rehearsal, and post-send checkpoint rehearsal body hashes now exclude or neutralize `generated_at` and synthetic timestamp churn, so identical proof states replay with stable body hashes
  - install-kit first-recipient private runbook now names the operator status board as the human-readable GO/NO-GO view, includes the final manual-send GO command before dispatch, and shows the two-file human edit checklist before any send; current workspace receipt body sha256 is `35e2563be66bc99d2963bec1e30614f8ec662c2f737e531a2b0501203e73ea00`
  - current first-recipient pre-send sequence remains safely blocked before manual send with body sha256 `82d331e499da2b644b7ea2753374d52fbca926df2ea4e6bdeb9c954066544bcf`; it now records `operator_status_board_file`, controlled `human_next_steps`, and the operator-status current-artifact gate (`release_current_artifacts_checked=true`, `release_current_artifacts_match=true`), open gates remain `recipient_private_ready` and `operator_note_names_private_channel`, and no script sends to a recipient or records dispatch before `READY_TO_MANUALLY_SEND_ONE`
  - install-kit first-recipient manual-send GO now writes `cambrian-install-kit-first-recipient-manual-send-go-receipt.json`, reruns the pre-send sequence, and returns `GO_TO_MANUALLY_SEND_ONE` only after pre-send READY, preserved READY operator-status receipt, current-artifact gate, operator send-bypass audit, manual-send rehearsal, and one-recipient manual-dispatch policy all pass; current default remains `BLOCKED_BEFORE_MANUAL_SEND` with body sha256 `575ec71a557bc7fd0ae08a22c8ed7909ffad9d49bfbeaaf88f498b2897f8f87c`
  - install-kit operator send bypass audit now treats manual-send GO as part of the required pre-send proof: release docs, runbooks, dispatch-record, post-send sequence, and recipient-checkpoint surfaces must include `--manual-send-go-receipt` and `--require-manual-send-go-receipt` whenever they can record send evidence
  - current first-recipient post-send sequence remains safely blocked before manual-send evidence with body sha256 `f89d0e681a33cd002e04c0e26c237f718293ae4a932d58823662ab49d8e33325`; it now records controlled `human_next_steps` for real UTC timestamp, acknowledgement, returned receipt follow-up, the current-artifact match inherited from dispatch-record, and the recipient-checkpoint copy-paste boundary when a checkpoint is recorded
  - install-kit first-recipient sequence regression lanes now keep the expensive install verification out of synthetic fixture tests by passing `skip_verify=True` only in those fixture calls; product CLI defaults still run the full gate, while the focused OS-11 regression pack now completes as `25 passed, 78 deselected` and the full install-kit suite completes as `104 passed` with manual-send GO bound through dispatch, post-send sequence, and recipient checkpoint
  - install-kit operator-facing recipient checkpoint commands now omit `--skip-verify`; `--skip-verify` is reserved for synthetic regression tests and trusted local rehearsals, so the real first-recipient launch path stays on the full verification gate
  - pending real first-recipient install receipt
  - pending real first-recipient gold path receipt
  - pending real first-recipient MCP operability receipt
  - pending recipient checkpoint with private-safe hashes only
next_task: OS-12
```

### OS-12 One Good Harness Generalization

```yaml
status: completed
why: AVF에서 한 번 닫힌 One Good Harness는 중요하지만, 한 번의 성공은 제품 일반성을 증명하지 않는다.
goal: AVF proof를 재사용 가능한 fixture, command gate, status truth contract로 일반화해 최소 두 종류의 프로젝트에서 같은 harness loop가 닫히게 한다.
implementation:
  - create a deterministic One Good Harness fixture project that is safe to commit
  - require scan, design/review, install, status, job start, reply envelope, validate, complete, verdict in one scripted gate
  - assert active custom harness state is preferred over legacy profile noise
  - enforce required AI reply evidence envelope before validation can become verified
  - record failed envelope and missing evidence cases as explicit hold verdicts
  - add `scripts/smoke_one_good_harness_fixture.py` as the first replayable fixture receipt gate
  - use `tests/fixtures/one_good_harness/python_auth_service` as the safe committed fixture
  - generalize the fixture replay script so a second committed fixture can reuse the same closed loop
  - use `tests/fixtures/one_good_harness/python_invoice_rules` as the second non-AVF fixture
  - add `status_truth` to `cambrian status --json` so the active harness, agents, skills, authority, validation, and evidence gaps are visible in one structured surface
completion_criteria:
  - AVF-style harness proof can be replayed without private target project files
  - a second non-AVF fixture passes the same closed loop
  - missing evidence envelope produces hold, not fake pass
  - status truth shows active harness, agents, skills, authority, validation, and evidence gaps consistently
tests:
  - python -m pytest -q tests/test_project_harness_profile.py tests/test_harness_engineer_review.py tests/test_job_start_runtime_contract.py tests/test_job_complete_evidence.py
  - add a One Good Harness fixture test that runs scan -> install -> status -> job start -> ingest/validate -> complete
  - python scripts/smoke_one_good_harness_fixture.py
  - python scripts/smoke_one_good_harness_fixture.py --fixture-dir tests/fixtures/one_good_harness/python_invoice_rules --receipt dist/one-good-harness-python-invoice-rules-replay-receipt.json
  - python scripts/smoke_one_good_harness_fixture.py --verify-receipt dist/one-good-harness-fixture-replay-receipt.json
  - python scripts/smoke_one_good_harness_fixture.py --verify-receipt dist/one-good-harness-python-invoice-rules-replay-receipt.json
  - python scripts/smoke_one_good_harness_fixture.py --expect-hold --receipt dist/one-good-harness-missing-evidence-hold-receipt.json
  - python scripts/smoke_one_good_harness_fixture.py --verify-receipt dist/one-good-harness-missing-evidence-hold-receipt.json
  - python -m pytest -q tests/test_one_good_harness_fixture.py
  - python -m pytest -q tests/test_project_mode.py tests/test_one_good_harness_fixture.py
  - python -m py_compile engine/project_mode.py engine/project_harness_profile.py engine/project_harness_interview.py engine/project_custom_harness.py
evidence:
  - AVF closed pass recorded in docs/product/51_HARNESS_FIRST_REALITY_CHECK.md
  - first committed One Good Harness fixture receipt now writes `dist/one-good-harness-fixture-replay-receipt.json`
  - second committed One Good Harness fixture receipt now writes `dist/one-good-harness-python-invoice-rules-replay-receipt.json`
  - missing-evidence hold replay now writes `dist/one-good-harness-missing-evidence-hold-receipt.json`
  - fixture replay verifies project scan, interview answer, harness engineering design/review/dry-run, install, status, job start, reply ingest, validation run, job complete, and pass verdict
  - missing-evidence replay verifies weak AI reply evidence becomes hold with `trust_gate_status != verified`
  - fixture replay asserts source hashes unchanged, provider API not called, public proof claim locked, and sale_ready false
  - `cambrian status --json` now exposes `status_truth.active_harness`, `active_agents`, `active_skills`, `authority`, `validation`, `evidence`, `evidence_gaps`, and `release_boundaries`
  - status truth is fail-closed: missing baseline, missing artifacts, unchecked items, unverified trust gate, and a newest job without matching verdict appear as evidence gaps instead of hidden success
  - `cambrian company status --json` now derives `project_company_ready` from mission last_outcome plus a matching verification ledger pass/verified entry instead of stale hard-coded blockers
next_task: OS-13
```

### OS-13 Docs Authority / Scanner Truth Hardening

```yaml
status: completed
why: Cambrian이 모든 MD와 generated artifact를 같은 권위로 읽으면 호텔/예약/인증 같은 잘못된 도메인 환각이 반복된다.
goal: source-of-truth 문서, 코드 evidence, sample/demo/generated noise를 분리해 scan과 interview가 프로젝트 정체성을 보수적으로 판단하게 한다.
implementation:
  - define document authority tiers for root identity docs, product docs, release docs, samples, and generated artifacts
  - make scanner skip pytest basetemp, launch runs, archives, fixtures, build, dist, and runtime generated evidence for identity/domain promotion
  - keep sample skills and demo artifacts as capability catalog evidence, not current project domain evidence
  - expose authority/noise policy in project scan evidence_card
  - add regression tests for generated artifact domain pollution
completion_criteria:
  - generated test artifacts cannot change language, test framework, or product domain
  - sample skills and demo docs cannot become project identity by keyword alone
  - docs-to-interview inference records which documents were used and excludes generated/noisy sources
  - project scan evidence_card shows the document authority and noise boundary policy
tests:
  - python -m pytest -q tests/test_project_harness_profile.py tests/test_harness_interview.py tests/test_ai_company_os_task_backlog.py
  - python -m py_compile engine/project_harness_profile.py engine/project_harness_interview.py
evidence:
  - scanner now skips generated/runtime/sample identity noise including `.pytest*/`, `.launch_runs/`, `archive/`, `dist/`, `build/`, `fixtures/`, `demo/`, `examples/`, `sample/`, `samples/`, and `skill_pool/`
  - demo, examples, and skill_pool code can no longer set the active project language or domain during project scan
  - project scan evidence_card exposes `document_authority` and `noise_filter` policies, including generated/demo/sample exclusion boundaries
  - interview doc inference now records `document_authority` and `noise_filter` in `document_context`
  - interview doc inference excludes generated/demo/sample/runtime Markdown before inferring primary_goal, test_command, change_policy, or agent roles
  - regression tests now cover generated pytest/launch artifacts, demo/examples/skill_pool scan pollution, document authority exposure, and interview authority/noise context
  - python -m pytest -q tests/test_project_harness_profile.py tests/test_harness_interview.py tests/test_ai_company_os_task_backlog.py -> 22 passed
  - python -m py_compile engine/project_harness_profile.py engine/project_harness_interview.py -> passed
next_task: none
```

## 4. Current Next Task

```yaml
current_next_task: OS-11
reason: OS-01 Mission Control through OS-13 Docs Authority / Scanner Truth Hardening are completed or technically ready; the remaining launch-critical proof is still OS-11 real first-recipient evidence, which requires human-only private recipient/channel input before any send.
```

### 2026-05-23 OS-11 Install-Kit Truthful Blocked Diagnostics

```yaml
status: blocked_on_human_private_fields
why: The first-recipient gate should stay fail-closed but should not falsely report the seeded current release hash as missing.
implementation:
  - unresolved operator-note scaffold still blocks manual send as placeholder
  - operator status now reports the seeded current release bundle sha256 as present when it is present
  - open gates in default private workspace are now recipient_private_ready and operator_note_names_private_channel
  - pre-send summary now reports operator-dispatch-note-private.md contains_release_hash=true while mentions_channel=false
evidence:
  - release_bundle_sha256: a2462b1d6b9fc80e7d97bf3de3a9bc39f1ae3b5b98c44791bbaa48bf4d712577
  - internal_install_kit_zip_sha256: 0b426ce2864e4011dcc8c5402f0f57f83f660c2968a2b58f3ac5d26775ec4623
  - release_receipt_body_sha256: 021f89f50e0fe4f9d370507e8c0b872c9a0c34f954d4f3d536377e00d7aedb43
  - release_bundle_smoke_body_sha256: 5d3e724f8f4b486eed81a204be2f64eac0bd69bcde8ac922f16a37566e21a9cf
  - send_ready_verdict: GO
  - dispatch_record_verdict: READY_TO_SEND_ONE
  - operator_send_bypass_audit: NO_OPERATOR_STATUS_BYPASS
  - operator_send_bypass_audit_body_sha256: 69a90f828a6df8e1b52cba5320d27a06346d5fb4c227ce0d8da862f9218dbc82
  - first_recipient_workspace_body_sha256: fc5898b860c0b75cf1e720111abe3f7b23d204bfb3374102f6587475e9bc238f
  - first_recipient_operator_status: FILL_PRIVATE_FIELDS
  - first_recipient_operator_status_body_sha256: d4d81aeb8151c26a44ff899efe04f5929274b4bde738813e4c1543ac13314c6c
  - first_recipient_open_gates: recipient_private_ready, operator_note_names_private_channel
  - first_recipient_pre_send: BLOCKED_BEFORE_MANUAL_SEND
  - first_recipient_post_send_placeholder: BLOCKED_AFTER_MANUAL_SEND
tests:
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_operator_status or first_recipient_pre_send_sequence" -> 10 passed
boundary: no real send, no private recipient data entry, no publish, no deploy, no git push
next_human_action: fill exactly one recipient and replace <private-send-channel>; the seeded release hash can remain if it matches the current bundle
```

### 2026-05-23 OS-11 Install-Kit Private Operator Note Fail-Closed Template

```yaml
status: blocked_on_human_private_fields
why: The first-recipient operator note must teach the exact private channel/hash shape without letting a seeded hash-only scaffold count as real send readiness.
implementation:
  - install-kit first-recipient workspace now seeds operator-dispatch-note-private.md with a structured local-only template
  - the template includes private channel: <private-send-channel> plus the current release bundle sha256
  - operator status now treats unresolved <private-send-channel> or the legacy channel placeholder as placeholder, not ready
  - existing real private operator notes are preserved
  - release documentation now states that the seeded release hash is instructional only
evidence:
  - release_bundle_sha256: 51194767bb137cfafae1984cb92e6ea76ea54a6b09ce1e515934c888db1b5e70
  - internal_install_kit_zip_sha256: 535b55ceaf4078cc5cc6bf4285e3fdb3761a1c947ec033718b2abc0b1142716e
  - release_receipt_body_sha256: e5faa3d09d500d8ee8db88ab57521b893a60a442862825059d32560212f70947
  - release_bundle_smoke_body_sha256: 16bda5e5c566971ee58a9c14425c0f11ed6bcc10451ad9e81069c0a58b6f1721
  - send_ready_verdict: GO
  - dispatch_record_verdict: READY_TO_SEND_ONE
  - operator_send_bypass_audit: NO_OPERATOR_STATUS_BYPASS
  - operator_send_bypass_audit_body_sha256: 16502cff130e1a0b54da5d6fc384dd8809f3f3fa69f159b258afca371a440352
  - first_recipient_workspace_body_sha256: e99d38c80b958a52c03df97880511629cd78e653260be18c7209c80c09896341
  - first_recipient_operator_status: FILL_PRIVATE_FIELDS
  - first_recipient_operator_status_body_sha256: 8e4d2ab49496e3ade95588a42c2a3e68f9110ef51e8eb97c416a8a4f844ceade
  - first_recipient_pre_send: BLOCKED_BEFORE_MANUAL_SEND
  - first_recipient_post_send_placeholder: BLOCKED_AFTER_MANUAL_SEND
tests:
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_workspace or first_recipient_operator_status" -> 9 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "operator_send_bypass_audit" -> 3 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_pre_send_sequence" -> 4 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_post_send_sequence" -> 6 passed
boundary: no real send, no private recipient data entry, no publish, no deploy, no git push
next_human_action: replace recipient-private.txt and <private-send-channel>, rerun the pre-send sequence, then manually send exactly one bundle only after READY_TO_MANUALLY_SEND_ONE
```

### 2026-05-23 OS-11 Install-Kit First Recipient Runbook Hardening

```yaml
status: blocked_on_human_private_fields
why: OS-11 is still the correct next task, but Cambrian must not let a copied placeholder command break in Bash or PowerShell before the human replaces it.
implementation:
  - install-kit private first-recipient runbook now quotes command placeholders such as "<real-sent-at-utc>"
  - install-kit share-safe workspace/operator-status receipts now self-check shell-safe placeholder commands
  - release bundle regenerated after the runbook/operator command contract changed
evidence:
  - release_bundle_sha256: 66bfa7e40b5a14b624b4b78fbf0cfeb1396ee216c2458d7f67c876bc5cb4d8ba
  - internal_install_kit_zip_sha256: 5de24df0619f663f7f102a0396bd0285b9e08e364b313c6696c4b13cb1bff46d
  - release_bundle_smoke_body_sha256: fe5a1708e0bffd960095f5a337920ec00dc47f24f2984b9d3cc8f61526a0f94a
  - send_ready_verdict: GO
  - dispatch_record_verdict: READY_TO_SEND_ONE
  - first_recipient_operator_status: FILL_PRIVATE_FIELDS
  - first_recipient_pre_send: BLOCKED_BEFORE_MANUAL_SEND
  - first_recipient_post_send_placeholder: BLOCKED_AFTER_MANUAL_SEND
tests:
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_workspace or first_recipient_operator_status" -> 8 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "install_kit_doc_records_build_and_verify_commands or first_recipient_workspace or first_recipient_operator_status or post_send_sequence" -> 15 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_pre_send_sequence or first_recipient_post_send_sequence" -> 10 passed
boundary: no real send, no private recipient data entry, no publish, no deploy, no git push
next_human_action: fill exactly one real recipient and private send channel, then rerun the pre-send sequence
```

### 2026-05-23 OS-11 Operator Send Bypass Audit Shell-Safe Gate

```yaml
status: blocked_on_human_private_fields
why: The shell-safe first-recipient runbook rule must be enforced by the same operator send-bypass audit that blocks send-record shortcuts.
implementation:
  - operator send-bypass audit now checks operator command placeholders for shell safety
  - audit receipt records operator_command_placeholders_shell_safe per audited source
  - unsafe private runbook command with --sent-at-utc <real-sent-at-utc> now fails the audit
evidence:
  - release_bundle_sha256: 81465d011444f47758b3f99227ab13952fa487d76ccaaca74e9c33a64c9481ca
  - internal_install_kit_zip_sha256: 91fd2daeb4ef359c3dbda953cf78aeba9d22db440df831bb0ffe938b05a54dac
  - release_bundle_smoke_body_sha256: a1a75c062606f111cb6a31eaad3acd6993997de69cfa9846d162bd13c8db0d43
  - send_ready_verdict: GO
  - dispatch_record_verdict: READY_TO_SEND_ONE
  - operator_send_bypass_audit: NO_OPERATOR_STATUS_BYPASS
  - operator_send_bypass_audit_body_sha256: 77a4377960f2c1b6e7c7932b6be21ed74dfadaa56ac9ab2f28fbf07e163c8a8e
  - first_recipient_operator_status: FILL_PRIVATE_FIELDS
  - first_recipient_pre_send: BLOCKED_BEFORE_MANUAL_SEND
  - first_recipient_post_send_placeholder: BLOCKED_AFTER_MANUAL_SEND
tests:
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "operator_send_bypass_audit" -> 3 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "operator_send_bypass_audit or first_recipient_workspace or first_recipient_operator_status" -> 11 passed
  - python -m pytest -q tests/test_cambrian_install_kit.py -k "first_recipient_pre_send_sequence or first_recipient_post_send_sequence" -> 10 passed
boundary: no real send, no private recipient data entry, no publish, no deploy, no git push
next_human_action: fill exactly one real recipient and private send channel, then rerun the pre-send sequence
```

## 5. Update Policy

- 완료된 task는 `status: completed`로 바꾸고 `evidence`를 채운다.
- 부분 구현은 `status: in_progress`로 바꾸고 남은 gap을 유지한다.
- 막힌 task는 `status: blocked`와 blocker evidence를 기록한다.
- 새 task는 기존 OS task 아래에 붙인다. 새 축을 만들지 않는다.
- Marketplace 작업은 `OS-10` 이후 또는 proof maturity 이후로 둔다.
