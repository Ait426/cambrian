# Cloudflare Pages Token Runbook

Purpose: give Cambrian one temporary shell credential path for launching the public download site through Cloudflare Pages direct upload.

Do not write real token values into this repository. `.env`, `.env.*`, and `.cambrian/` are ignored, but the safest release path is still a temporary shell environment variable.

## Required Cloudflare Credentials

This launch path requires both shell values:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

Create a Cloudflare API token from the dashboard with:

- Permission group: `Account`
- Permission: `Cloudflare Pages`
- Access: `Edit`
- Account resources: include the target Cloudflare account

Short permission label used by Cambrian receipts: `Account / Cloudflare Pages / Edit`.

Cloudflare's Pages API documentation also names `Pages Write` as the write-capable token permission for Pages operations. The direct-upload CI documentation shows `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` as the credentials Wrangler uses for Pages deploys, so Cambrian treats both as required for deterministic non-interactive direct upload.

Official references:

- `https://developers.cloudflare.com/pages/configuration/api/`
- `https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/`
- `https://developers.cloudflare.com/workers/wrangler/system-environment-variables/`

## Temporary PowerShell Setup

Set credentials only in the current shell:

```powershell
$env:CLOUDFLARE_API_TOKEN = "<cloudflare-pages-edit-token>"
$env:CLOUDFLARE_ACCOUNT_ID = "<cloudflare-account-id>"
```

First run the credential-only check:

```powershell
python scripts\check_external_alpha_cloudflare_credentials.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json
```

Expected credential success:

```text
verdict: CLOUDFLARE_CREDENTIALS_READY
missing: none
```

Then run the guarded launch sequence:

```powershell
python scripts\run_external_alpha_public_launch_sequence.py --receipt dist\cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json
```

The sequence runs the credential gate first and will not deploy until credentials are ready.

You can also run the guarded launch command directly after credential success:

```powershell
python scripts\launch_external_alpha_cloudflare_pages.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json
```

Expected success:

```text
verdict: CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY
share  : True
```

Expected blocked states:

```text
BLOCKED_API_TOKEN_REQUIRED          -> CLOUDFLARE_API_TOKEN is missing.
BLOCKED_ACCOUNT_ID_REQUIRED         -> CLOUDFLARE_ACCOUNT_ID is missing.
BLOCKED_PREFLIGHT_NOT_READY         -> the deploy preflight did not return READY_TO_DEPLOY_WITH_WRANGLER.
BLOCKED_PROJECT_CHECK_FAILED        -> Wrangler could not list Pages projects.
BLOCKED_PROJECT_CREATE_FAILED       -> Wrangler could not create the cambrian-alpha Pages project.
BLOCKED_DEPLOY_FAILED               -> Wrangler Pages deploy failed.
BLOCKED_DEPLOY_PUBLIC_URL_NOT_FOUND -> deploy output did not include an https://*.pages.dev URL.
BLOCKED_PUBLIC_URL_GATE_FAILED      -> hosted URL failed the final downloaded-ZIP gate.
```

## Cleanup

After the launch run, clear the credentials from the current shell:

```powershell
Remove-Item Env:\CLOUDFLARE_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:\CLOUDFLARE_ACCOUNT_ID -ErrorAction SilentlyContinue
```

## Share Boundary

Do not share the public URL until the launch receipt says:

```text
verdict: CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY
external_sharing_allowed: true
```
