# Launch Checklist

## Golden Path

- [x] `cambrian pack list` works
- [x] `cambrian pack show auth-bug-core` works
- [x] `cambrian install pack auth-bug-core` works
- [x] `cambrian install doctor` passes or gives actionable errors
- [x] `cambrian pack activate auth-bug-core` works
- [x] `cambrian pack doctor auth-bug-core` works
- [x] `cambrian pack start "로그인 에러 수정해"` creates a packet/job
- [x] `cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml` routes the canned AI reply
- [x] `cambrian pack job-validate <job-id>` validates the job handoff
- [x] `cambrian pack proof auth-bug-core` completes and honestly reports local proof state

## Launch Assets

- [x] `auth-bug-core` exists in local catalog
- [x] `examples/auth_bug_demo/src/auth.py` exists
- [x] `examples/auth_bug_demo/tests/test_auth.py` exists
- [x] `examples/auth_bug_demo/fixtures/ai_reply_patch_candidate.yaml` exists
- [x] canned reply `old_text` matches example source
- [x] Auth Bug Core web detail page shows install command
- [x] Auth Bug Core web detail page says web is hiring desk and local runtime executes install/job handoff/validation/proof
- [x] README quickstart matches implemented commands
- [x] Launch docs exist
- [x] No fake proof claims in launch docs or web page
- [x] Launch dry run passes
- [x] transcript generated
- [x] LAUNCH_RC_REPORT.md updated
- [x] GO_NO_GO.md created
- [x] canned AI reply validated
- [x] no provider API call required
- [x] no fake proof claim

## Scope Cut

- [x] Remote registry is not part of the launch run
- [x] Dependency resolver is not part of the launch run
- [x] Rollout/vNext/release candidate flow is not part of the launch run
- [x] Marketplace, payment, login, cloud execution are not part of the launch run
- [x] Provider API call is not part of the launch run
- [x] Source code auto apply is not part of the launch run

## Before Showing

- [x] Run `python tools/run_launch_demo.py --out .launch_runs/latest`
- [x] Run `python -m pytest tests/test_launch_demo_runner.py -q`
- [x] Run `python -m pytest tests/test_launch_demo_fixture.py -q`
- [x] Run `python -m pytest tests/test_launch_golden_path.py -q`
- [x] Run `python -m pytest tests/test_launch_surface.py -q`
- [x] Run `python -m pytest tests/test_product_docs.py -q`
- [x] Run full pytest
- [ ] Confirm the product run terminal is in `examples/auth_bug_demo`
- [x] Confirm recovery commands are visible in docs
