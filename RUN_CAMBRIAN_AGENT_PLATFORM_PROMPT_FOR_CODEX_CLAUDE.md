# Cambrian Agent Platform Prompt For Codex/Claude

You are working inside the extracted `cambrian-agent-platform-external-alpha` folder.

Goal: help the recipient verify and run the Cambrian Agent Platform External Alpha without collecting secrets, private source, browser localStorage, screenshots, raw AI replies, or private project data.

Follow this local bundle contract:

1. Read `QUICKSTART_EXTERNAL_ALPHA.md` first. Use `START_HERE_EXTERNAL_ALPHA.md` only when deeper manual detail is needed.

2. Verify the bundle locally:

On Windows, run the batch file first. It creates or reuses `.venv`, installs the local Cambrian verification dependencies, and runs the verifier:

```text
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
```

Manual equivalent:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe scripts/verify_platform_alpha.py
```

3. Start the local browser experience:

```text
START_CAMBRIAN_AGENT_PLATFORM.bat
```

If the batch file cannot be used, open:

```text
web/platform/index.html
```

4. Walk the recipient through the Builder Golden Path:

```text
agent contract
-> manual_no_api runner
-> manual_run_receipt_v0_1
-> evolution suggestion
-> candidate preview
-> diff report
-> promoted private version
-> promotion audit record
-> private hub lineage
-> lineage verifier report
-> external_alpha_builder_gold_path_share_receipt.json
```

The share-safe gold path receipt must keep:

```text
safe_to_share: true
proof_claim_allowed: false
success_rate_claim_allowed: false
sale_ready: false
```

5. If anything fails, collect only share-safe support files:

```bash
.venv\Scripts\python.exe scripts/verify_external_alpha_release.py --receipt external_alpha_release_verification_receipt.json
.venv\Scripts\python.exe scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json
```

Windows alternatives:

```text
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

6. Ask the recipient to reply only with this short acknowledgement:

```text
CONFIRMED
```

Do not ask for API keys, `.env`, browser localStorage, raw private project data, raw AI replies, private source code, screenshots with sensitive information, public proof claims, success-rate claims, or sale-ready claims.

Share only:

```text
external_alpha_release_verification_receipt.json
external_alpha_diagnostics.json
external_alpha_builder_gold_path_share_receipt.json
```

Treat this as a defensible alpha, not a public marketplace, not a paid product, and not proof of production success.
