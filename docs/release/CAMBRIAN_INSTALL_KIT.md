# Cambrian Install Kit

## Purpose

이 문서는 Cambrian을 다른 PC에서도 간단히 설치할 수 있게 만드는 portable install kit 기준을 고정한다.

목표:

```text
Claude/Codex 또는 사용자가 install kit ZIP 하나만 받아도
프로젝트 폴더에 Cambrian venv를 만들고
cambrian --help, cambrian doctor --json,
cambrian company snapshot --help까지 확인할 수 있어야 한다.
```

## Build

저장소 루트에서 실행한다.

```bash
python scripts/build_cambrian_install_kit.py
```

빌드부터 offline 검증, receipt, handoff, send-ready까지 한 번에 준비하려면 아래 명령을 사용한다.

```bash
python scripts/prepare_cambrian_install_kit_release.py
python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json
```

이미 검증된 ZIP을 재사용해 release receipt만 다시 만들 때는 아래 명령을 사용한다.

```bash
python scripts/prepare_cambrian_install_kit_release.py --skip-build
python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json
```

기본 산출물:

```text
dist/cambrian-install-kit/
dist/cambrian-install-kit-0.3.0.zip
dist/cambrian-install-kit-verification-receipt.json
dist/cambrian-install-kit-handoff.md
dist/cambrian-install-kit-handoff.json
dist/cambrian-install-kit-send-ready.md
dist/cambrian-install-kit-send-ready.json
dist/cambrian-install-kit-dispatch-record.md
dist/cambrian-install-kit-dispatch-record.json
dist/cambrian-install-kit-operator-send-bypass-audit.json
dist/cambrian-install-kit-manual-send-go-rehearsal-receipt.json
dist/cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json
dist/cambrian-install-kit-recipient-checkpoint.md
dist/cambrian-install-kit-recipient-checkpoint.json
<private-workspace-dir>/SEND_CAMBRIAN_INSTALL_KIT_ONE_PRIVATE.md
<private-workspace-dir>/cambrian-install-kit-first-recipient-workspace-receipt.json
<private-workspace-dir>/cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json
<private-workspace-dir>/cambrian-install-kit-first-recipient-post-send-sequence-receipt.json
dist/cambrian-install-kit-release-receipt.json
dist/cambrian-install-kit-release-bundle-smoke-receipt.json
dist/START_HERE_CAMBRIAN_INSTALL_KIT.md
dist/VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py
dist/INSTALL_CAMBRIAN_FROM_BUNDLE.py
dist/RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py
dist/INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md
dist/MCP_EXTERNAL_CLIENT_CONNECT.md
dist/INSTALL_CAMBRIAN_FROM_BUNDLE.bat
dist/install_cambrian_from_bundle.sh
dist/cambrian-install-kit-release-bundle.zip
```

install kit에는 다음이 포함된다.

```text
wheels/cambrian-0.3.0-py3-none-any.whl
install_cambrian.py
INSTALL_CAMBRIAN.ps1
INSTALL_CAMBRIAN.bat
install_cambrian.sh
README_INSTALL_CAMBRIAN.md
INSTALL_PROMPT_FOR_CODEX_CLAUDE.md
CAMBRIAN_INSTALL_KIT_MANIFEST.json
```

## Verify

ZIP 구조와 manifest 해시를 확인한다.

```bash
python scripts/verify_cambrian_install_kit.py
```

ZIP을 임시 폴더에 풀고 실제 설치까지 확인한다.

```bash
python scripts/verify_cambrian_install_kit.py --install-check
```

ZIP 안의 wheelhouse만 사용해 offline 설치까지 확인한다.

```bash
python scripts/verify_cambrian_install_kit.py --install-check --offline
```

외부 공유 가능한 검증 receipt를 남긴다.

```bash
python scripts/verify_cambrian_install_kit.py --install-check --offline --receipt dist/cambrian-install-kit-verification-receipt.json
python scripts/verify_cambrian_install_kit.py --verify-receipt dist/cambrian-install-kit-verification-receipt.json
```

ZIP과 receipt를 수령자 전달용 handoff로 묶는다.

```bash
python scripts/prepare_cambrian_install_kit_handoff.py
python scripts/prepare_cambrian_install_kit_handoff.py --verify-handoff dist/cambrian-install-kit-handoff.json
```

발송 직전 GO/NO-GO를 확인한다.

```bash
python scripts/check_cambrian_install_kit_send_ready.py
python scripts/check_cambrian_install_kit_send_ready.py --verify-send-ready dist/cambrian-install-kit-send-ready.json
python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip
python scripts/smoke_cambrian_install_kit_release_bundle.py --bundle dist/cambrian-install-kit-release-bundle.zip --receipt dist/cambrian-install-kit-release-bundle-smoke-receipt.json
python scripts/smoke_cambrian_install_kit_release_bundle.py --verify-receipt dist/cambrian-install-kit-release-bundle-smoke-receipt.json
```

Sender-side `--verify-release-bundle` is stricter than the recipient's standalone verifier: it verifies the bundle's embedded hash chain and also compares every listed bundle payload against the current prepared `dist` artifacts. A self-consistent but stale release bundle must fail before any operator prepares a first-recipient send.

The handoff and send-ready receipt body hashes exclude `generated_at`, so refreshing the same release chain does not churn downstream dispatch or rehearsal proof hashes.

첫 수령자 1명에게 실제로 보낼 준비/기록 장부를 남긴다.
이 단계는 `dist/cambrian-install-kit-release-bundle-smoke-receipt.json`이 PASS일 때만 통과한다.
또한 smoke receipt 안의 `gold_path_share_receipt.mcp_operability_verified`가 true여야 하며, 이 값은 dispatch-record와 recipient-checkpoint까지 그대로 노출된다.

```bash
python scripts/check_cambrian_install_kit_dispatch_record.py
python scripts/check_cambrian_install_kit_dispatch_record.py --verify-dispatch-record dist/cambrian-install-kit-dispatch-record.json
python scripts/audit_cambrian_install_kit_operator_send_bypass.py
python scripts/audit_cambrian_install_kit_operator_send_bypass.py --verify-receipt dist/cambrian-install-kit-operator-send-bypass-audit.json
python scripts/smoke_cambrian_install_kit_manual_send_go_rehearsal.py
python scripts/smoke_cambrian_install_kit_manual_send_go_rehearsal.py --verify-receipt dist/cambrian-install-kit-manual-send-go-rehearsal-receipt.json
python scripts/smoke_cambrian_install_kit_post_send_checkpoint.py
python scripts/smoke_cambrian_install_kit_post_send_checkpoint.py --verify-receipt dist/cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json
```

실제 발송 후에는 수령자 식별자와 운영 노트 원문을 공개 산출물에 저장하지 않고 private sha256만 기록한다.

```bash
python scripts/check_cambrian_install_kit_dispatch_record.py \
  --recipient-private-file "<private-recipient-file>" \
  --operator-dispatch-note-private-file "<private-dispatch-note-file>" \
  --operator-status-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-ready-receipt.json" \
  --require-operator-status-receipt \
  --manual-send-go-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-manual-send-go-receipt.json" \
  --require-manual-send-go-receipt \
  --sent-at-utc "<real-sent-at-utc>"
```

dispatch-record는 `READY_TO_SEND_ONE` 또는 `SENT_ONE_RECORDED`만 기록하며, cohort scaling, marketplace listing, proof claim, success-rate claim을 계속 막는다. 발송 전 MCP 확인 상태는 `release_bundle_smoke.mcp_operability_verified`로 기록한다.

The dispatch-record and recipient-checkpoint body hashes exclude `generated_at`, so replaying the same waiting state or same private-hash evidence does not stale the proof chain.

Recipient install checkpoint:

```bash
python scripts/check_cambrian_install_kit_recipient_checkpoint.py
python scripts/check_cambrian_install_kit_recipient_checkpoint.py --verify-recipient-checkpoint dist/cambrian-install-kit-recipient-checkpoint.json
```

Before the human sends the bundle to the first real recipient, prepare a local-only private workspace:

```bash
python scripts/prepare_cambrian_install_kit_first_recipient_workspace.py --workspace-dir "<private-workspace-dir>"
python scripts/prepare_cambrian_install_kit_first_recipient_workspace.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-workspace-receipt.json"
python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --workspace-dir "<private-workspace-dir>"
python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-receipt.json"
python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-ready-receipt.json"
python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py --workspace-dir "<private-workspace-dir>"
python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json"
python scripts/check_cambrian_install_kit_first_recipient_manual_send_go.py --workspace-dir "<private-workspace-dir>"
python scripts/check_cambrian_install_kit_first_recipient_manual_send_go.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-manual-send-go-receipt.json"
python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py --workspace-dir "<private-workspace-dir>" --sent-at-utc "<real-sent-at-utc>"
python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py --verify-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-post-send-sequence-receipt.json"
```

The workspace writes placeholder-only private files, `SEND_CAMBRIAN_INSTALL_KIT_ONE_PRIVATE.md`, and a share-safe receipt. The receipt omits absolute paths, recipient/channel text, acknowledgement text, and returned receipt paths. The private runbook tells the operator where to put `recipient-private.txt`, `operator-dispatch-note-private.md`, `recipient-ack-private.txt`, `cambrian_install_share_receipt.json`, `cambrian_gold_path_share_receipt.json`, and `mcp_operability_receipt.json`. It also points the operator to `cambrian-install-kit-first-recipient-operator-status.md`, the human-readable safe status board written by the operator-status command. The operator-dispatch note is seeded with a local-only template containing `private channel: <private-send-channel>` and the current release bundle sha256. The status gate may count the seeded current hash as present, but it still treats the note as a placeholder and blocks manual send until `<private-send-channel>` is replaced with a real private channel. The workspace receipt body hash excludes `generated_at`, so refreshing the same private scaffold does not churn downstream proof hashes.

The operator status receipt is the pre-send GO/NO-GO surface for this private workspace. Its default placeholder state is `FILL_PRIVATE_FIELDS`; it reaches `READY_TO_MANUALLY_SEND_ONE` only when `recipient-private.txt` contains exactly one non-placeholder recipient and `operator-dispatch-note-private.md` names the private channel plus the exact current release bundle sha256. It also runs the sender-side release bundle current-artifact gate; if the ZIP is self-consistent but no longer matches the current `dist` verification receipt, handoff, send-ready, release receipt, install kit ZIP, or generated bundle helper files, the verdict falls back to `PREPARE_RELEASE_BUNDLE` with `open_gates: release_bundle_current_artifacts_match`. When it reaches `READY_TO_MANUALLY_SEND_ONE`, it also writes `cambrian-install-kit-first-recipient-operator-status-ready-receipt.json`. Dispatch and recipient checkpoint commands use this preserved READY receipt, so a later status rerun can safely change the default receipt to `WAITING_FOR_RECIPIENT_RECEIPTS` without destroying the pre-send proof. The CLI prints safe private file statuses and open gate ids, for example `recipient-private.txt=placeholder` and `open_gates: recipient_private_ready, operator_note_names_private_channel, operator_note_confirms_current_release_hash`. It also writes `cambrian-install-kit-first-recipient-operator-status.md`, which mirrors verdict, open gates, private file statuses, release bundle sha256, current-artifact match status, MCP smoke proof, and safe commands for human review, including the post-send recipient checkpoint command that requires the preserved READY receipt and returned MCP proof. The status receipt and board record a controlled command use order from `prepare_workspace` through `record_recipient_checkpoint_after_return`, so copyable commands are not presented as a flat unordered list. The operator status body hash excludes `generated_at`, so rerunning the same blocked state does not stale downstream proof hashes. It records only file names, safe hashes, verdicts, and gate summaries. It does not send, upload, publish, store raw private text, print absolute workspace paths, or mark OS-11 complete.

The pre-send sequence command is the one-command operator surface before a real manual send. It prepares or refreshes the private workspace without overwriting existing private values, runs the operator-status gate, runs the operator send-bypass audit, runs the synthetic manual-send GO rehearsal, and writes `cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json`. It returns `READY_TO_MANUALLY_SEND_ONE` only when the preserved READY operator-status receipt exists and all pre-send checks pass. Its operator-status gate receipt also exposes `release_current_artifacts_checked`, `release_current_artifacts_match`, `release_current_artifacts_gate_passed`, and `release_current_artifacts_status`, so the pre-send receipt itself shows whether the release bundle still matches the current `dist` artifacts. In placeholder state it writes a blocked receipt with controlled file statuses such as `recipient-private.txt=placeholder`, names `cambrian-install-kit-first-recipient-operator-status.md` as the safe status board, and records controlled `human_next_steps` such as "do not send", "fill one recipient", and "replace the private channel". It does not print raw private values or local paths.

The manual-send GO command is the final one-recipient launch decision before the human sends anything. It reruns the pre-send sequence, then writes `cambrian-install-kit-first-recipient-manual-send-go-receipt.json` with `GO_TO_MANUALLY_SEND_ONE` only when the pre-send receipt is READY, the preserved READY operator-status receipt exists, the current-artifact gate passes, the operator send-bypass audit passes, the synthetic manual-send rehearsal passes, and the one-recipient/manual-dispatch policy is still locked. In placeholder or stale-artifact states it writes `BLOCKED_BEFORE_MANUAL_SEND`, points back to the safe operator status board, records controlled blocked check ids, and still does not send, upload, publish, store raw private text, or print local paths.

The post-send sequence command is the one-command operator surface after the human has actually sent the bundle. It requires `--sent-at-utc`; without it, it writes `BLOCKED_AFTER_MANUAL_SEND` and does not record dispatch. The private runbook intentionally uses quoted `"<real-sent-at-utc>"` instead of a generated timestamp, so Bash/PowerShell do not treat the placeholder as redirection if copied before replacement. The dispatch gate rejects placeholders, non-UTC timestamps, stale current `dist` artifacts, READY receipts that no longer match the current release bundle evidence, and missing manual-send GO proof. Replace it only after the manual send actually happened, for example `2026-05-15T10:00:00Z`. With a real UTC timestamp, it records dispatch only through the preserved READY operator-status receipt plus the `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt, then waits for returned share-safe receipts and exactly one `CONFIRMED` acknowledgement. If `cambrian_install_share_receipt.json`, `cambrian_gold_path_share_receipt.json`, and `mcp_operability_receipt.json` are present in `returned-receipts/`, it can close the recipient checkpoint. When a recipient checkpoint is recorded, the post-send sequence receipt mirrors its dispatch copy-paste boundary as share-safe hashes and booleans, never as raw send text. In blocked or waiting states it records controlled `human_next_steps` for timestamp, acknowledgement, and returned receipt follow-up. It stores only receipt filenames, sha256 values, controlled verdicts, current-artifact gate status, and safe summaries.

For the first-recipient path, `SENT_ONE_RECORDED` must be bound to both the latest operator status proof and the final manual-send GO proof. Run dispatch-record with `--operator-status-receipt`, `--require-operator-status-receipt`, `--manual-send-go-receipt`, and `--require-manual-send-go-receipt`; it rejects missing receipts, blocked receipts, stale release hashes, current `dist` artifact mismatches, manual-send GO/operator-status mismatches, or private hash mismatches. This keeps "we sent it" from becoming a self-asserted claim without the pre-send gate and final human-send decision.

The operator send bypass audit checks the release doc, first-recipient workspace script, operator-status script, dispatch-record script, recipient-checkpoint script, post-send sequence script, and local private runbook when present. It passes only when every operator-facing private dispatch command that can record a send also requires `--operator-status-receipt`, `--require-operator-status-receipt`, `--manual-send-go-receipt`, and `--require-manual-send-go-receipt`. The audit receipt is share-safe and does not include raw source text, private workspace paths, recipient/channel values, or send claims.

The manual-send GO rehearsal uses a temporary private workspace with synthetic private values and a fixed synthetic `sent_at_utc` to prove the final path can reach `READY_TO_MANUALLY_SEND_ONE`, write `GO_TO_MANUALLY_SEND_ONE`, and then record a temporary `SENT_ONE_RECORDED` dispatch record with the required operator-status and manual-send GO receipts. The rehearsal receipt is not real send evidence: it sets `real_manual_send=false`, `real_recipient_evidence=false`, stores no raw private values or temp paths, and exists only to catch mechanical launch-chain failures before a human contacts the first real recipient. Its temporary dispatch record carries `synthetic_rehearsal_boundary`; the default dispatch verifier rejects it as standalone send evidence, and the rehearsal verifier requires `synthetic_dispatch_not_standalone_proof` before passing.

The post-send checkpoint rehearsal uses a temporary private workspace with synthetic returned receipts and the same fixed synthetic `sent_at_utc` to prove the recipient checkpoint can close `RECIPIENT_GOLD_PATH_CONFIRMED` only when install, gold-path, MCP, acknowledgement, dispatch hashes, the same `READY_TO_MANUALLY_SEND_ONE` operator-status receipt, and the matching `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt are present. This rehearsal receipt is not real recipient evidence: it sets `real_recipient_evidence=false`, stores no raw private values or temp paths, and exists only to catch mechanical post-send evidence-chain failures before the first real recipient is contacted. Its synthetic recipient checkpoint carries `synthetic_rehearsal_boundary`; the default recipient-checkpoint verifier rejects it as standalone recipient evidence, and the rehearsal verifier requires `synthetic_checkpoint_not_standalone_proof` before passing.

After the one-recipient manual dispatch is actually recorded, the recipient checkpoint can be closed with the share-safe install receipt and private hashes only:

```bash
python scripts/check_cambrian_install_kit_recipient_checkpoint.py \
  --recipient-private-file "<private-recipient-file>" \
  --operator-dispatch-note-private-file "<private-dispatch-note-private-file>" \
  --operator-status-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-operator-status-ready-receipt.json" \
  --require-operator-status-receipt \
  --manual-send-go-receipt "<private-workspace-dir>/cambrian-install-kit-first-recipient-manual-send-go-receipt.json" \
  --require-manual-send-go-receipt \
  --recipient-ack-private-file "<private-recipient-ack-file>" \
  --install-share-receipt "<path/to/cambrian_install_share_receipt.json>" \
  --gold-path-share-receipt "<path/to/cambrian_gold_path_share_receipt.json>" \
  --mcp-operability-receipt "<path/to/mcp_operability_receipt.json>" \
  --sent-at-utc "<real-sent-at-utc>"
```

recipient-checkpoint records only `WAITING_FOR_RECIPIENT`, `RECIPIENT_INSTALL_CONFIRMED`, or `RECIPIENT_GOLD_PATH_CONFIRMED`. Any post-send evidence path that includes private send hashes, acknowledgement, install receipt, gold-path receipt, MCP receipt, or `--sent-at-utc` requires the same `READY_TO_MANUALLY_SEND_ONE` operator status receipt and matching `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt used by dispatch-record, including the current-artifact gate inherited from dispatch-record. Gold path confirmation requires `cambrian_install_share_receipt.json`, `cambrian_gold_path_share_receipt.json`, and a returned `mcp_operability_receipt.json`; without the returned MCP receipt it must stop at install confirmation. The gold path receipt verifies six capabilities: AI agents, skill generate/search/fuse, harness engineering, evolution apply, private-safe company snapshot, and MCP operability. The returned `mcp_operability_receipt.json` is validated as a standalone installed-wheel MCP proof and only its sha256 plus safe summary are stored. The waiting state still records the pre-send MCP proof inherited from dispatch-record, so operators can see that the bundle was MCP-ready before any private recipient response exists. It also preserves the dispatch copy-paste boundary as hashes and booleans, proving the final recipient checkpoint inherited install/gold-path/MCP instructions, local-validation-only evidence, public-proof blocking, and real-human-send first-recipient confirmation. It does not store raw acknowledgement text, local receipt paths, raw MCP receipt paths, private project data, success-rate claims, public proof claims, or sale-ready claims.

The recipient checkpoint receipt also writes a share-safe `blocking_summary` with `missing_evidence`, `required_returned_receipts`, `ack_file`, and controlled `human_next_steps`. In the default waiting state it names `SENT_ONE_RECORDED dispatch record` as the first missing proof and tells the operator to complete the first-recipient pre-send and post-send sequences before claiming recipient evidence. After dispatch is recorded, the same summary shifts to missing acknowledgement and returned receipt files. When `RECIPIENT_GOLD_PATH_CONFIRMED` is reached, the summary closes proof and points to controlled feedback collection before any next recipient.

`--skip-verify` is reserved for synthetic regression tests and trusted local rehearsals where the release artifacts were already verified in the same test fixture. Operator-facing first-recipient commands intentionally omit it so the default launch path remains the full gate.

The returned MCP receipt must prove the installed `cambrian-mcp` entry point: `server_command_mode: installed_entrypoint`, `installed_entrypoint_command: true`, `source_pythonpath_injected: false`, and `no_arbitrary_shell: true`.

## Install On Another PC

가장 단순한 수령자 경로는 `cambrian-install-kit-release-bundle.zip`을 풀고 bundle 루트에서 바로 실행하는 것이다.

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project /path/to/project
```

Windows:

```bat
INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\path\to\project
```

macOS/Linux:

```bash
bash install_cambrian_from_bundle.sh --project /path/to/project
```

Required AI Company Gold Path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project /path/to/project
```

Required MCP external client verification:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Expected MCP receipt:

```text
mcp_operability_verified: true
```

The portable installer itself also runs the MCP verifier and writes `mcp_operability_receipt.json` beside `cambrian_install_receipt.json`. The share-safe `cambrian_install_share_receipt.json` records only the safe MCP summary: `verdict: GO`, `server_command_mode: installed_entrypoint`, `installed_entrypoint_command: true`, `source_pythonpath_injected: false`, `no_arbitrary_shell: true`, and `explicit_cwd_required: true`.

For Codex, Claude, Cursor, or another MCP client, use the installed `cambrian-mcp` command as the stdio MCP server and pass an explicit target project `cwd` to every Cambrian MCP tool call. If the client has trouble with non-ASCII Windows project paths, use an ASCII junction/alias for the client session and rely on Cambrian's `requested_cwd` / `resolved_cwd` fields to keep the evidence clear.

Read `MCP_EXTERNAL_CLIENT_CONNECT.md` before connecting Codex, Claude, or another MCP client. The guide requires the installed `cambrian-mcp` server command, an explicit `cwd`, and no arbitrary shell access through MCP.

This post-install runner verifies the architecture-level product promise from the extracted release bundle: AI agent creation, skill generation/search/fusion, harness engineering, evolution propose/preview/apply, private-safe company snapshot generation, and MCP operability. It writes a local `cambrian_gold_path_receipt.json` and a share-safe `cambrian_gold_path_share_receipt.json`; support requests should share only the share-safe receipt.

이 top-level installer는 기본적으로 `VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`를 먼저 실행한 뒤, 내부 install kit ZIP을 풀고 wheelhouse-only offline 설치를 호출한다.

내부 install kit ZIP만 따로 풀었다면 아래 중 하나를 실행한다.

```bash
python install_cambrian.py --project /path/to/project
```

Windows PowerShell:

```powershell
.\INSTALL_CAMBRIAN.ps1 -Project "C:\path\to\project"
```

Windows cmd:

```bat
INSTALL_CAMBRIAN.bat --project C:\path\to\project
```

macOS/Linux:

```bash
bash install_cambrian.sh --project /path/to/project
```

## Claude/Codex Prompt

release bundle을 Claude 또는 Codex에게 맡길 때는 bundle 최상단의 `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md` 내용을 그대로 붙여넣는다. 내부 install kit 안의 `INSTALL_PROMPT_FOR_CODEX_CLAUDE.md`는 zip을 직접 푼 고급 경로용이고, 외부 수령자 기본 경로는 release bundle prompt다.

핵심 문장:

```text
release bundle 압축을 풀고 python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py를 실행한 다음 python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>를 실행한 뒤 cambrian_install_share_receipt.json을 확인하세요.
그 다음 python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>를 실행하고 cambrian_gold_path_share_receipt.json의 status가 passed인지 확인하세요.
그 다음 MCP_EXTERNAL_CLIENT_CONNECT.md를 읽고 cambrian mcp verify --receipt dist/mcp_operability_receipt.json를 실행해 mcp_operability_verified가 true인지 확인하세요.
지원 요청이 필요하면 로컬 절대경로가 들어 있는 cambrian_install_receipt.json과 cambrian_gold_path_receipt.json 대신 cambrian_install_share_receipt.json과 cambrian_gold_path_share_receipt.json만 공유하세요.
```

## Receipt

설치 성공 시 대상 프로젝트 폴더에 아래 파일이 생긴다.

```text
cambrian_install_receipt.json
cambrian_install_share_receipt.json
cambrian_gold_path_share_receipt.json
```

local receipt는 설치 디버깅을 위해 로컬 절대경로를 기록하므로 그대로 공유하지 않는다.
share receipt는 공유 가능한 설치 상태만 기록한다.

share receipt는 다음을 기록한다.

```text
status: installed
safe_to_share: true
absolute_paths_included: false
cambrian --help: passed
cambrian doctor --json: passed
cambrian company snapshot --help: passed
next_commands:
  project scan
  harness interview start
  skill generate
  company snapshot
```

## Boundary

`RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py` verifies the installed Cambrian venv can create AI agents, generate/search/fuse skills, create the harness engineering system, run evolution propose/preview/apply, write a private-safe company snapshot, and run `cambrian mcp verify --receipt dist/mcp_operability_receipt.json` with the installed `cambrian-mcp` command.

install kit는 Cambrian 명령 설치, doctor 확인, private-safe company snapshot CLI 표면 확인을 보장한다.
검증 receipt는 ZIP 파일명, sha256, PASS 체크, company snapshot capability만 담고 절대경로, secret, raw private project data, 임시 설치 결과 원문은 담지 않는다.
handoff는 ZIP 파일명, ZIP sha256, receipt body sha256, 수령자 설치 절차, copy-paste message, do-not-share guardrail만 담고 수령자에게 자동 발송하지 않는다.
send-ready는 ZIP, receipt, handoff의 artifact chain과 manual dispatch policy가 맞을 때만 `GO`를 기록한다.
dispatch-record는 기존 send-ready와 release bundle smoke receipt가 모두 PASS인 경우에만 첫 수령자 1명 발송 준비 또는 실제 발송 기록을 남긴다. 스크립트는 release bundle 안의 send-ready 체인을 소비하며, 발송하지 않고 수령자 식별자와 운영 노트 원문은 저장하지 않고 sha256만 저장한다. It also preserves a hashed copy-paste message policy proving the operator send text names install, gold path, MCP receipt, local-validation-only evidence, public-proof blocking, and real-human-send first-recipient confirmation.
recipient-checkpoint는 dispatch-record 이후 수령자의 실제 설치 확인을 share-safe `cambrian_install_share_receipt.json`과 private acknowledgement sha256만으로 기록한다. raw acknowledgement, local install receipt path, success/proof/sale-ready claim은 저장하지 않는다.
release receipt는 build, verification receipt, handoff, send-ready가 모두 맞을 때만 `status: pass`를 기록하며, `--verify-release-receipt`로 단독 무결성 검증이 가능해야 한다.
`START_HERE_CAMBRIAN_INSTALL_KIT.md`는 수령자가 처음 열어야 할 파일, verify 명령, required AI Company Gold Path, copy-paste message, do-not-share 경계를 한 장으로 묶는다. It also states that local install, MCP, and gold-path receipts are local validation evidence only, not public proof, sale-ready proof, marketplace proof, success-rate proof, or first-recipient confirmation.
`INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`는 release bundle 최상단에서 Claude/Codex에게 바로 붙여넣는 설치 프롬프트이며, bundle verify -> install -> required AI Company Gold Path -> share-safe receipts 확인까지 한 번에 고정한다. It tells the assisting AI not to claim public proof, sale readiness, marketplace readiness, success rate, or first-recipient confirmation from the local run.
`cambrian-install-kit-handoff.md/json` and `cambrian-install-kit-send-ready.md/json` carry the same claim boundary inside the operator copy-paste message, so the actual send text treats local receipts as validation evidence only and does not imply public proof, sale readiness, marketplace readiness, success rate, or first-recipient confirmation.
The release bundle verifier also requires that handoff/send-ready copy-paste boundary, so a bundle cannot pass with safe recipient docs but unsafe operator send text.
`VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`는 수령자가 소스 저장소 없이 bundle을 푼 폴더에서 실행할 수 있는 독립 검증 스크립트다.
`INSTALL_CAMBRIAN_FROM_BUNDLE.py`는 수령자가 bundle 루트에서 바로 대상 프로젝트에 설치할 수 있는 독립 설치 스크립트이며, `.bat`과 `.sh` wrapper는 같은 경로를 제공한다.
`cambrian-install-kit-release-bundle.zip`은 START_HERE, Claude/Codex top-level prompt, install kit ZIP, verification receipt, handoff, send-ready, release receipt를 한 번에 전달하기 위한 수령자 패킷이다.
bundle 검증은 파일 존재와 manifest 해시뿐 아니라 release receipt, verification receipt, handoff, send-ready, 내부 install kit ZIP manifest의 해시 체인도 확인한다.
bundle smoke는 release bundle ZIP을 실제 수령자처럼 임시 폴더에 풀고, bundle verifier, installer, required AI Company Gold Path runner를 실행한 뒤 share-safe install receipt와 gold path receipt를 검증한다. 이때 MCP operability proof가 true인지 별도 체크로 고정하고, dispatch-record와 recipient-checkpoint가 같은 값을 발송 전 증거로 이어받는다.
AI agent, skill, harness engineering, evolution, company snapshot 생성까지의 전체 골든패스는 소스 저장소에서 아래 명령으로 검증한다.

sender-side bundle verification also compares the current `dist` verification receipt, handoff, send-ready, release receipt, install kit ZIP, and generated bundle helper files against the ZIP payload hashes so stale bundles cannot pass.

```bash
python scripts/smoke_ai_company_gold_path.py
```

설치된 프로젝트에 AI Company evidence가 쌓인 뒤에는 아래 명령으로 raw private data 없이 refs, hashes, proof lineage만 담은 snapshot을 만들 수 있다.

```bash
cambrian company snapshot --json
```

공개 PyPI 배포 전까지는 이 install kit ZIP이 다른 PC 설치의 기준 산출물이다.
