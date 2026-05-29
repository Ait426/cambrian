# Cambrian Dogfood Runbook

## 1. Purpose

Verify that an installed Cambrian RC can run the Auth Bug Core workflow against a real Python + pytest project.

This dogfood is not another fixture smoke test. `examples/auth_bug_demo` is a fixture and must not be used as dogfood PASS evidence.

## 2. Preconditions

- Task 159R-1 PASS.
- Task 159R-2 PASS.
- `python scripts/smoke_installed_wheel.py` PASS.
- A fresh install can list, show, install, activate, and start `auth-bug-core`.

Preflight smoke:

```bash
python scripts/smoke_installed_wheel.py
```

## 3. Target Project Requirements

- Real Python project.
- pytest or an equivalent test command exists.
- Auth/login bug, failing test, or realistic auth/login maintenance task exists.
- A clean git tree is recommended before the run.
- Do not directly edit the original project source during dogfood. Prefer a copy when source protection matters.
- `examples/auth_bug_demo` is not a valid dogfood target.

Target input:

```bash
set CAMBRIAN_DOGFOOD_TARGET=C:\path\to\real-python-pytest-auth-project
```

Or:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\real-python-pytest-auth-project
```

## 4. Install Cambrian RC

Use the local wheel flow from README and `RC_INSTALL_GUIDE.md`.

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
```

## 5. Prepare Target Project

Recommended:

```bash
git status --short
python -m pytest -q
```

If the tree is dirty, record it in the dogfood report. A non-git target may still be used, but source protection evidence is weaker.

## 6. Run Auth Bug Core

```bash
cambrian doctor
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
cambrian pack start "Fix the login error"
```

Automated run:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\target
```

If no AI reply is available, the correct result is `PARTIAL: WAITING_FOR_AI_REPLY`; that is not a failure by itself.

## 7. Capture AI Reply

This RC dogfood does not call an AI provider API automatically.

Allowed flow:

1. `cambrian pack start "Fix the login error" --json > .cambrian/dogfood/job_start.json`
2. Paste the generated packet into the user's existing AI coding tool.
3. Save the AI response as a YAML reply file.
4. Feed the reply back through `cambrian pack job-ingest`.

## 8. Ingest AI Reply

```bash
cambrian pack job-ingest latest ./ai_reply_patch_candidate.yaml --json
```

Scripted run:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\target --ai-reply C:\path\to\ai_reply_patch_candidate.yaml
```

## 9. Validate Job

```bash
cambrian pack job-validate latest --json
```

If validation fails, classify it as one of:

- AI_REPLY_FORMAT_FAILURE
- JOB_INGEST_FAILURE
- JOB_VALIDATE_FAILURE
- VALIDATION_NOT_TRUSTWORTHY
- OUTPUT_NOT_ACTIONABLE

## 10. Evaluate Result

A human operator evaluates:

- Was the next command clear?
- Was the output actionable?
- Did the result identify a useful patch or test direction?
- Was validation trustworthy?
- What was confusing?

## 11. Failure Handling

Failure classes:

- INSTALL_FAILURE
- DOCTOR_FAILURE
- PACK_CATALOG_FAILURE
- PACK_INSTALL_FAILURE
- PACK_ACTIVATE_FAILURE
- PACK_START_FAILURE
- AI_REPLY_FORMAT_FAILURE
- JOB_INGEST_FAILURE
- JOB_VALIDATE_FAILURE
- OUTPUT_NOT_ACTIONABLE
- VALIDATION_NOT_TRUSTWORTHY
- USER_FLOW_CONFUSING

Priority guidance:

- P0: install, activate, start, ingest, or validate repeatedly fails on a real target.
- P1: the flow runs, but the user cannot tell what to do next.
- P2: wording, docs, or fixture clarity issues.

## 12. What Counts As PASS

- A real Python + pytest auth/login project is used as the target.
- `doctor`, `pack list`, `pack show`, `install`, `activate`, and `pack start` pass.
- A job id is extracted.
- If an AI reply exists, `job-ingest` and `job-validate` pass.
- No target source file is patched automatically.
- `DOGFOOD_REPORT.md` is written.

## 13. What Counts As FAIL

- Treating a demo fixture run as dogfood PASS.
- Using `examples/auth_bug_demo` as the dogfood target.
- Install, activate, start, or job id extraction fails.
- An AI reply exists but ingest or validate fails without a clear recorded cause.
- Source code is patched automatically.
- A provider API key or network call becomes required.
