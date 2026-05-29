# Cambrian 0.3.0

Cambrian is an installable AI company runtime. Every project becomes an AI company.

This release is distributed through the GitHub Release asset `cambrian-install-kit-release-bundle.zip`.

## Install

1. Download `cambrian-install-kit-release-bundle.zip` from this release.
2. Extract the ZIP.
3. From the extracted folder, run:

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project /path/to/project
```

On Windows:

```powershell
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project C:\path\to\project
```

Then run the local gold path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project /path/to/project
```

## What This Verifies

The bundle verifies local install, Cambrian CLI access, `cambrian doctor --json`, AI company snapshot help, the required gold path, and MCP operability evidence.

Share-safe receipts are written by the local install and gold-path runners. Do not share `.env`, API keys, secrets, raw private project data, temporary install paths, or screenshots containing private code or user data.

## Distribution Boundary

PyPI is not the current release lane. Do not use `pip install cambrian` unless a later PyPI release explicitly says that fresh PyPI install verification has passed.

Cambrian does not run unsupervised, patch source code automatically, deploy, charge payments, read secrets, or bypass operator approval.
