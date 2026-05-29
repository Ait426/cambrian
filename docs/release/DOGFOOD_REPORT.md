# Cambrian Dogfood Report

## Date

2026-05-07

## Target Project

- Path: `<operator-local-target-redacted>`
- Language: Python
- Test command: pytest or project equivalent
- Git repo: False
- Dirty tree before: None
- Git status before:

```text
not a git repo
```

## Cambrian RC

- Install mode: installed `cambrian` command or provided executable
- Version: recorded by command output if available
- Wheel: see `docs/release/RC_VERIFICATION.md`
- Python: 3.14.2

## Commands

```bash
cambrian.exe doctor
cambrian.exe pack list
cambrian.exe pack show auth-bug-core
cambrian.exe install pack auth-bug-core
cambrian.exe pack activate auth-bug-core
cambrian.exe pack start "Fix the login error" --json
cambrian.exe pack job-ingest job-auth-bug-core-20260507_105653 <operator-local-ai-reply-yaml> --json
cambrian.exe pack job-validate job-auth-bug-core-20260507_105653 --json
```

## AI Reply

- Reply file: `<operator-local-ai-reply-yaml>`
- Provider API call: none

## Results

| Step | Result | Duration | Notes |
| --- | ---: | ---: | --- |
| cambrian doctor | PASS | 0.369s | ok |
| pack list | PASS | 0.340s | ok |
| pack show auth-bug-core | PASS | 0.621s | ok |
| install pack auth-bug-core | PASS | 0.439s | ok |
| activate auth-bug-core | PASS | 0.489s | ok |
| pack start | PASS | 0.533s | ok |
| job-ingest | PASS | 0.713s | ok |
| job-validate | FAIL | 1.798s | JOB_VALIDATE_FAILURE |

## Human Evaluation

- Was the next command clear: not evaluated yet
- Was the output actionable: not evaluated yet
- Did the result identify a useful patch/test direction: not evaluated yet
- Was validation trustworthy: not evaluated yet
- What was confusing:
- not evaluated yet

## Blockers

- JOB_VALIDATE_FAILURE: `job-validate` failed after a successful start and ingest.

## Usability Blocker Classification

- P0: dogfood cannot be counted as end-to-end PASS until the validation failure is fixed or the AI reply contract mismatch is explained by a reproducible user error.

## Failure Classes

```text
INSTALL_FAILURE, DOCTOR_FAILURE, PACK_CATALOG_FAILURE, PACK_INSTALL_FAILURE, PACK_ACTIVATE_FAILURE, PACK_START_FAILURE, AI_REPLY_FORMAT_FAILURE, JOB_INGEST_FAILURE, JOB_VALIDATE_FAILURE, OUTPUT_NOT_ACTIONABLE, VALIDATION_NOT_TRUSTWORTHY, USER_FLOW_CONFUSING
```

## Source Protection

- Automatic patch apply: no
- Provider API call: no
- Allowed target metadata: `.cambrian/`
- Cambrian repo report file: docs/release/DOGFOOD_REPORT.md

## Verdict

FAIL
