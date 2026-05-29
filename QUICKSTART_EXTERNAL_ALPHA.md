# Cambrian External Alpha Quickstart

Use this file first. It is the shortest path for a real external recipient to open Cambrian, verify that the bundle is intact, run the Builder Golden Path, and send only safe support evidence back.

## 1. What This Is

Cambrian External Alpha is a local browser experience for testing agent creation, manual run review, skill/evolution flow, and private audit lineage.

It is not a public marketplace, a paid product, or proof that an AI agent succeeds in production.

## 2. Open Cambrian

On Windows, double-click:

```text
START_CAMBRIAN_AGENT_PLATFORM.bat
```

If that does not open the browser, open this file manually:

```text
web/platform/index.html
```

If you are using Claude or Codex to help you, paste this file into it:

```text
RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md
```

## 3. Verify The Bundle

Run this first before reporting a problem. On Windows it creates or reuses a local `.venv`, installs Cambrian verification dependencies from this extracted folder, and then runs the verifier:

```text
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
```

If you are doing the same steps manually:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe scripts/verify_platform_alpha.py
```

Expected result:

```text
Cambrian Agent Platform alpha verification passed.
```

## 4. Run The Golden Path

In the platform, complete this flow:

```text
Builder draft
-> agent contract
-> Local Runner manual_no_api run
-> manual_run_receipt_v0_1
-> Evolution suggestion
-> candidate preview
-> diff report
-> promoted private version
-> promotion audit record
-> Private Hub lineage
-> lineage verifier pass
-> external_alpha_builder_gold_path_share_receipt.json
```

The goal is to prove that the workflow is understandable and locally runnable, not to claim public performance.

## 5. Send Back Only Safe Files

If the operator asks for evidence, send only these files:

```text
external_alpha_release_verification_receipt.json
external_alpha_diagnostics.json
external_alpha_builder_gold_path_share_receipt.json
```

Only send `external_alpha_diagnostics.json` if it says:

```text
safe_to_share: true
```

Only send the gold path receipt if it says:

```text
safe_to_share: true
proof_claim_allowed: false
success_rate_claim_allowed: false
sale_ready: false
```

## 6. Do Not Send

Do not send:

```text
.env
API keys
browser localStorage
private source code
private project files
raw AI replies
screenshots with private data
download folder paths
```

## 7. If Something Fails

Run:

```text
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

On Windows this also creates or reuses `.venv` and installs the local verification dependencies if needed. If you are doing it manually:

```bash
.venv\Scripts\python.exe scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json
```

Then read:

```text
EXTERNAL_ALPHA_SUPPORT_PACKET.md
```

Send only the safe receipt and diagnostics files listed above.

## 8. Short Confirmation

If everything opens and the Golden Path is clear, a short confirmation is enough:

```text
Confirmed: opened Cambrian and completed the Builder Golden Path.
```
