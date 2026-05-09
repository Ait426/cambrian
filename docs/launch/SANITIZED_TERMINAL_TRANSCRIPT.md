# Sanitized Terminal Transcript

Source: `.launch_runs/latest`

This public transcript is a curated excerpt. Raw absolute paths are replaced with `[demo-workdir]`. It does not include API keys, private source, or full raw stdout.

## Step 1 -- Show Pack

```bash
cambrian pack show auth-bug-core
```

Output excerpt:

```text
Pack:
  id      : auth-bug-core
  name    : Auth Bug Core
  kind    : lane
  version : 0.1.0
  proof   : unknown

Description:
  Python + pytest + narrow auth/login bug fix lane pack

Fit:
  status: strong

Install:
  cambrian install pack auth-bug-core
```

## Step 2 -- Install Pack

```bash
cambrian install pack auth-bug-core
```

Output excerpt:

```text
Installing pack from local catalog.

Pack:
  auth-bug-core

Pack install completed.

Installed:
  workers   : 3
  teams     : 1
  templates : 1
  benchmarks: 1
  lane      : python-pytest-auth-bug-core
```

## Step 3 -- Install Doctor

```bash
cambrian install doctor
```

Output excerpt:

```text
Install Doctor
==================================================

Checks:
  OK worker installed: bug-fix-agent
  OK worker installed: regression-test-agent
  OK worker installed: review-agent
  OK team installed: auth-bug-team
  OK template installed: auth-bug-template
  OK benchmark workset installed: auth-bug-workset
```

## Step 4 -- Activate Pack

```bash
cambrian pack activate auth-bug-core
```

Output excerpt:

```text
Pack activated.

Pack:
  auth-bug-core@0.1.0

This does not apply a template or modify source code.
It only selects this pack as the current work context.

Recommended first job:
  cambrian pack start "로그인 에러 수정해"
```

## Step 5 -- Pack Doctor

```bash
cambrian pack doctor auth-bug-core
```

Output excerpt:

```text
Pack Doctor
==================================================

Pack:
  auth-bug-core@0.1.0

Readiness:
  ready

Fit:
  strong

Lane:
  Python + pytest + auth/login bug fixes
```

## Step 6 -- Start Job

```bash
cambrian pack start "로그인 에러 수정해"
```

Output excerpt:

```text
pack job started for auth-bug-core
AI provider was not called.
Source code was not modified.

Job:
  job-auth-bug-core-[timestamp]

Next:
  paste the generated packet into your AI
```

## Step 7 -- Ingest Canned AI Reply

```bash
cambrian pack job-ingest job-auth-bug-core-[timestamp] fixtures/ai_reply_patch_candidate.yaml
```

Output excerpt:

```text
reply_kind: patch_candidate
status: validation_ready
target_path: src/auth.py
```

## Step 8 -- Validate

```bash
cambrian pack job-validate job-auth-bug-core-[timestamp]
```

Output excerpt:

```text
validation_status: validated
proposal_ref: .cambrian/proposals/...
source code was not auto-applied
```

## Step 9 -- Proof / Outcome

```bash
cambrian pack proof auth-bug-core
```

Output excerpt:

```text
Pack Proof Card
==================================================

Pack:
  auth-bug-core

Outcome:
  validated proposal rate : local evidence only
  adoption rate           : unknown until explicit adoption

Known limits:
  - local proof is not public benchmark superiority
  - proof card is local-only and is not uploaded automatically
```

## Privacy Notes

- `[demo-workdir]` replaces local absolute paths.
- The transcript uses a canned AI reply fixture.
- No provider API call is shown or required.
- No fake proof metric is claimed.
