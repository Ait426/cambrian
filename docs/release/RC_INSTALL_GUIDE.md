# Cambrian RC Install Guide

## Purpose

이 문서는 Cambrian RC를 새 환경에 wheel로 설치하고 Auth Bug Core 골든패스를 검증하는 절차입니다. 목표는 소스 트리 전용 데모가 아니라 설치형 제품 흐름을 확인하는 것입니다.

## Agent Platform External Alpha

외부 알파 사용자는 먼저 Agent Platform Builder를 로컬 브라우저에서 확인할 수 있습니다.
이 경로는 공개 marketplace, 결제, cloud execution, provider API key를 요구하지 않습니다.
이 경로는 단순 MVP가 아니라 Defensible Alpha입니다.
목표는 한국 시장에서 에이전트 쇼핑몰 UI를 복제하는 것이 아니라, agent contract, preflight, promotion audit lineage, proof boundary 표준을 먼저 선점하는 것입니다.

시작 파일:

```text
QUICKSTART_EXTERNAL_ALPHA.md
START_HERE_EXTERNAL_ALPHA.md
RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md
EXTERNAL_ALPHA_SUPPORT_PACKET.md
START_CAMBRIAN_AGENT_PLATFORM.bat
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

Windows에서 `START_CAMBRIAN_AGENT_PLATFORM.bat`를 더블클릭하면 아래 화면이 열립니다.

```text
web/platform/index.html
```

수동 검증:

```bash
python scripts/verify_platform_alpha.py
```

Recipient ZIP verification should normally start with `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat`.
The batch creates or reuses `.venv`, runs `python -m pip install -e .` from the extracted folder when needed, and then runs `scripts/verify_platform_alpha.py`.
For manual verification in a fresh folder, run:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python scripts\verify_platform_alpha.py
```

시크릿 없는 진단 리포트 생성:

```bash
python scripts/collect_external_alpha_diagnostics.py
```

`COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat` uses the same `.venv` bootstrap before writing diagnostics.

Optional browser UI smoke:

```bash
npm install --prefix C:\tmp\cambrian-playwright-deps playwright
python scripts/verify_agent_platform_browser_flow.py --node-modules C:\tmp\cambrian-playwright-deps\node_modules --single
```

기본 출력은 `external_alpha_diagnostics.json`이다. 이 리포트는 환경 변수, `.env` 파일 내용, secret 값, 사용자 문서를 수집하지 않는다.
지원 요청에는 `safe_to_share: true`와 모든 `redaction_checks: true`가 표시된 diagnostics JSON만 첨부한다.
`support_summary`에는 검증 상태, 누락 파일, 다음 조치, 공유 금지 항목이 요약된다.
`.env`, 브라우저 `localStorage`, 사용자 원문 문서, raw AI reply는 공유하지 않는다.

외부 알파 ZIP 생성:

```bash
python scripts/build_external_alpha_release.py
```

외부 알파 ZIP 수령자 관점 검증:

```bash
python scripts/verify_external_alpha_release.py
```

Operator-only recipient-style bundle smoke:

```bash
python scripts/smoke_external_alpha_release_bundle.py
```

Operator-only post-send checkpoint rehearsal:

```bash
python scripts/smoke_external_alpha_post_send_checkpoint.py
```

Operator-only pilot learning loop rehearsal:

```bash
python scripts/smoke_external_alpha_pilot_learning_loop.py
```

Operator-only private pilot workspace rehearsal:

```bash
python scripts/smoke_external_alpha_private_pilot_workspace.py
```

Operator-only manual send GO rehearsal:

```bash
python scripts/smoke_external_alpha_manual_send_go_rehearsal.py
```

This rehearsal also proves the synthetic private-input path makes `check_external_alpha_first_recipient_operator_status.py` report `READY_TO_MANUALLY_SEND_ONE`, without claiming a real recipient was contacted.

Operator-only private pilot workspace scaffold:

```bash
python scripts/prepare_external_alpha_private_pilot_workspace.py --workspace-dir <private-workspace-dir>
```

Operator-only first-recipient send workspace:

```bash
python scripts/prepare_external_alpha_first_recipient_send_workspace.py --workspace-dir <private-workspace-dir> --operator-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
```

First-recipient full pre-send sequence:

```bash
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py --workspace-dir <private-workspace-dir>
```

If blocked, the receipt and terminal output name only the required private file statuses, such as `recipient-private.txt=placeholder`. They must not include raw recipient text or local paths.

First-recipient operator status:

```bash
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir <private-workspace-dir>
```

This reports the current safe stage and next action without sending anything, without raw private values, and without local paths. Use it before send, after send, and after acknowledgement if you are unsure which command comes next.

If the verdict is `CHECK_RELEASE_CHAIN`, run `python scripts/audit_external_alpha_send_chain.py` before any send. If the output names `release_sources_match_current_manifest`, rebuild the release artifacts and rerun the operator packet/workspace/pre-send sequence. The status receipt prints only controlled check IDs, not raw private values or local paths.

First-recipient post-send sequence:

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>
```

If the recipient has not acknowledged yet, this records the manual send and prints only safe ack status such as `recipient-ack-private.txt=placeholder`, plus the next action. It must not include raw acknowledgement text or local paths.

Receipt-only verification does not require `--sent-at-utc`:

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --verify-receipt <private-workspace-dir>\external-alpha-first-recipient-post-send-sequence-receipt.json
```

Post-send private workspace shortcut:

```bash
python scripts/check_external_alpha_dispatch_record.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --require-preflight-receipt
python scripts/check_external_alpha_recipient_checkpoint.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --require-preflight-receipt --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>
```

Operator dispatch packet:

```bash
python scripts/prepare_external_alpha_operator_dispatch_packet.py
```

Operator-only public download launch chain:

```bash
python scripts/prepare_external_alpha_download_landing.py
python scripts/prepare_external_alpha_public_download_site.py
python scripts/package_external_alpha_public_download_site.py
python scripts/check_external_alpha_public_deploy_candidate.py
python scripts/check_external_alpha_cloudflare_pages_deploy_ready.py
python scripts/check_external_alpha_cloudflare_credentials.py
python scripts/launch_external_alpha_cloudflare_pages.py
python scripts/check_external_alpha_public_launch_doctor.py
python scripts/run_external_alpha_public_launch_sequence.py
python scripts/finalize_external_alpha_public_launch_url.py
python scripts/verify_external_alpha_public_download_site_url.py
python scripts/prepare_external_alpha_public_share_packet.py
python scripts/prepare_external_alpha_public_launch_handoff.py
```

Read `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md` before setting launch credentials. The guarded public launch sequence blocks before deploy unless both `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are present, writes `dist/cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json`, and only reaches `PUBLIC_LAUNCH_SEQUENCE_READY` after the public HTTPS URL gate and share packet are verified. The upload package is `cambrian-public-site.zip`; the downloadable user artifact remains `cambrian-alpha.zip`.

공유 가능한 검증 영수증 생성:

```bash
python scripts/verify_external_alpha_release.py --receipt external_alpha_release_verification_receipt.json
```

외부 사용자 전달용 handoff 생성:

```bash
python scripts/prepare_external_alpha_handoff.py
```

handoff JSON 단독 확인:

```bash
python scripts/prepare_external_alpha_handoff.py --verify-handoff cambrian-agent-platform-external-alpha-handoff.json
```

외부 사용자 발송 직전 GO/NO-GO 판정:

```bash
python scripts/check_external_alpha_send_ready.py
```

이 판정은 handoff JSON 단독 검증, receipt 단독 검증, diagnostics privacy, copy-paste message, do-not-share guardrail이 모두 맞을 때만 `GO`를 기록한다.
copy-paste message는 `QUICKSTART_EXTERNAL_ALPHA.md`를 첫 진입점으로 안내하고, 실행 경로 확인 후 정확히 `CONFIRMED` 한 줄로만 회신하라는 요청, Claude/Codex 위임용 `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md` 안내, 스크린샷 원문 금지 문구까지 포함해야 한다.
판정서의 `artifact_chain`은 release ZIP, handoff JSON, receipt JSON, send-ready JSON의 파일명과 sha256을 연결해 최종 발송 증거를 확인한다.

send-ready JSON 단독 확인:

```bash
python scripts/check_external_alpha_send_ready.py --verify-send-ready cambrian-agent-platform-external-alpha-send-ready.json
```

첫 외부 파일럿 운영 GO/NO-GO 판정:

```bash
python scripts/check_external_alpha_pilot_ready.py
```

이 판정은 send-ready GO, receipt 단독 검증, pilot intake/feedback 개인정보 보호 문구, support do-not-share guardrail, 첫 파일럿 성공/수정/중단 기준이 모두 맞을 때만 `GO`를 기록한다.
pilot-dispatch는 첫 사용자 1명에게 `QUICKSTART_EXTERNAL_ALPHA.md`를 먼저 읽게 하고 짧은 확인 회신만 요청하며, Claude/Codex 위임 시 `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`를 붙여넣게 하고, 사용자 원문과 스크린샷 원문을 받지 않는 문구를 유지해야 한다.
판정서의 `artifact_chain`은 release ZIP, handoff JSON, receipt JSON, send-ready JSON, pilot-ready JSON의 파일명과 sha256을 연결해 첫 파일럿 운영 증거를 확인한다.

pilot-ready JSON 단독 확인:

```bash
python scripts/check_external_alpha_pilot_ready.py --verify-pilot-ready cambrian-agent-platform-external-alpha-pilot-ready.json
```

첫 외부 파일럿 발송 기록 장부:

```bash
python scripts/check_external_alpha_dispatch_record.py
```

이 장부는 첫 사용자 1명 발송만 허용하고, recipient raw identifier와 dispatch message thread raw text를 공개 산출물에 넣지 않는다.
실제 발송 후 기록할 때도 recipient와 운영 노트 원문 대신 private sha256과 UTC 시각만 남긴다.
copy-paste message가 ZIP 파일명, sha256, `QUICKSTART_EXTERNAL_ALPHA.md`, `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`, 짧은 회신 요청, 스크린샷 원문 금지 문구를 유지하는지도 `copy_paste_message_policy`로 고정한다.
수신자 식별자와 운영 노트 원문을 private workspace 파일로 보관했다면 `--recipient-private-file <private-recipient-file>`과 `--operator-dispatch-note-private-file <private-dispatch-note-file>`을 사용할 수 있다. 이 입력 파일들의 내용과 경로는 장부에 저장하지 않고 sha256만 기록한다.

dispatch-record JSON 단독 확인:

```bash
python scripts/check_external_alpha_dispatch_record.py --verify-dispatch-record cambrian-agent-platform-external-alpha-dispatch-record.json
```

dispatch-record requires the recipient-style bundle smoke receipt to PASS and match the current ZIP sha256 before `READY_TO_SEND_ONE`.

수령자 시작 확인 장부:

```bash
python scripts/check_external_alpha_recipient_checkpoint.py
```

이 장부는 수령자가 QUICKSTART_EXTERNAL_ALPHA.md와 검증 경로를 확인했는지 원문 없이 기록한다.
확인 전에는 `WAITING_FOR_RECIPIENT`를 유지하고, 확인 후에도 recipient acknowledgement raw text 대신 private sha256만 남긴다.
수령자가 Builder Golden Path까지 완료했고 플랫폼의 `gold path receipt 다운로드`로 받은 share-safe `external_alpha_builder_gold_path_share_receipt.json`을 보냈다면 `--builder-gold-path-share-receipt`로 함께 기록할 수 있다. 이 경우 `RECIPIENT_GOLD_PATH_CONFIRMED` verdict가 가능하지만, success rate/proof claim/sale ready는 계속 금지한다.
수신자 식별자와 발송 운영 노트 원문 파일도 `--recipient-private-file <private-recipient-file>`과 `--operator-dispatch-note-private-file <private-dispatch-note-file>`로 이어받을 수 있다.
수령자가 정확히 `CONFIRMED` 한 줄로 회신했고 이를 private workspace 파일로 보관했다면 `--recipient-ack-private-file <private-ack-file>`을 사용할 수 있다. first-recipient sequence는 다른 ACK 문장을 `unconfirmed`로 유지한다. 이 입력 파일들의 내용과 경로는 장부에 저장하지 않고 sha256만 기록한다.

recipient-checkpoint JSON 단독 확인:

```bash
python scripts/check_external_alpha_recipient_checkpoint.py --verify-recipient-checkpoint cambrian-agent-platform-external-alpha-recipient-checkpoint.json
```

첫 외부 파일럿 결과 검토 대기 판정:

```bash
python scripts/check_external_alpha_pilot_review.py
```

이 판정은 실제 첫 사용자 증거가 오기 전에는 `WAITING_FOR_EVIDENCE`만 기록한다.
성공률, proof claim, sale ready, 시장 검증, 성능 개선 주장은 금지하고, feedback/intake/receipt/diagnostics가 모이기 전에는 continue/fix/stop 결정을 내리지 않는다.
수신자 식별자, 발송 운영 노트, 수령자 확인 원문, Builder Golden Path share receipt를 보관했다면 `--recipient-private-file`, `--operator-dispatch-note-private-file`, `--recipient-ack-private-file`, `--builder-gold-path-share-receipt`로 recipient-checkpoint까지 이어받을 수 있다.

pilot-review JSON 단독 확인:

```bash
python scripts/check_external_alpha_pilot_review.py --verify-pilot-review cambrian-agent-platform-external-alpha-pilot-review.json
```

첫 외부 파일럿 증거 패킷 생성:

```bash
python scripts/check_external_alpha_pilot_evidence.py
```

이 판정은 공유 가능한 receipt/diagnostics, private feedback/intake 해시, 통제된 pilot learning 태그만 기록한다.
완료된 feedback과 issue intake 원문은 private workspace에만 두고, 공개 저장소나 지원 요청에는 넣지 않는다.
운영 결정을 내리려면 `--outcome-tag`가 `not_collected`가 아니어야 하며, 마찰 지점과 부족한 기능은 `--friction-tag`, `--missing-skill-tag`의 허용된 태그로만 기록한다. 사용자 원문, 인용문, 자유 서술은 판정서에 넣지 않는다.
수신자 식별자, 발송 운영 노트, 수령자 확인 원문, Builder Golden Path share receipt도 `--recipient-private-file`, `--operator-dispatch-note-private-file`, `--recipient-ack-private-file`, `--builder-gold-path-share-receipt`로 pilot-review까지 이어받을 수 있다.
완료된 feedback과 issue intake 원문을 private workspace 파일로 보관했다면 `--feedback-private-file <private-feedback-file>`과 `--issue-intake-private-file <private-issue-file>`을 사용할 수 있다. 이 입력 파일들의 내용과 경로는 판정서에 저장하지 않고 sha256만 기록한다.
private feedback 해시, 통제된 pilot learning 태그, 운영 판단이 모두 있어야만 `READY_FOR_DECISION`이 되며, 그 전에는 `NO_DECISION` 상태를 유지한다.
성공률, proof claim, sale ready는 이 단계에서도 표시하지 않는다.

pilot-evidence JSON 단독 확인:

```bash
python scripts/check_external_alpha_pilot_evidence.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

```bash
python scripts/check_external_alpha_pilot_evidence.py --verify-pilot-evidence cambrian-agent-platform-external-alpha-pilot-evidence.json
```

첫 외부 파일럿 운영 결정 판정:

```bash
python scripts/check_external_alpha_pilot_decision.py
```

이 판정은 `continue`, `fix_before_next`, `stop_and_redesign` 중 하나의 운영 결정을 기록한다.
결정 기록에는 private feedback 해시, pilot-evidence `READY_FOR_DECISION`, 통제된 pilot learning 태그, 운영 판단 노트 sha256이 모두 필요하다.
pilot learning 태그는 pilot-evidence에서 pilot-decision과 pilot-iteration으로 그대로 이어져야 하며, 원문이나 자유 서술로 확장하지 않는다.
운영 판단 노트 원문을 private workspace 파일로 보관했다면 `--operator-note-private-file <private-decision-note-file>`을 사용할 수 있다. 이 입력 파일의 내용과 경로는 판정서에 저장하지 않고 sha256만 기록한다.
증거가 부족하면 `NO_DECISION`과 `decision_blocked`를 유지한다.
결정이 기록되어도 성공률, proof claim, sale ready, marketplace listing, public proof badge는 계속 막는다.

pilot-decision JSON 단독 확인:

```bash
python scripts/check_external_alpha_pilot_decision.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

```bash
python scripts/check_external_alpha_pilot_decision.py --verify-pilot-decision cambrian-agent-platform-external-alpha-pilot-decision.json
```

파일럿 반복 운영 판정:

```bash
python scripts/check_external_alpha_pilot_iteration.py
```

이 판정은 pilot-decision 이후 다음 운영 단계를 제한한다.
`continue`여도 다음 외부 파일럿은 1명만 허용하고, cohort scaling은 금지한다.
`fix_before_next`는 수정과 전체 게이트 재실행 전까지 다음 발송을 막는다.
`stop_and_redesign`은 외부 발송을 중단하고 product boundary와 메시지 재설계를 요구한다.

pilot-iteration JSON 단독 확인:

```bash
python scripts/check_external_alpha_pilot_iteration.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

```bash
python scripts/check_external_alpha_pilot_iteration.py --verify-pilot-iteration cambrian-agent-platform-external-alpha-pilot-iteration.json
```

Final send-chain audit:

```bash
python scripts/audit_external_alpha_send_chain.py
```

검증 영수증 단독 확인:

```bash
python scripts/verify_external_alpha_release.py --verify-receipt external_alpha_release_verification_receipt.json
```

지원 요청 전에 아래 문서를 먼저 확인한다.

```text
EXTERNAL_ALPHA_SUPPORT_PACKET.md
RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md
```

지원 요청에는 `external_alpha_release_verification_receipt.json`와 `external_alpha_diagnostics.json`만 첨부하고, `.env`, 브라우저 `localStorage`, 사용자 원문 문서, raw AI reply는 공유하지 않는다.

기본 산출물:

```text
dist/cambrian-agent-platform-external-alpha.zip
dist/cambrian-agent-platform-external-alpha.manifest.json
dist/cambrian-agent-platform-external-alpha-handoff.md
dist/cambrian-agent-platform-external-alpha-handoff.json
dist/cambrian-agent-platform-external-alpha-send-ready.md
dist/cambrian-agent-platform-external-alpha-send-ready.json
dist/cambrian-agent-platform-external-alpha-pilot-ready.md
dist/cambrian-agent-platform-external-alpha-pilot-ready.json
dist/cambrian-agent-platform-external-alpha-pilot-dispatch.md
dist/cambrian-agent-platform-external-alpha-dispatch-record.md
dist/cambrian-agent-platform-external-alpha-dispatch-record.json
dist/cambrian-agent-platform-external-alpha-recipient-checkpoint.md
dist/cambrian-agent-platform-external-alpha-recipient-checkpoint.json
dist/cambrian-agent-platform-external-alpha-pilot-review.md
dist/cambrian-agent-platform-external-alpha-pilot-review.json
dist/cambrian-agent-platform-external-alpha-pilot-evidence.md
dist/cambrian-agent-platform-external-alpha-pilot-evidence.json
dist/cambrian-agent-platform-external-alpha-pilot-decision.md
dist/cambrian-agent-platform-external-alpha-pilot-decision.json
dist/cambrian-agent-platform-external-alpha-pilot-iteration.md
dist/cambrian-agent-platform-external-alpha-pilot-iteration.json
dist/cambrian-agent-platform-external-alpha-bundle-smoke-receipt.json
dist/cambrian-agent-platform-external-alpha-private-workspace-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-post-send-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-pilot-learning-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.md
dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
dist/external_alpha_release_verification_receipt.json
```

포함 파일, 제외 파일, 해시 매니페스트 기준은 아래 문서에 고정한다.

```text
docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md
```

확인할 샘플:

```text
web/assets/document-organizer.agent-pack.json
web/assets/document-organizer.promoted.agent-pack.json
web/assets/document-organizer.candidate-promotion-record.json
```

외부 알파의 핵심 경계:

- 브라우저 `localStorage`에만 저장한다.
- 서버, 공개 마켓, Cambrian Runtime으로 전송하지 않는다.
- API key와 secret을 수집하지 않는다.
- proof, 성능, 성공률을 주장하지 않는다.
- promoted private version도 `sale_ready: false`, `proof_claim_allowed: false`, `no_runtime_evidence` 상태를 유지한다.
- promotion audit record는 원문 입력이 아니라 해시와 수동 승격 gate만 저장한다.

## Requirements

- Python 3.11 이상
- `pip`
- Agent Platform 검증용 `jsonschema`
- 로컬 Cambrian 저장소 checkout
- Auth Bug Core validation을 위한 Python + pytest 프로젝트 환경

검증 의존성이 없으면 아래 명령으로 설치합니다.

```bash
python -m pip install -e .
```

## Build wheel

```bash
python -m pip install build
python -m build
```

빌드 산출물은 `dist/` 아래에 생성됩니다.

## Install in fresh environment

새 가상환경을 만들고 wheel을 설치합니다.

```bash
python -m venv .venv-cambrian-rc
.venv-cambrian-rc\Scripts\python -m pip install dist/*.whl
```

Windows가 아닌 환경에서는 venv의 `bin/python`을 사용합니다.

## Run doctor

```bash
cambrian --help
cambrian doctor
cambrian company snapshot --help
```

help 첫 화면은 `pack list`, `pack show auth-bug-core`, `install pack`, `pack activate`, `pack start` 중심이어야 합니다.
`company snapshot` 도움말은 설치된 CLI가 private-safe AI Company snapshot 표면을 포함하는지 확인하는 가벼운 gate입니다.

## Start Auth Bug Core

```bash
cambrian demo create login-bug --out ./auth-bug-demo
cd ./auth-bug-demo
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
cambrian pack start "로그인 에러 수정해"
```

`pack start`는 AI provider를 호출하지 않습니다. 작업 packet과 pack job artifact를 만들고, 사용자가 이미 쓰는 AI에 넘길 내용을 준비합니다.

AI agent, skill 생성/검색/융합, harness engineering, evolve apply, private-safe company snapshot까지의 통합 검증은 소스 저장소에서 아래 smoke로 확인합니다.

```bash
python scripts/smoke_ai_company_gold_path.py
```

## Validate canned AI reply

```bash
cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml
cambrian pack job-validate latest
```

이 RC 검증은 재현성을 위해 canned AI reply fixture를 사용합니다. 실제 provider API key는 필요 없습니다.

## Troubleshooting

### pack catalog not found

wheel에 bundled pack data가 포함되어야 합니다. 아래 파일이 wheel 내부에 있는지 확인합니다.

```text
engine/_data/packs/catalog.yaml
engine/_data/packs/auth-bug-core.cambrian-pack.yaml
```

### auth-bug-core not listed

`cambrian pack list --json`을 실행해 catalog resolver가 어떤 catalog를 사용했는지 확인합니다. 로컬 `./packs/catalog.yaml`이 있으면 bundled catalog보다 우선됩니다.

### fixture file missing

`cambrian demo create login-bug --out ./auth-bug-demo`를 다시 실행하고 아래 파일을 확인합니다.

```text
auth-bug-demo/fixtures/ai_reply_patch_candidate.yaml
```

### job-ingest cannot find latest job

먼저 demo project 안에서 `cambrian pack start "로그인 에러 수정해"`를 실행해야 합니다. `latest`는 현재 프로젝트의 가장 최근 pack job을 가리킵니다.

### doctor fails

`cambrian doctor --json`으로 실패 항목을 확인합니다. RC smoke는 fresh venv에서 이 단계를 먼저 확인합니다.

### command is slow but not failed

fresh wheel build와 venv 설치는 느릴 수 있습니다. 공식 smoke는 각 subprocess에 timeout을 두고, 실패 시 stdout/stderr excerpt를 남깁니다.

## Known limits for this RC

- remote registry 없음
- marketplace 없음
- cloud execution 없음
- public proof export와 sale-ready marketplace listing은 RC 핵심 경로가 아님
- company snapshot은 private-safe refs/hash/proof lineage artifact이며 raw private project data를 내보내지 않음
- 현재 primary lane은 Python + pytest + auth/login bug
- source code 자동 적용은 RC 골든패스에 포함하지 않음

## First Recipient Operator Note Seed

`prepare_external_alpha_first_recipient_send_workspace.py` now pre-seeds `operator-dispatch-note-private.md` when it is missing, empty, or still scaffold text. Replace `<private-send-channel>` with the real private channel before preflight; that unresolved token is intentionally blocked by all send and recording gates.
