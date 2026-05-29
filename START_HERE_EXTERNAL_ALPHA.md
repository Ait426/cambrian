# Cambrian Agent Platform External Alpha

Start with `QUICKSTART_EXTERNAL_ALPHA.md` if you are the recipient. This file is the deeper manual for operators, support helpers, and recipients who want to understand the full path.

## What This Bundle Is

Cambrian External Alpha is a local browser bundle for testing:

- agent contract creation
- manual no-API runner review
- skill and evolution flow
- candidate preview and diff report
- promoted private version
- promotion audit record
- Private Hub lineage
- share-safe gold path receipt generation

This is a Defensible Alpha, not a public marketplace, a paid product, a production success claim, or proof that any AI agent succeeds in the real world.

## First 5 Minutes

1. Open `QUICKSTART_EXTERNAL_ALPHA.md`.
2. Run `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat`. It creates or reuses `.venv`, installs the local verification dependencies, and runs the verifier.
3. Open Cambrian with `START_CAMBRIAN_AGENT_PLATFORM.bat`.
4. If the batch file cannot open a browser, open `web/platform/index.html`.
5. If you want Codex or Claude to help, paste `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md` into that assistant.

Expected verifier output:

```text
Cambrian Agent Platform alpha verification passed.
```

## Builder Golden Path

Run the product through this path:

```text
Builder draft
-> agent contract
-> Local Runner manual_no_api run
-> manual_run_receipt_v0_1
-> manual_review_only metadata boundary
-> Evolution suggestion
-> candidate preview
-> diff report
-> promoted private version
-> promotion audit record
-> Private Hub lineage
-> lineage verifier pass
-> external_alpha_builder_gold_path_share_receipt.json
```

The receipt is only a private alpha evidence artifact. It must keep:

```text
safe_to_share: true
proof_claim_allowed: false
success_rate_claim_allowed: false
sale_ready: false
```

## Promotion Audit Checks

Use these sample artifacts if you need a deterministic lineage check:

```text
web/assets/document-organizer.promoted.agent-pack.json
web/assets/document-organizer.candidate-promotion-record.json
```

The lineage verifier should report the promoted private version as verified only when the promotion audit fingerprint matches. If the lineage card is tampered with, malformed, not an object, privacy unsafe, or making proof/success/sale claims, the verifier should fail without changing Hub storage, promotion audit storage, or Runner handoff state.

When a verified private Hub version is run again, the handoff kind should be `private_download_hub_to_manual_runner`.

## Verification Commands

Core local verification:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe scripts/verify_platform_alpha.py
.venv\Scripts\python.exe scripts/verify_external_alpha_release.py
.venv\Scripts\python.exe scripts/smoke_external_alpha_release_bundle.py
```

Optional browser smoke:

```bash
npm install --prefix C:\tmp\cambrian-playwright-deps playwright
python scripts/verify_agent_platform_browser_flow.py --node-modules C:\tmp\cambrian-playwright-deps\node_modules --single
```

Release and operator gates:

```bash
python scripts/build_external_alpha_release.py
python scripts/prepare_external_alpha_handoff.py
python scripts/check_external_alpha_send_ready.py
python scripts/check_external_alpha_pilot_ready.py
python scripts/check_external_alpha_dispatch_record.py
python scripts/check_external_alpha_recipient_checkpoint.py
python scripts/check_external_alpha_pilot_review.py
python scripts/check_external_alpha_pilot_evidence.py
python scripts/check_external_alpha_pilot_decision.py
python scripts/check_external_alpha_pilot_iteration.py
python scripts/audit_external_alpha_send_chain.py
python scripts/audit_external_alpha_operator_send_bypass.py
python scripts/prepare_external_alpha_operator_dispatch_packet.py
```

First-recipient private operator gates:

```bash
python scripts/prepare_external_alpha_private_pilot_workspace.py --workspace-dir <private-workspace-dir>
python scripts/prepare_external_alpha_first_recipient_send_workspace.py
python scripts/check_external_alpha_first_recipient_operator_status.py
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>
```

If operator status says `CHECK_RELEASE_CHAIN`, run `python scripts/audit_external_alpha_send_chain.py` and resolve the controlled check IDs, such as `release_sources_match_current_manifest`, before any manual send.

## First-Recipient Send Rule

Scripts do not send files or messages to a recipient. The operator manually sends exactly one ZIP to exactly one recipient.

The recipient should receive:

```text
cambrian-agent-platform-external-alpha.zip
QUICKSTART_EXTERNAL_ALPHA.md guidance
RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md if using Codex or Claude
```

Ask for only this short acknowledgement after they open and verify the bundle:

```text
CONFIRMED
```

Do not ask for raw screenshots, browser localStorage, private project files, API keys, `.env`, raw AI replies, or private source code.

## Support Packet

If something fails, ask the recipient to read:

```text
EXTERNAL_ALPHA_SUPPORT_PACKET.md
```

They can collect diagnostics with:

```text
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

The Windows diagnostics batch creates or reuses `.venv` and installs local verification dependencies if needed. Manual equivalent:

```bash
.venv\Scripts\python.exe scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json
```

The only normal share-safe evidence files are:

```text
external_alpha_release_verification_receipt.json
external_alpha_diagnostics.json
external_alpha_builder_gold_path_share_receipt.json
```

Only accept `external_alpha_diagnostics.json` when `safe_to_share` is true and every `redaction_checks` value is true.

## Private Evidence Rule

Real recipient names, send channels, acknowledgements, feedback, issue reports, and decision notes stay in the private workspace. Public or share-safe records store only controlled booleans, tags, and sha256 hashes.

Use `--private-workspace-dir <private-workspace-dir>` whenever a gate supports it. Do not pass raw recipient, channel, acknowledgement, feedback, issue, or decision text as CLI arguments.

## Boundary

This alpha validates whether the local workflow is understandable and auditable. It does not prove performance, does not make public proof claims, does not imply marketplace readiness, and does not allow cohort scaling before the first controlled pilot evidence is reviewed.
