# Expected Demo Output

## Before patch application

`pytest` is expected to fail because `normalize_username()` returns the raw username.

## Cambrian flow

- `cambrian pack start "로그인 에러 수정해"` creates a pack job and bridge packet.
- `cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml` routes a `patch_candidate` reply.
- `cambrian pack job-validate latest` creates a validated proposal without applying source changes.
- `cambrian pack proof auth-bug-core` shows local usage/proof state. If no real accepted outcome exists yet, it should not claim fake metrics.

## After explicit patch application

If the suggested patch is applied to `src/auth.py`, the demo pytest suite should pass.
