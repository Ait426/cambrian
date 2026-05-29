# Cambrian GitHub Release Runbook

## Purpose

This runbook is the final operator path for making Cambrian available through GitHub Releases.

The current public distribution lane is the GitHub Release asset `cambrian-install-kit-release-bundle.zip`. PyPI remains deferred until its separate TestPyPI/PyPI install gates pass.

## Current Remote State

Read-only checks on 2026-05-29:

```text
gh repo view Ait426/cambrian --json nameWithOwner,visibility,url,defaultBranchRef,isArchived
```

Result:

```text
repository: Ait426/cambrian
visibility: PUBLIC
default branch: master
archived: false
```

```text
gh release list --repo Ait426/cambrian --limit 10
```

Result:

```text
no GitHub Releases are currently published
```

## Preflight

Run these commands before any push or release creation:

```bash
python scripts/check_github_release_ready.py
python scripts/check_github_release_ready.py --verify-receipt dist/github-release-ready.json
python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json
python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip
python scripts/check_cambrian_install_kit_send_ready.py --verify-send-ready dist/cambrian-install-kit-send-ready.json
```

Required result:

```text
GitHub release-ready verdict: GO
final staging receipt: receipt_all_artifacts_current
release bundle: safe_to_share true
send-ready receipt: GO
```

## Commit Rule

Do not commit the full worktree as one flat change. Follow `docs/release/COMMIT_SLICING_PLAN.md` and commit the seven receipt-locked slices one at a time.

Before each slice commit:

```bash
python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec
python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>
```

Run the slice-specific `test_gate_commands` printed by the commit-ready verifier before committing.

## Push

Only after the reviewed slices are committed locally:

```bash
git push origin master
```

Do not push `.env`, `.cambrian/`, `dist/`, local session handoff notes, raw private project data, or PyPI/TestPyPI tokens.

## Create GitHub Release

Use version `v0.3.0` for the current install-kit release unless the package version changes before release.

```bash
gh release create v0.3.0 dist/cambrian-install-kit-release-bundle.zip \
  --repo Ait426/cambrian \
  --target master \
  --title "Cambrian 0.3.0" \
  --notes-file docs/release/GITHUB_RELEASE_NOTES_0_3_0.md
```

Upload only this asset by default:

```text
dist/cambrian-install-kit-release-bundle.zip
```

Do not upload the entire `dist/` directory.

## Post-Release Verification

After the release exists:

```bash
gh release view v0.3.0 --repo Ait426/cambrian --json tagName,isDraft,isPrerelease,url,assets
```

Required result:

```text
isDraft: false
asset includes: cambrian-install-kit-release-bundle.zip
```

Then verify the asset flow on a clean target project by downloading the release asset, extracting it, and running:

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project /path/to/project
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project /path/to/project
```

Successful local validation writes share-safe receipts:

```text
cambrian_install_share_receipt.json
cambrian_gold_path_share_receipt.json
mcp_operability_receipt.json
```

## Boundary

This runbook does not claim PyPI availability, marketplace readiness, public proof, sale readiness, or first-recipient success. Those require separate receipts.
