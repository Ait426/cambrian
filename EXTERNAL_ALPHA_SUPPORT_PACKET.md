# External Alpha Support Packet

Use this packet only when something fails or the operator asks for share-safe evidence. If you are the recipient and nothing has failed, start with `QUICKSTART_EXTERNAL_ALPHA.md` instead.

## Purpose

This packet keeps support evidence small, private-safe, and repeatable. It tells the recipient what to send, what not to send, and how support should triage the result.

## Send These Files

Create the support files with:

```bash
python scripts/verify_external_alpha_release.py --receipt external_alpha_release_verification_receipt.json
python scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json
```

On Windows, you can also run:

```text
VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat
COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat
```

Send only these share-safe files:

```text
external_alpha_release_verification_receipt.json
external_alpha_diagnostics.json
external_alpha_builder_gold_path_share_receipt.json
```

Only send `external_alpha_diagnostics.json` when:

```text
safe_to_share: true
all redaction_checks: true
```

Only send `external_alpha_builder_gold_path_share_receipt.json` when:

```text
safe_to_share: true
proof_claim_allowed: false
success_rate_claim_allowed: false
sale_ready: false
```

## Do Not Send

Do not send or paste:

```text
.env
API keys
secrets
browser localStorage
private source code
private project files
raw AI replies
raw AI reply text
screenshots with private data
download folder paths
raw pilot feedback with personal or company data
```

## Issue Intake

Use this template for issue reports:

```text
docs/launch/PILOT_ISSUE_INTAKE.md
```

Minimum useful issue evidence:

- which file or command was run
- expected result
- actual result
- `external_alpha_release_verification_receipt.json`
- `external_alpha_diagnostics.json`
- a screenshot only if it contains no private data

## Feedback Form

Use this template for product feedback:

```text
docs/launch/PILOT_FEEDBACK_FORM.md
```

Keep raw feedback in the private workspace. Share-safe pilot records should store controlled tags and sha256 hashes, not raw recipient text, company names, project names, or local paths.

## Support Triage

Support should check this order:

1. Confirm the release receipt archive sha256 matches the delivered ZIP.
2. Confirm every `verified_checks` value in the release receipt is true.
3. Confirm diagnostics has `safe_to_share: true`.
4. Confirm every diagnostics `redaction_checks` value is true.
5. Read `support_summary.next_action`.
6. If required files are missing, ask the recipient to re-extract the ZIP and rerun verification.
7. If platform verification failed, inspect only the sanitized stdout/stderr tails in diagnostics.

## Boundary

This packet is not a production support contract. It exists to test whether the first external alpha user can understand, verify, and run Cambrian without leaking private data or making public proof, success-rate, marketplace, or sale-ready claims.
