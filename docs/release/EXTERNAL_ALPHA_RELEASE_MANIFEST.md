# External Alpha Release Manifest

## Purpose

이 문서는 Cambrian Agent Platform 외부 알파를 사용자에게 전달할 때 포함할 파일, 제외할 파일, 검증 순서를 고정한다.
이 릴리즈는 공개 marketplace나 판매 제품이 아니라 브라우저 기반 Agent Builder, Local Runner, Evolution Review, private promotion audit 흐름을 확인하는 알파 묶음이다.
이 릴리즈는 단순 MVP가 아니라 Defensible Alpha다.
한국 시장 선점 대상은 에이전트 쇼핑몰 UI가 아니라 agent contract, preflight, verified promotion audit lineage, proof boundary 표준이다.

## Release Command

릴리즈 담당자는 저장소 루트에서 아래 명령을 실행한다.

```bash
python scripts/build_external_alpha_release.py
```

생성된 ZIP과 외부 manifest가 서로 맞는지 수령자 관점에서 다시 검증하려면 아래 명령을 실행한다.

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

Pre-send private workspace gate:

```bash
python scripts/check_external_alpha_first_recipient_send_preflight.py --workspace-dir <private-workspace-dir> --operator-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
```

First-recipient manual send GO/NO-GO gate:

```bash
python scripts/check_external_alpha_first_recipient_manual_send_go.py --workspace-dir <private-workspace-dir>
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

Read `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md` before setting launch credentials. The guarded public launch sequence writes `dist/cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json`, blocks before deploy unless both `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are present, and only reaches `PUBLIC_LAUNCH_SEQUENCE_READY` after the public HTTPS URL gate and share packet are verified. The upload package is `cambrian-public-site.zip`; the downloadable user artifact remains `cambrian-alpha.zip`.

Browser smoke wrapper gate: the release verifier also runs `scripts/verify_agent_platform_browser_flow.py --help` from the extracted ZIP. A release cannot pass if the optional browser smoke wrapper is missing or its CLI surface is broken, and the success output includes `browser : pass wrapper help`.

Current-source guard: normal sender-side `python scripts/verify_external_alpha_release.py` also compares every current `INCLUDED_FILES` source file against the release manifest by byte count and sha256. This closes the stale-ZIP gap where a ZIP and manifest can be internally consistent but no longer reflect the current codebase. `--skip-current-source-check` is reserved for standalone ZIP/manifest checks, and shareable release receipts require `current_sources_match_release_manifest=true`.

이 검증은 ZIP sha256, ZIP 내부 경로, manifest.files의 byte/sha256, bundle manifest, 압축 해제 후 `verify_platform_alpha.py`, `collect_external_alpha_diagnostics.py` 실행과 진단 privacy 플래그, `safe_to_share`, `redaction_checks`, `support_summary`까지 확인한다.
Windows에서는 압축 해제된 폴더 안의 `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat`와 `COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat`도 실제로 실행한다.
성공 출력에는 release version, archive sha256, 파일 수, policy boundary 검증 수, `EXTERNAL_ALPHA_TRUST_REPORT.md` 검증 여부, diagnostics privacy-safe/share-safe 상태, support next action, Windows batch rehearsal 상태가 함께 표시된다.
release manifest와 bundle manifest는 `dispatch_execution_policy`를 포함하며, `script_sends_to_recipient=false`, `script_sends_copy_paste_message=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`를 ZIP 검증 단계에서 고정한다.
공유 가능한 검증 영수증이 필요하면 아래처럼 `--receipt`를 사용한다.

```bash
python scripts/verify_external_alpha_release.py --receipt external_alpha_release_verification_receipt.json
```

영수증 파일만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/verify_external_alpha_release.py --verify-receipt external_alpha_release_verification_receipt.json
```

The shareable receipt records this as `browser_smoke_wrapper_checked` and includes a privacy-safe `browser_wrapper` section with no local paths. `generated_at` is retained for operator context, but it is excluded from `receipt_body_sha256` so repeated receipt generation does not stale the handoff hash chain.

이 영수증은 `external_alpha_release_verification_receipt_v0_1` 스키마를 사용하며, 로컬 절대경로와 secret 없이 release hash, policy boundary 수, diagnostics safe-to-share 상태, support next action만 담는다.
또한 `verified_checks`에 archive hash, manifest file hash, bundle manifest policy, trust report, release boundary, forbidden path exclusion, diagnostics privacy/share safety 검증 여부를 남기고, `receipt_body_sha256`과 `receipt_checks`로 영수증 본문 해시와 공유 안전성을 확인한다.

외부 사용자에게 보낼 전달문과 운영 체크리스트는 아래 명령으로 생성한다.

```bash
python scripts/prepare_external_alpha_handoff.py
```

handoff JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/prepare_external_alpha_handoff.py --verify-handoff cambrian-agent-platform-external-alpha-handoff.json
```

생성되는 handoff 산출물:

```text
dist/cambrian-agent-platform-external-alpha-handoff.md
dist/cambrian-agent-platform-external-alpha-handoff.json
dist/external_alpha_release_verification_receipt.json
```

handoff 산출물은 로컬 절대경로와 secret 없이 ZIP 파일명, archive sha256, receipt body sha256, handoff body sha256, recipient steps, support files, do-not-share 항목, pilot intake/feedback 템플릿만 담는다.
handoff도 verified release의 `dispatch_execution_policy`를 이어받아 운영자가 수동으로 1명에게만 발송해야 하며 스크립트가 ZIP이나 copy-paste message를 직접 보내지 않는다는 점을 검증한다.
handoff 생성 과정은 `external_alpha_release_verification_receipt.json`을 만들고 `--verify-receipt` 기준으로 단독 검증한다.
handoff JSON은 `handoff_body_sha256`과 `handoff_checks`로 본문 해시와 공유 안전성을 자체 검증한다.

발송 직전 최종 GO/NO-GO 판정서는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_send_ready.py
```

send-ready JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_send_ready.py --verify-send-ready cambrian-agent-platform-external-alpha-send-ready.json
```

생성되는 send-ready 산출물:

```text
dist/cambrian-agent-platform-external-alpha-send-ready.md
dist/cambrian-agent-platform-external-alpha-send-ready.json
```

send-ready 산출물은 handoff 단독 검증, receipt 단독 검증, handoff가 기록한 receipt body sha256과 현재 receipt body sha256의 일치, diagnostics privacy, copy-paste message, do-not-share guardrail이 모두 맞을 때만 `verdict: GO`를 기록한다.
send-ready도 handoff의 `dispatch_execution_policy`를 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지될 때만 `GO`를 허용한다.
copy-paste message는 `QUICKSTART_EXTERNAL_ALPHA.md`를 첫 진입점으로 안내하고 실행 경로 확인 후 정확히 `CONFIRMED` 한 줄로만 회신하라는 요청, Claude/Codex 위임용 `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md` 안내, 스크린샷 원문 금지 문구를 포함해야 한다.
판정서에는 send-ready body sha256, handoff body sha256, receipt body sha256, `handoff_receipt_body_matches_current_receipt`, standalone verification 상태가 함께 남는다.
send-ready JSON은 `send_ready_body_sha256`과 `send_ready_checks`로 본문 해시와 공유 안전성을 자체 검증한다.
또한 `artifact_chain`에 release ZIP, handoff JSON, receipt JSON, send-ready JSON의 파일명과 sha256을 순서대로 남겨 최종 발송 증거가 서로 연결되어 있음을 확인한다.

첫 외부 파일럿 운영 GO/NO-GO 판정서는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_pilot_ready.py
```

pilot-ready JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_pilot_ready.py --verify-pilot-ready cambrian-agent-platform-external-alpha-pilot-ready.json
```

생성되는 pilot-ready 산출물:

```text
dist/cambrian-agent-platform-external-alpha-pilot-ready.md
dist/cambrian-agent-platform-external-alpha-pilot-ready.json
dist/cambrian-agent-platform-external-alpha-pilot-dispatch.md
```

pilot-ready 산출물은 send-ready GO, receipt 단독 검증, pilot intake/feedback 개인정보 보호 문구, support do-not-share guardrail, 첫 파일럿 성공/수정/중단 기준이 모두 맞을 때만 `verdict: GO`를 기록한다.
pilot-ready도 send-ready의 `dispatch_execution_policy`를 최상위 필드로 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
판정서에는 pilot-ready body sha256, send-ready body sha256, receipt body sha256, 파일럿 성공 기준, stop-and-redesign 기준이 함께 남는다.
pilot-ready JSON은 `pilot_ready_body_sha256`과 `pilot_ready_checks`로 본문 해시와 공유 안전성을 자체 검증한다.
pilot-dispatch Markdown은 첫 사용자 1명에게 보낼 copy-paste message, 10분 timebox, 수령자 체크리스트, 회수할 feedback/intake/receipt/diagnostics 파일, stop-and-redesign 기준을 한 장으로 묶는다.
pilot-dispatch copy-paste message도 수령자에게 `QUICKSTART_EXTERNAL_ALPHA.md`를 먼저 읽게 하고 짧은 확인 회신만 요청하며, Claude/Codex 위임 시 `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`를 붙여넣게 하고, 사용자 원문과 스크린샷 원문을 받지 않도록 고정한다.
pilot-dispatch의 `execution_policy`는 스크립트가 직접 발송하지 않고 운영자가 수동으로 1명에게만 보내야 한다는 점을 먼저 보여준다. `script_sends_to_recipient`와 `script_sends_copy_paste_message`는 `false`, `manual_operator_dispatch_required`는 `true`, `max_recipients_per_pilot`은 `1`, `records_private_sha256_only_after_send`는 `true`여야 한다.
또한 send-ready의 `artifact_chain`을 이어받아 release ZIP, handoff JSON, receipt JSON, send-ready JSON, pilot-ready JSON의 파일명과 sha256이 한 줄의 파일럿 증거 체인으로 이어지는지 확인한다.

첫 외부 파일럿 발송 기록 장부는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_dispatch_record.py
```

dispatch-record JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_dispatch_record.py --verify-dispatch-record cambrian-agent-platform-external-alpha-dispatch-record.json
```

dispatch-record requires the recipient-style bundle smoke receipt to PASS and match the current ZIP sha256 before `READY_TO_SEND_ONE`.

생성되는 dispatch-record 산출물:

```text
dist/cambrian-agent-platform-external-alpha-dispatch-record.md
dist/cambrian-agent-platform-external-alpha-dispatch-record.json
```

dispatch-record 산출물은 첫 사용자 1명 발송만 허용하고 cohort scaling, marketplace listing, success/proof/sale ready 주장을 막는다.
수신자 원문과 발송 메시지 원문은 공개 산출물에 넣지 않고, 실제 발송 후 기록도 private sha256과 UTC 시각만 남긴다.
`dispatch_execution_policy`는 스크립트가 수령자에게 ZIP이나 copy-paste message를 직접 보내지 않는다는 점을 고정한다. `script_sends_to_recipient`와 `script_sends_copy_paste_message`는 항상 `false`, `manual_operator_dispatch_required`는 항상 `true`, `max_recipients_per_record`는 `1`, `records_private_sha256_only`는 `true`여야 한다.
dispatch-record는 pilot-ready의 최상위 `dispatch_execution_policy` 스냅샷을 함께 보관하고, 실제 발송 기록 여부를 뜻하는 `sent_recorded_by_private_hashes_only`만 현재 장부 상태에 맞게 파생한다.
copy-paste message가 ZIP 파일명, sha256, `QUICKSTART_EXTERNAL_ALPHA.md`, `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`, 짧은 회신 요청, 스크린샷 원문 금지 문구를 유지하는지도 `copy_paste_message_policy`로 고정한다.
수신자 식별자와 운영 노트 원문을 private workspace 파일로 보관했다면 `--recipient-private-file <private-recipient-file>`과 `--operator-dispatch-note-private-file <private-dispatch-note-file>`을 사용할 수 있다. 이 입력 파일들의 내용과 경로는 산출물에 저장하지 않고 sha256만 기록한다.
또한 pilot-ready의 `artifact_chain`을 이어받아 release ZIP, handoff JSON, receipt JSON, send-ready JSON, pilot-ready JSON, dispatch-record JSON의 파일명과 sha256이 한 줄의 발송 증거 체인으로 이어지는지 확인한다.

수령자 시작 확인 장부는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_recipient_checkpoint.py
```

recipient-checkpoint JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_recipient_checkpoint.py --verify-recipient-checkpoint cambrian-agent-platform-external-alpha-recipient-checkpoint.json
```

생성되는 recipient-checkpoint 산출물:

```text
dist/cambrian-agent-platform-external-alpha-recipient-checkpoint.md
dist/cambrian-agent-platform-external-alpha-recipient-checkpoint.json
```

recipient-checkpoint 산출물은 수령자가 QUICKSTART_EXTERNAL_ALPHA.md와 검증 경로를 확인했는지 원문 없이 기록한다.
확인 전에는 `WAITING_FOR_RECIPIENT`를 유지하고, 확인 후에도 recipient acknowledgement raw text 대신 private sha256만 남긴다.
수령자가 Builder Golden Path까지 완료했고 플랫폼의 `gold path receipt 다운로드`로 받은 share-safe `external_alpha_builder_gold_path_share_receipt.json`을 보냈다면 `--builder-gold-path-share-receipt`로 함께 기록할 수 있다. 이 경우 `RECIPIENT_GOLD_PATH_CONFIRMED` verdict가 가능하지만, success rate/proof claim/sale ready는 계속 금지한다.
recipient-checkpoint도 dispatch-record의 `dispatch_execution_policy`를 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
수신자 식별자와 발송 운영 노트 원문 파일도 `--recipient-private-file <private-recipient-file>`과 `--operator-dispatch-note-private-file <private-dispatch-note-file>`로 이어받을 수 있다.
수령자가 정확히 `CONFIRMED` 한 줄로 회신했고 이를 private workspace 파일로 보관했다면 `--recipient-ack-private-file <private-ack-file>`을 사용할 수 있다. first-recipient sequence는 다른 ACK 문장을 `unconfirmed`로 유지한다. 이 입력 파일들의 내용과 경로는 산출물에 저장하지 않고 sha256만 기록한다.
또한 dispatch-record의 `artifact_chain`을 이어받아 release ZIP, handoff JSON, receipt JSON, send-ready JSON, pilot-ready JSON, dispatch-record JSON, recipient-checkpoint JSON의 파일명과 sha256이 한 줄의 시작 확인 증거 체인으로 이어지는지 확인한다.

첫 외부 파일럿 결과 검토 대기 판정서는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_pilot_review.py
```

pilot-review JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_pilot_review.py --verify-pilot-review cambrian-agent-platform-external-alpha-pilot-review.json
```

생성되는 pilot-review 산출물:

```text
dist/cambrian-agent-platform-external-alpha-pilot-review.md
dist/cambrian-agent-platform-external-alpha-pilot-review.json
```

pilot-review 산출물은 실제 첫 사용자 증거가 오기 전에는 `WAITING_FOR_EVIDENCE`만 기록한다.
성공률, proof claim, sale ready, 시장 검증, 성능 개선 주장은 금지하고, feedback/intake/receipt/diagnostics가 모이기 전에는 continue/fix/stop 결정을 내리지 않는다.
pilot-review도 recipient-checkpoint의 `dispatch_execution_policy`를 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
수신자 식별자, 발송 운영 노트, 수령자 확인 원문, Builder Golden Path share receipt를 보관했다면 `--recipient-private-file`, `--operator-dispatch-note-private-file`, `--recipient-ack-private-file`, `--builder-gold-path-share-receipt`로 recipient-checkpoint까지 이어받을 수 있다.
또한 recipient-checkpoint의 `artifact_chain`을 이어받아 release ZIP, handoff JSON, receipt JSON, send-ready JSON, pilot-ready JSON, dispatch-record JSON, recipient-checkpoint JSON, pilot-review JSON의 파일명과 sha256이 한 줄의 검토 증거 체인으로 이어지는지 확인한다.

첫 외부 파일럿 증거 패킷은 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_pilot_review.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>
```

```bash
python scripts/check_external_alpha_pilot_evidence.py
```

pilot-evidence JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_pilot_evidence.py --verify-pilot-evidence cambrian-agent-platform-external-alpha-pilot-evidence.json
```

생성되는 pilot-evidence 산출물:

```text
dist/cambrian-agent-platform-external-alpha-pilot-evidence.md
dist/cambrian-agent-platform-external-alpha-pilot-evidence.json
```

pilot-evidence 산출물은 공유 가능한 receipt/diagnostics, private feedback/intake 해시, 통제된 pilot learning 태그만 기록한다.
완료된 feedback과 issue intake 원문은 private workspace에만 두고, 공개 저장소나 지원 요청에는 넣지 않는다.
운영 결정을 내리려면 `--outcome-tag`가 `not_collected`가 아니어야 하며, 마찰 지점과 부족한 기능은 `--friction-tag`, `--missing-skill-tag`의 허용된 태그로만 기록한다. 사용자 원문, 인용문, 자유 서술은 공개 산출물에 넣지 않는다.
pilot-evidence도 pilot-review의 `dispatch_execution_policy`를 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
수신자 식별자, 발송 운영 노트, 수령자 확인 원문, Builder Golden Path share receipt도 `--recipient-private-file`, `--operator-dispatch-note-private-file`, `--recipient-ack-private-file`, `--builder-gold-path-share-receipt`로 pilot-review까지 이어받을 수 있다.
완료된 feedback과 issue intake 원문을 private workspace 파일로 보관했다면 `--feedback-private-file <private-feedback-file>`과 `--issue-intake-private-file <private-issue-file>`을 사용할 수 있다. 이 입력 파일들의 내용과 경로는 산출물에 저장하지 않고 sha256만 기록한다.
private feedback 해시, 통제된 pilot learning 태그, 운영 판단이 모두 있어야만 `READY_FOR_DECISION`이 되며, 그 전에는 `NO_DECISION` 상태를 유지한다.
성공률, proof claim, sale ready는 이 단계에서도 표시하지 않는다.

첫 외부 파일럿 운영 결정 판정서는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_pilot_evidence.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

```bash
python scripts/check_external_alpha_pilot_decision.py
```

pilot-decision JSON만 따로 확인할 때는 아래처럼 실행한다.

```bash
python scripts/check_external_alpha_pilot_decision.py --verify-pilot-decision cambrian-agent-platform-external-alpha-pilot-decision.json
```

생성되는 pilot-decision 산출물:

```text
dist/cambrian-agent-platform-external-alpha-pilot-decision.md
dist/cambrian-agent-platform-external-alpha-pilot-decision.json
```

pilot-decision 산출물은 `continue`, `fix_before_next`, `stop_and_redesign` 중 하나의 운영 결정을 기록한다.
결정 기록에는 private feedback 해시, pilot-evidence `READY_FOR_DECISION`, 통제된 pilot learning 태그, 운영 판단 노트 sha256이 모두 필요하다.
증거가 부족하면 `NO_DECISION`과 `decision_blocked`를 유지한다.
pilot learning 태그는 pilot-evidence에서 pilot-decision과 pilot-iteration으로 그대로 이어져야 하며, 원문이나 자유 서술로 확장하지 않는다.
pilot-decision도 pilot-evidence의 `dispatch_execution_policy`를 이어받아 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
운영 판단 노트 원문은 private workspace에만 두고, 공개 산출물에는 sha256만 남긴다.
운영 판단 노트 원문을 private workspace 파일로 보관했다면 `--operator-note-private-file <private-decision-note-file>`을 사용할 수 있다. 이 입력 파일의 내용과 경로는 산출물에 저장하지 않고 sha256만 기록한다.
결정이 기록되어도 성공률, proof claim, sale ready, marketplace listing, public proof badge는 계속 막는다.

파일럿 반복 운영 판정서는 아래 명령으로 생성한다.

```bash
python scripts/check_external_alpha_pilot_decision.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

```bash
python scripts/check_external_alpha_pilot_iteration.py
```

pilot-iteration JSON만 따로 확인할 때는 아래처럼 실행한다.

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

Operator send bypass audit:

```bash
python scripts/audit_external_alpha_operator_send_bypass.py --workspace-dir <private-workspace-dir>
```

Final send-chain audit requires this receipt before returning `READY_TO_SEND_ONE`; the operator packet builder may use an internal non-final audit path only to avoid circular packet generation.
The operator dispatch packet also names both final commands so the manual sender does not have to discover them from this manifest.

생성되는 pilot-iteration 산출물:

```text
dist/cambrian-agent-platform-external-alpha-pilot-iteration.md
dist/cambrian-agent-platform-external-alpha-pilot-iteration.json
```

pilot-iteration 산출물은 pilot-decision 이후 다음 운영 단계를 제한한다.
`continue`여도 다음 외부 파일럿은 1명만 허용하고, cohort scaling은 금지한다.
`fix_before_next`는 수정과 전체 게이트 재실행 전까지 다음 발송을 막는다.
`stop_and_redesign`은 외부 발송을 중단하고 product boundary와 메시지 재설계를 요구한다.
pilot-iteration도 pilot-decision의 `dispatch_execution_policy`를 이어받아 다음 반복에서도 `script_sends_to_recipient=false`, `manual_operator_dispatch_required=true`, `max_recipients_per_record=1`, `records_private_sha256_only=true`가 유지되는지 단독 검증한다.
이 단계에서도 성공률, proof claim, sale ready, marketplace listing, public proof badge는 계속 막는다.

생성되는 기본 산출물:

```text
dist/cambrian-agent-platform-external-alpha/
dist/cambrian-agent-platform-external-alpha.zip
dist/cambrian-agent-platform-external-alpha.manifest.json
dist/cambrian-agent-platform-external-alpha-bundle-smoke-receipt.json
dist/cambrian-agent-platform-external-alpha-private-workspace-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-post-send-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-pilot-learning-rehearsal-receipt.json
dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.md
dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
dist/cambrian-agent-platform-external-alpha-operator-send-bypass-audit.json
```

ZIP 내부에는 `EXTERNAL_ALPHA_BUNDLE_MANIFEST.json`이 포함되며, 각 포함 파일의 byte 크기와 sha256 해시를 기록한다.
ZIP 내부에는 사람이 먼저 읽을 수 있는 `EXTERNAL_ALPHA_TRUST_REPORT.md`도 포함한다.
자기 자신인 `EXTERNAL_ALPHA_BUNDLE_MANIFEST.json`은 순환 해시를 만들지 않기 위해 self hash를 생략한다.
ZIP 자체 sha256은 ZIP 밖의 `dist/cambrian-agent-platform-external-alpha.manifest.json`에 기록한다.

## Included Surface

외부 알파 묶음은 허용 목록 기반으로만 만들어진다.

포함되는 사용자 시작 파일:

```text
QUICKSTART_EXTERNAL_ALPHA.md
START_HERE_EXTERNAL_ALPHA.md
RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md
EXTERNAL_ALPHA_SUPPORT_PACKET.md
START_CAMBRIAN_AGENT_PLATFORM.bat
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

포함되는 브라우저 화면:

```text
web/index.html
web/platform/index.html
web/runner/index.html
web/evolution/index.html
web/studio/index.html
web/packs/index.html
web/packs/auth-bug-core.html
web/packs/typescript-jest-auth-core.html
```

포함되는 핵심 샘플:

```text
web/assets/document-organizer.agent-pack.json
web/assets/document-organizer.candidate.agent-pack.json
web/assets/document-organizer.candidate-diff-report.json
web/assets/document-organizer.candidate-promotion-record.json
web/assets/document-organizer.evolution-review-decision.json
web/assets/document-organizer.evolution-suggestion.json
web/assets/document-organizer.manual-run-receipt.json
web/assets/document-organizer.promoted.agent-pack.json
```

포함되는 검증 계약:

```text
schemas/agent_contract_v0_1.schema.json
schemas/agent_pack_bundle_v0_1.schema.json
schemas/manual_run_receipt_v0_1.schema.json
schemas/evolution_suggestion_v0_1.schema.json
schemas/evolution_review_decision_v0_1.schema.json
schemas/candidate_diff_report_v0_1.schema.json
schemas/candidate_promotion_record_v0_1.schema.json
scripts/verify_platform_alpha.py
scripts/verify_agent_platform_browser_flow.py
scripts/build_external_alpha_release.py
scripts/verify_external_alpha_release.py
scripts/smoke_external_alpha_release_bundle.py
scripts/smoke_external_alpha_manual_send_go_rehearsal.py
scripts/smoke_external_alpha_post_send_checkpoint.py
scripts/smoke_external_alpha_pilot_learning_loop.py
scripts/smoke_external_alpha_private_pilot_workspace.py
scripts/external_alpha_operator_note_template.py
scripts/prepare_external_alpha_private_pilot_workspace.py
scripts/prepare_external_alpha_first_recipient_send_workspace.py
scripts/check_external_alpha_first_recipient_send_preflight.py
scripts/check_external_alpha_first_recipient_manual_send_go.py
scripts/check_external_alpha_first_recipient_pre_send_sequence.py
scripts/check_external_alpha_first_recipient_post_send_sequence.py
scripts/check_external_alpha_first_recipient_operator_status.py
scripts/prepare_external_alpha_operator_dispatch_packet.py
scripts/prepare_external_alpha_handoff.py
scripts/check_external_alpha_send_ready.py
scripts/check_external_alpha_pilot_ready.py
scripts/check_external_alpha_dispatch_record.py
scripts/check_external_alpha_recipient_checkpoint.py
scripts/check_external_alpha_pilot_review.py
scripts/check_external_alpha_pilot_evidence.py
scripts/check_external_alpha_pilot_decision.py
scripts/check_external_alpha_pilot_iteration.py
scripts/audit_external_alpha_send_chain.py
scripts/audit_external_alpha_operator_send_bypass.py
scripts/collect_external_alpha_diagnostics.py
EXTERNAL_ALPHA_TRUST_REPORT.md
docs/launch/PILOT_ISSUE_INTAKE.md
docs/launch/PILOT_FEEDBACK_FORM.md
tools/validate_agent_pack.py
tools/validate_manual_run_receipt.py
tools/validate_evolution_suggestion.py
tools/validate_evolution_review_decision.py
tools/validate_candidate_diff_report.py
tools/validate_candidate_promotion_record.py
```

## Excluded By Policy

아래 경로와 파일은 외부 알파 ZIP에 포함하지 않는다.

```text
.env
.env.*
.git/
.cambrian/
.pytest_tmp/
.pytest_cache/
__pycache__/
dist/
build/
raw AI replies
local runtime evidence archives
secret or credential files
```

## External Alpha Boundaries

외부 알파는 다음 경계를 넘지 않는다.

- 단순 MVP가 아니라 Defensible Alpha다.
- 한국 시장 선점 대상은 에이전트 쇼핑몰 UI가 아니라 agent contract, preflight, verified promotion audit lineage, proof boundary 표준이다.
- 브라우저 `localStorage` 외 저장소를 만들지 않는다.
- 서버, 공개 마켓, Cambrian Runtime으로 데이터를 전송하지 않는다.
- API key, secret, 비밀번호를 수집하지 않는다.
- proof, 성능, 성공률, 판매 가능 상태를 주장하지 않는다.
- promoted private version도 `sale_ready: false`, `proof_claim_allowed: false`, `no_runtime_evidence` 상태를 유지한다.
- promotion audit record는 원문 입력이 아니라 해시와 수동 승격 gate만 저장한다.
- promotion audit record는 promoted pack 본문 해시까지 맞을 때만 `verified linked`로 인정한다.

`verify_external_alpha_release.py`는 ZIP 해시뿐 아니라 release version, `boundaries`, `forbidden_path_parts`, manifest.files의 byte/sha256, bundle manifest 정책, `EXTERNAL_ALPHA_TRUST_REPORT.md`의 핵심 문구, 진단 리포트 privacy 플래그, `safe_to_share`, `redaction_checks`, `support_summary`도 검증한다.
Windows에서는 외부 사용자가 실제로 누르게 될 `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat`와 `COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat` 실행도 릴리즈 게이트에 포함한다.

## Release Verification

릴리즈 전에 아래 검증을 통과해야 한다.

```bash
python scripts/verify_platform_alpha.py
python scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json
npm install --prefix C:\tmp\cambrian-playwright-deps playwright
python scripts/verify_agent_platform_browser_flow.py --node-modules C:\tmp\cambrian-playwright-deps\node_modules --single
python scripts/build_external_alpha_release.py
python scripts/verify_external_alpha_release.py
python scripts/smoke_external_alpha_release_bundle.py
python scripts/smoke_external_alpha_manual_send_go_rehearsal.py
python scripts/smoke_external_alpha_post_send_checkpoint.py
python scripts/smoke_external_alpha_pilot_learning_loop.py
python scripts/smoke_external_alpha_private_pilot_workspace.py
python scripts/prepare_external_alpha_private_pilot_workspace.py --workspace-dir <private-workspace-dir>
python scripts/prepare_external_alpha_first_recipient_send_workspace.py --workspace-dir <private-workspace-dir> --operator-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
python scripts/check_external_alpha_first_recipient_send_preflight.py --workspace-dir <private-workspace-dir> --operator-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
python scripts/check_external_alpha_first_recipient_manual_send_go.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>
python scripts/prepare_external_alpha_operator_dispatch_packet.py
python scripts/prepare_external_alpha_handoff.py
python scripts/check_external_alpha_send_ready.py
python scripts/check_external_alpha_pilot_ready.py
python scripts/check_external_alpha_dispatch_record.py
python scripts/check_external_alpha_recipient_checkpoint.py
python scripts/check_external_alpha_pilot_review.py
python scripts/check_external_alpha_pilot_evidence.py
python scripts/check_external_alpha_pilot_decision.py
python scripts/check_external_alpha_pilot_iteration.py
python scripts/audit_external_alpha_operator_send_bypass.py --workspace-dir <private-workspace-dir>
python -m pytest -q tests/test_external_alpha_install_surface.py tests/test_external_alpha_release_bundle.py
```

ZIP을 받은 사용자는 압축 해제 후 아래 순서로 확인한다.

```text
1. QUICKSTART_EXTERNAL_ALPHA.md를 먼저 읽는다.
2. START_HERE_EXTERNAL_ALPHA.md는 상세 수동 안내가 필요할 때만 읽는다.
3. Claude/Codex에게 맡길 경우 RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md를 붙여넣는다.
3. START_CAMBRIAN_AGENT_PLATFORM.bat를 실행한다.
4. 필요하면 VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat를 실행한다.
5. 문제가 생기면 EXTERNAL_ALPHA_SUPPORT_PACKET.md를 보고 diagnostics와 receipt만 공유한다.
```

검증 스크립트는 `jsonschema`가 필요하다. 새 Python 환경에서는 저장소 루트에서 아래 명령으로 의존성을 설치할 수 있다.

```bash
python -m pip install -e .
```

브라우저 화면 확인만 할 때는 provider API key, 서버 계정, Cambrian Runtime 설치가 필요 없다.

## First Recipient Operator Note Seed

`prepare_external_alpha_first_recipient_send_workspace.py` seeds `operator-dispatch-note-private.md` with the canonical private operator note template when that file is missing, empty, or still scaffold text. Existing real private notes are preserved. The unresolved `<private-send-channel>` token is intentionally treated as a placeholder by preflight, manual GO, dispatch-record, recipient-checkpoint, post-send, and operator-status gates, so a seeded note never becomes send-ready until the real private channel is filled.
