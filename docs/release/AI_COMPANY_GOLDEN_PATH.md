# AI Company Golden Path

## Purpose

이 문서는 Cambrian 설치형 제품의 핵심 골든패스를 고정한다.

목표는 새 환경에 wheel로 설치한 사용자가 아래 네 가지를 provider API key 없이 만들 수 있는지 확인하는 것이다.

```text
1. AI 에이전트 생성
2. 스킬 생성, 검색, 융합
3. 하네스 엔지니어링 시스템 생성
4. evidence 기반 진화 제안, preview, apply
5. private-safe AI company snapshot 생성
```

## Golden Path Command

저장소 루트에서 아래 명령을 실행한다.

```bash
python scripts/smoke_ai_company_gold_path.py
```

이 smoke는 임시 fresh venv를 만들고, 현재 소스에서 wheel을 빌드한 뒤, 설치된 `cambrian` 명령만 사용해 골든패스를 검증한다.
wheel은 임시 wheelhouse에 빌드하므로 기존 `dist/` 릴리즈 산출물을 지우지 않는다.

## Verified Flow

검증 순서:

```text
build wheel
create venv
install wheel
cambrian --help
cambrian doctor
project scan
harness interview start
harness interview answer
harness engineer design
harness engineer review
harness engineer dry-run
workforce generate
skill generate
harness install --confirm
skill search
skill fuse
job start
job complete
evolve propose
evolve preview
evolve apply --confirm
company snapshot
```

## Capability Mapping

### AI 에이전트 생성

`harness install --confirm` 이후 `.cambrian/agents/*.yaml`이 생성되어야 한다.
골든패스는 최소한 `.cambrian/agents/auth-flow-investigator.yaml` 생성을 확인한다.

### 스킬 생성, 검색, 융합

`skill generate`는 프로젝트 하네스와 workforce에 맞는 `.cambrian/skills/*.yaml` draft를 만든다.
`skill search auth token --json`은 설치된 generated skill 중 `trace-auth-token-flow`를 찾아야 한다.
`skill fuse trace-auth-token-flow inspect-jest-auth-test --goal ... --json`은 provider API 없이 새 fused generated skill을 만들고 workforce mapping에 연결해야 한다.

### 하네스 엔지니어링 시스템

`harness engineer design`, `review`, `dry-run`은 설치 전 설계 후보, 품질 검수, dry-run evidence를 만들어야 한다.
설치 전 자동 dispatch나 source patch apply는 없어야 한다.

### 진화

`job complete`가 outcome evidence를 기록한 뒤 `evolve propose`, `preview`, `apply --confirm`이 통과해야 한다.
진화는 source code를 자동 수정하지 않고 `.cambrian/` metadata를 evidence 기반으로 조정한다.

### Company Snapshot

`company snapshot --json`은 설치된 `cambrian` 명령에서 private-safe company artifact를 생성해야 한다.
스냅샷은 raw project data, secrets, raw AI replies, result bodies를 포함하지 않고 summary, relative refs, sha256 fingerprints, proof summary, lineage만 포함해야 한다.
Marketplace 상태는 proof maturity 전까지 `sale_ready: false`, `proof_claim_allowed: false`를 유지한다.

## Latest Local Result

최근 실행 결과:

```text
Result: PASS
Summary: .launch_runs/ai_company_gold_path_latest
Installed wheel smoke: PASS
company_snapshot_generated: true
```

주요 PASS 항목:

```text
skill search finds generated skill: PASS
skill fuse creates project skill: PASS
job start selects agents and skills: PASS
evolve apply: PASS
company snapshot is private-safe artifact: PASS
```

## MCP Operability Gate

The golden path now treats MCP operability as an official external-user proof gate, not a supplemental developer check.

Command:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Source-tree command:

```bash
python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
```

Inside `python scripts/smoke_ai_company_gold_path.py`, the verifier is run through the freshly installed wheel's `cambrian mcp verify` command against the installed `cambrian-mcp` entry point with source-tree `PYTHONPATH` disabled.

External client setup is fixed in `docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md`.

The receipt must show:

```text
verdict: GO
initialize: true
tools_list: true
missing_cwd_blocked: true
project_scan_with_explicit_cwd: true
harness_install_requires_confirm: true
allowlisted_cli_only: true
no_arbitrary_shell: true
explicit_cwd_required: true
```

This is the official local proof that an external AI workbench can operate Cambrian through MCP without raw shell access.

Latest expected capability summary:

```text
mcp_operability_verified: true
installed cambrian-mcp entry point is operable: PASS
```

## One Good Harness Fixture Replay

OS-12 adds a deterministic fixture proof so One Good Harness can be replayed without
private AVF files or live provider calls.

Command:

```bash
python scripts/smoke_one_good_harness_fixture.py
python scripts/smoke_one_good_harness_fixture.py --fixture-dir tests/fixtures/one_good_harness/python_invoice_rules --receipt dist/one-good-harness-python-invoice-rules-replay-receipt.json
python scripts/smoke_one_good_harness_fixture.py --expect-hold --receipt dist/one-good-harness-missing-evidence-hold-receipt.json
```

Receipt:

```text
dist/one-good-harness-fixture-replay-receipt.json
dist/one-good-harness-python-invoice-rules-replay-receipt.json
dist/one-good-harness-missing-evidence-hold-receipt.json
```

The replay now covers two safe committed fixtures:

```text
tests/fixtures/one_good_harness/python_auth_service
tests/fixtures/one_good_harness/python_invoice_rules
```

Each replay verifies project scan, interview answer, harness engineering
design/review/dry-run, install, status, job start, AI reply evidence ingest,
validation run, job complete, and final pass verdict. Each receipt is share-safe:
it omits the temp workdir, keeps source hashes unchanged, records no live provider
API call, and keeps public proof/sale claims locked.

The negative replay uses an intentionally weak AI reply and must produce
`ONE_GOOD_HARNESS_HOLD_REPLAYED`. This proves missing evidence is recorded as hold
instead of being promoted into a fake verified pass.

## Status Truth Gate

`cambrian status --json` now includes a top-level `status_truth` contract.

This is the first surface an external user or external AI workbench should inspect
after install. It must show:

```text
active_harness
active_agents
active_skills
authority
validation
evidence
evidence_gaps
release_boundaries
```

The status truth gate is intentionally fail-closed. A fitted harness is not enough
by itself. If the project baseline is missing, active agents or skills are absent,
validation commands are missing, a trust gate is not verified, unchecked items are
present, or the newest job has no matching latest verdict, `status_truth.status`
must become `partial` and `evidence_gaps` must name the reason.

For the active mission loop this means an open job appears as
`latest_job_not_validated` until validation and completion write a matching
verdict. A verified status truth permits a status-truth claim only; it still does
not permit an external release, public proof, or sale-readiness claim without the
separate real external-recipient proof from OS-11.

## Boundary

이 골든패스가 증명하는 것은 설치형 로컬 AI company runtime의 핵심 루프다.

아직 증명하지 않는 것:

```text
public marketplace
payment
cloud execution
multi-user proof claim
자동 source code patch apply
외부 provider API를 통한 완전 자율 생성
raw private project data export
```

따라서 이 상태는 외부 알파와 RC 골든패스에는 충분하지만, 공개 marketplace 출시를 의미하지 않는다.
