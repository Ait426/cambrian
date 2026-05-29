# Cambrian Product RC Checklist

## Split-Run Regression Gate

- [x] `docs/release/SPLIT_RUN_REGRESSION_GATE.md` is current.
- [x] installed wheel smoke is PASS.
- [x] focused release gates are PASS.
- [x] broad pytest validation uses split-run evidence instead of relying only on one long `python -m pytest -q`.
- [x] timeout-only broad-suite failures are classified as `SPLIT_RUN_REQUIRED` only after isolated chunks pass.
- [x] `.cambrian/auto/report.yaml` has no open blockers before release gate GO.

## Worktree Release Handoff Gate

- [x] `docs/release/WORKTREE_RELEASE_HANDOFF.md` is current.
- [x] worktree changes are reviewed by product area, not as one flat diff.
- [x] latest auto release gate verdict is GO.
- [x] commit slices are planned before tagging or packaging.
- [x] no secrets or private project data are included in the current release candidate set.

## Commit Slicing Gate

- [x] `docs/release/COMMIT_SLICING_PLAN.md` is current.
- [x] each commit slice has a suggested commit message.
- [x] each commit slice has a slice-specific validation gate.
- [x] `.cambrian/` evidence is not committed by default.
- [ ] staged diffs are checked with `git diff --cached --stat`.

## Packaging Slice Gate

- [x] `docs/release/PACKAGING_SLICE_READY.md` is current.
- [x] `python scripts/smoke_installed_wheel.py` is PASS.
- [x] packaging test gate is PASS.
- [ ] staged diff contains only Slice 1 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Auto Runtime Slice Gate

- [x] `docs/release/AUTO_RUNTIME_SLICE_READY.md` is current.
- [x] auto runtime test gate is PASS.
- [x] authority mode remains `proposal_only` by default.
- [x] full authority is explicit only.
- [x] auto run stays bounded by `--max-steps`.
- [x] release gate uses current evidence rather than stale blockers.
- [ ] staged diff contains only Slice 2 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Harness Workforce Skill Slice Gate

- [x] `docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md` is current.
- [x] harness workforce skill test gate is PASS.
- [x] custom harness creation remains the primary path.
- [x] presets remain optional seeds only.
- [x] harness install requires approval and engineering gate evidence.
- [x] install does not dispatch agents.
- [x] `job start` returns selected agents and selected skills.
- [ ] staged diff contains only Slice 3 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Pack Template Benchmark Slice Gate

- [x] `docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md` is current.
- [x] pack/template/benchmark split-run test gate is PASS.
- [x] broad timeout risk is classified through split-run evidence.
- [x] advanced pack/template/benchmark surfaces do not become the default launch path.
- [x] benchmark proof remains local validation evidence, not public proof claims.
- [ ] staged diff contains only Slice 4 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Launch Pilot Release Docs Slice Gate

- [x] `docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md` is current.
- [x] launch pilot release docs test gate is PASS.
- [x] launch docs avoid fake proof claims.
- [x] pilot docs avoid real participant names, emails, company names, and private project details.
- [x] release docs point to split-run validation evidence.
- [ ] staged diff contains only Slice 5 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Web Tools Slice Gate

- [x] `docs/release/WEB_TOOLS_SLICE_READY.md` is current.
- [x] `python tools/generate_web_catalog.py` succeeds.
- [x] web catalog test gate is PASS.
- [x] web catalog remains a hiring desk, not the runtime.
- [x] local Cambrian runtime boundary says install, job handoff, validation, and proof.
- [x] web pages do not mutate `.cambrian/` runtime state.
- [ ] staged diff contains only Slice 6 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Runtime Evidence Archive Slice Gate

- [x] `docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md` is current.
- [x] evidence archive test gate is PASS.
- [x] latest selected auto release gate verdict is GO.
- [x] release gate evidence is summarized in `docs/release/` by default.
- [x] full `.cambrian/` runtime tree is excluded by default.
- [x] raw external AI replies, private project paths, user data, and secrets are excluded.
- [ ] staged diff contains only Slice 7 files unless this is an explicit evidence artifact commit.
- [ ] `.cambrian/auto` raw evidence is committed only with an explicit evidence archive scope.

## Final Commit Staging Handoff Gate

- [x] `docs/release/FINAL_COMMIT_STAGING_HANDOFF.md` is current.
- [x] final commit staging handoff test gate is PASS.
- [x] `python scripts/check_final_commit_staging_handoff.py --json` returns `ready_for_manual_slice_staging`.
- [x] `python scripts/check_final_commit_staging_handoff.py --worktree --all-slices --json` returns `all_slices_worktree_ready`.
- [x] receipt/worktree planning uses `git status --porcelain=v1 -z --untracked-files=all` so untracked directories are file-level.
- [x] generated pytest/tool cache directories are ignored before release staging.
- [x] receipt JSON keeps full slice candidate paths but compacts `excluded_by_default` into count, category summary, truncation flag, and bounded samples.
- [x] receipt generation writes per-slice pathspec files under `dist/final-commit-staging-pathspecs/`.
- [x] receipt generation writes `dist/final-commit-staging-runbook.md` with slice-specific prestage, stage, staged-verify, and test gate commands.
- [x] receipt JSON includes per-slice `test_gate_commands` and `test_gate_commands_sha256`.
- [x] receipt generation writes per-slice pending test gate evidence templates under `dist/final-commit-test-gate-evidence/`.
- [x] `python scripts/check_final_commit_staging_handoff.py --write-receipt-dir dist` writes review-only staging receipts.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json` returns `receipt_all_artifacts_current`.
- [x] `--verify-all-artifacts` includes `receipt_test_gate_evidence_templates_current`.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json` verifies the receipt body and slice path digests.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-pathspec-files` returns `receipt_pathspec_files_current`.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-runbook` returns `receipt_runbook_current`.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree` returns `receipt_current`.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree --verify-pathspec-files --verify-runbook` returns `receipt_current_with_pathspecs_and_runbook`.
- [x] `python scripts/check_final_commit_staging_handoff.py --worktree --slice <slice_id> --json` lists the candidate paths before staging.
- [x] `python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>` returns `slice_prestage_ready`.
- [ ] selected slice is staged with `git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec` or an equivalent reviewed path list.
- [ ] planned `candidate_paths_sha256` is checked with `--expect-paths-sha256` after staging.
- [ ] stage and commit one slice at a time.
- [ ] `python scripts/check_final_commit_staging_handoff.py --staged --slice <slice_id>` returns `slice_stage_ready` before each commit.
- [ ] `python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>` returns `receipt_staged_slice_ready` before each commit.
- [ ] `python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id>` returns `slice_commit_ready` and prints the receipt-locked suggested commit message plus `test_gate_commands`.
- [ ] selected slice's receipt-locked `test_gate_commands` pass before each commit.
- [ ] `python scripts/check_final_commit_staging_handoff.py --verify-test-gate-evidence-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id> --test-gate-evidence dist/final-commit-test-gate-evidence/<slice_id>.json` returns `test_gate_evidence_ready` before each commit.
- [ ] the slice test gate evidence JSON is saved at the receipt-designated `test_gate_evidence_file`.
- [ ] every PASS command result in the slice test gate evidence JSON has a unique non-empty portable local `evidence_ref` under `dist/final-commit-test-gate-logs/` and matching `evidence_sha256`.
- [ ] every referenced test gate evidence file contains the exact expected command string.
- [ ] `python scripts/check_final_commit_staging_handoff.py --verify-final-commit-from-receipt dist/final-commit-staging-receipt.json --slice <slice_id> --test-gate-evidence dist/final-commit-test-gate-evidence/<slice_id>.json` returns `slice_final_commit_gate_ready` before each commit.
- [ ] the integrated final commit gate includes `receipt_all_artifacts_current`.
- [ ] the integrated final commit gate has empty `blocking_reasons`.
- [ ] the integrated final commit gate has empty `blocking_details`.
- [ ] the integrated final commit gate has empty `recovery_commands`.
- [ ] the integrated final commit gate has empty `recovery_command_plan`.
- [ ] the integrated final commit gate has `recovery_command_summary.total_count` equal to `0`.
- [ ] the integrated final commit gate includes `recovery_execution_policy`.
- [ ] `recovery_execution_policy.script_executes_recovery_commands` is `false`.
- [ ] `recovery_execution_policy.script_executes_git_add` is `false`.
- [ ] `recovery_execution_policy.index_mutation_requires_manual_user_confirmation` is `true`.
- [x] latest auto release gate is GO.
- [ ] `git diff --cached --stat` matches the intended slice before each commit.
- [ ] `git diff --cached --name-only` contains no secrets, private data, raw external AI replies, or unintended `.cambrian/` files.
- [ ] no tag is created before the selected staged commits and RC smoke gate pass.

## GitHub Release Ready Gate

- [x] `docs/release/GITHUB_RELEASE_RUNBOOK.md` records the public GitHub release path.
- [x] `docs/release/GITHUB_RELEASE_NOTES_0_3_0.md` is ready for the first GitHub Release body.
- [x] `python scripts/check_github_release_ready.py` returns `GO`.
- [x] `dist/github-release-ready.json` verifies with `python scripts/check_github_release_ready.py --verify-receipt dist/github-release-ready.json`.
- [x] GitHub origin is present and does not contain embedded credentials.
- [x] `cambrian-install-kit-release-bundle.zip` verifies as the only external-user release asset.
- [x] install-kit send-ready receipt verdict is `GO`.
- [x] README points to the GitHub Release asset path and keeps PyPI deferred.
- [x] public release text scan has no private local path markers.
- [x] the script does not push to GitHub, create a GitHub Release, upload release assets, or publish PyPI.
- [ ] reviewed slices are committed before a GitHub Release is created.
- [ ] the operator manually creates the GitHub Release and uploads only the release bundle asset.

## 162R-REPLACE-V3 Conversational Harness, Workforce And Skill Builder

- [x] `cambrian skill generate --json` creates a generated skillset draft
- [x] `cambrian harness install --confirm --json` writes `.cambrian/skills/*.yaml`
- [x] `workforce.yaml` includes agent-to-skill mapping
- [x] `cambrian job start "..." --json` returns `selected_agents`
- [x] `cambrian job start "..." --json` returns `selected_skills`
- [x] preset skills remain optional seeds only
- [x] generated skill files have `type: generated_skill`

## 162R-REPLACE-V2 Conversational Harness And Workforce Builder

- [x] `cambrian harness design --json` creates a custom harness design
- [x] `cambrian workforce generate --json` creates a generated workforce draft
- [x] `cambrian harness install --confirm --json` writes `.cambrian/workforce.yaml`
- [x] generated agents are written under `.cambrian/agents/`
- [x] `dispatch_policy.auto_dispatch_on_install` is false
- [x] install does not create a job
- [x] `cambrian job start "..." --json` creates a job on demand
- [x] `cambrian agent run <agent-id> "..." --json` can call a specific generated agent
- [x] presets remain optional seeds only

## 162R Conversational Custom Harness Builder

- [x] `cambrian harness interview start --json` creates AI-mediated questions
- [x] `cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json` validates required answers
- [x] `cambrian harness plan --json` creates `plan_type=custom`
- [x] `cambrian harness install --json` is blocked without `--confirm`
- [x] `cambrian harness install --confirm --json` writes `.cambrian/harness.yaml`
- [x] `cambrian agent dispatch "로그인 에러 수정해" --json` uses the custom harness
- [x] presets are optional seeds only
- [x] no provider API call
- [x] no automatic patch apply

## Fresh Install Gate

- [x] `python -m build` 성공
- [x] wheel 설치 성공
- [x] `cambrian --help` 성공
- [x] `cambrian doctor` 성공
- [x] `cambrian demo create login-bug` 성공
- [x] demo project에 `fixtures/ai_reply_patch_candidate.yaml` 존재
- [x] `pack list`에서 `auth-bug-core` 표시
- [x] `pack show auth-bug-core` 성공
- [x] `install pack auth-bug-core` 성공
- [x] `activate auth-bug-core` 성공
- [x] `pack start "로그인 에러 수정해"` 성공
- [x] `job-ingest` 성공
- [x] `job-validate` 성공
- [x] README quickstart와 실제 명령 일치
- [x] help 첫 화면이 pack-first
- [x] help 출력에 깨진 한글 없음
- [x] advanced/future 기능이 README 첫 화면에 노출되지 않음

## AI Company Golden Path Gate

- [x] `docs/release/AI_COMPANY_GOLDEN_PATH.md` is current.
- [x] `python scripts/smoke_ai_company_gold_path.py` is PASS.
- [x] fresh installed wheel can create project AI agents.
- [x] fresh installed wheel can generate, search, and fuse project skills.
- [x] fresh installed wheel can run harness engineer design/review/dry-run.
- [x] fresh installed wheel can record job evidence and run evolve propose/preview/apply.
- [x] fresh installed wheel can generate a private-safe company snapshot without raw private project data.
- [x] fresh installed wheel can start `cambrian-mcp` and write an MCP operability receipt.
- [x] fresh installed wheel exposes `cambrian mcp verify --receipt dist/mcp_operability_receipt.json`.
- [x] `docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md` documents the external AI-client MCP connection path.
- [x] MCP operability receipt blocks missing `cwd`, blocks harness install without `confirm=true`, and reports no arbitrary shell.
- [x] provider API key is not required for the golden path.
- [x] source code is not automatically patched by the golden path.

## Cambrian Install Kit Gate

- [x] `docs/release/CAMBRIAN_INSTALL_KIT.md` is current.
- [x] `python scripts/build_cambrian_install_kit.py` writes `dist/cambrian-install-kit-<version>.zip`.
- [x] `python scripts/prepare_cambrian_install_kit_release.py` builds the install kit, verifies offline install, writes receipt, handoff, send-ready, and release receipt.
- [x] `python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json` verifies the release receipt without rebuilding.
- [x] `dist/START_HERE_CAMBRIAN_INSTALL_KIT.md` tells the recipient which files to open, how to verify the release receipt, and what not to share.
- [x] `dist/VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py` lets a recipient verify the extracted bundle without the Cambrian source checkout.
- [x] `dist/INSTALL_CAMBRIAN_FROM_BUNDLE.py` lets a recipient install from the extracted release bundle root, with `.bat` and `.sh` wrappers for the same path.
- [x] `python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip` verifies the recipient bundle contains START_HERE, install kit ZIP, receipt, handoff, send-ready, release receipt, and matching embedded hash chain.
- [x] install kit includes wheel, Python installer, PowerShell/cmd/bash wrappers, manifest, and Claude/Codex prompt.
- [x] `python scripts/verify_cambrian_install_kit.py` verifies ZIP manifest hashes.
- [x] `python scripts/verify_cambrian_install_kit.py --install-check` extracts the ZIP and installs Cambrian into a fresh project venv.
- [x] `python scripts/verify_cambrian_install_kit.py --install-check --offline` verifies wheelhouse-only install.
- [x] install receipt records `cambrian --help`, `cambrian doctor --json`, and `cambrian company snapshot --help` as passed.
- [x] `python scripts/verify_cambrian_install_kit.py --install-check --offline --receipt dist/cambrian-install-kit-verification-receipt.json` writes a shareable receipt.
- [x] `python scripts/verify_cambrian_install_kit.py --verify-receipt dist/cambrian-install-kit-verification-receipt.json` verifies the receipt without unpacking the ZIP.
- [x] install kit verification receipt omits absolute paths, secrets, raw private project data, and temporary install output.
- [x] `python scripts/prepare_cambrian_install_kit_handoff.py` writes recipient handoff JSON/Markdown linked to the ZIP and receipt.
- [x] `python scripts/prepare_cambrian_install_kit_handoff.py --verify-handoff dist/cambrian-install-kit-handoff.json` verifies the handoff body hash, artifact chain, do-not-share guardrails, and manual dispatch policy.
- [x] `python scripts/check_cambrian_install_kit_send_ready.py` writes install kit send-ready JSON/Markdown with verdict `GO`.
- [x] `python scripts/check_cambrian_install_kit_send_ready.py --verify-send-ready dist/cambrian-install-kit-send-ready.json` verifies the ZIP, receipt, handoff artifact chain and manual dispatch policy.
- [x] synthetic install-kit rehearsal dispatch and recipient-checkpoint artifacts are rejected by default verifiers as standalone send or recipient proof.
- [x] release bundle `START_HERE` and Codex/Claude prompt state local receipts are local validation evidence only, not public proof, sale-ready proof, marketplace proof, success-rate proof, or first-recipient confirmation.
- [x] install-kit handoff and send-ready copy-paste messages carry the same local-validation-only claim boundary.
- [x] release bundle verifier rejects bundles whose handoff/send-ready copy-paste messages omit the local-validation-only claim boundary.
- [x] dispatch-record preserves a hashed copy-paste message policy for install/gold-path/MCP receipt instructions plus the local-validation-only and first-recipient-confirmation boundary.
- [x] recipient-checkpoint preserves the dispatch copy-paste boundary as share-safe hashes and booleans before any recipient proof claim.
- [x] first-recipient post-send sequence mirrors the recipient-checkpoint copy-paste boundary as share-safe hashes and booleans when a checkpoint is recorded.

## PyPI Release Gate

- [x] `docs/release/PYPI_RELEASE.md` is current.
- [x] `python scripts/prepare_pypi_release.py` builds isolated `dist/pypi/` artifacts.
- [x] `twine check` passes for `dist/pypi/*`.
- [x] `dist/pypi_release_receipt.json` records package metadata, artifact hashes, and publish commands.
- [x] `python scripts/prepare_pypi_release.py --verify-receipt dist/pypi_release_receipt.json` verifies the receipt body hash, artifact hashes, path redaction, and token placeholders.
- [x] local wheel fresh install smoke passes with `python scripts/verify_pypi_install.py --wheel dist/pypi/cambrian-0.3.0-py3-none-any.whl --repository pypi --version 0.3.0`.
- [x] `python scripts/verify_pypi_install.py --verify-receipt dist/pypi_local_wheel_install_receipt.json` verifies the install receipt body hash, path redaction, and command-output redaction.
- [x] `python scripts/prepare_pypi_release.py --preflight-upload testpypi` writes a token-free publish preflight receipt with status `ready_for_testpypi_token` when only the token is missing.
- [x] `python scripts/prepare_pypi_release.py --preflight-upload testpypi --require-token-env` writes status `ready_to_upload_testpypi` when token env is present, without recording the token value.
- [x] `python scripts/check_pypi_publish_ready.py --repository testpypi` writes `pypi-publish-ready-testpypi.json` with verdict `WAITING_FOR_TOKEN` when the only missing input is the local TestPyPI token.
- [x] `python scripts/check_pypi_publish_ready.py --repository testpypi --require-token-env` reaches verdict `GO` when token env is present, without recording the token value.
- [x] `python scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json` verifies the preflight receipt body hash, path redaction, and token placeholder policy.
- [x] final PyPI preflight writes a blocked receipt instead of crashing when the TestPyPI install receipt is missing.
- [x] final PyPI token preflight reaches `ready_to_upload_pypi` only when a same-version TestPyPI install receipt and PyPI token env are both present, without recording the token value.
- [x] final PyPI publish-ready handoff reports `BLOCKED` until the same-version TestPyPI install receipt exists.
- [x] upload commands fail fast before build when `TWINE_PASSWORD` is missing or `TWINE_USERNAME` is not `__token__`.
- [x] upload commands fail fast unless the matching `pypi-publish-ready-*.json` receipt has verdict `GO`.
- [x] final PyPI upload path is guarded by `--testpypi-install-receipt dist/pypi_testpypi_install_receipt.json`, fails fast before build/upload, and rejects non-TestPyPI receipts.
- [ ] TestPyPI upload succeeds with token provided through local environment variables only.
- [ ] TestPyPI install check succeeds and writes `dist/pypi_testpypi_install_receipt.json`.
- [ ] final PyPI upload succeeds only after TestPyPI install receipt verification.
- [ ] `pip install cambrian` works from a fresh environment.
- [ ] `python scripts/verify_pypi_install.py --repository pypi --version 0.3.0` writes a verified receipt after upload.

## Installed Wheel Pack Catalog Gate

- [x] wheel includes `engine/_data/packs/catalog.yaml`
- [x] wheel includes `engine/_data/packs/auth-bug-core.cambrian-pack.yaml`
- [x] extracted wheel can run `cambrian pack list --json`
- [x] extracted wheel can run `cambrian pack show auth-bug-core --json`
- [x] generated first-run project includes `fixtures/ai_reply_patch_candidate.yaml`

## TypeScript/Jest Harness Gate

- [x] TypeScript + Jest auth/API project scan recommends `typescript-jest-auth-core`
- [x] `cambrian harness interview start --json` exposes `typescript-jest-auth-core` as a compatible optional seed
- [x] `cambrian harness plan --json` keeps `plan_type=custom` for TypeScript/Jest projects
- [x] `cambrian harness install --confirm --json` installs and activates a custom harness, not a preset clone
- [x] `cambrian agent dispatch "로그인 에러 수정해" --json` creates a custom harness job for the TypeScript/Jest project
- [x] TypeScript/Jest project blocks direct `auth-bug-core` install with `incompatible_harness`
- [x] TypeScript/Jest job validation does not call the Python/pytest lane
- [x] ONMI-STAY finding is recorded in `docs/release/ONMI_STAY_HARNESS_FINDING.md`

## Dogfood Gate

- [ ] real Python/pytest project dogfood execution
- [ ] original project source protection verified
- [x] auth-bug-core start succeeded
- [x] AI reply ingest succeeded or normal `WAITING_FOR_AI_REPLY` state was recorded
- [x] validate succeeded or a clear failure reason was recorded
- [x] `DOGFOOD_REPORT.md` written
- [x] next usability blocker classified as P0/P1/P2
- [x] `examples/auth_bug_demo` was not used as dogfood PASS evidence

## Auto Loop Dogfood Gate

- [x] no fake PASS without a real project target
- [x] `examples/auth_bug_demo` was not used as auto loop dogfood PASS evidence
- [x] `cambrian auto cycle --max-steps 1 --json` creates a task directive
- [x] external Codex/Claude result file follows the hardened result contract
- [x] `cambrian auto step ingest <task-ref> --result <result-file> --json` succeeded
- [x] next `cambrian auto cycle --max-steps 1 --json` succeeded after result ingest
- [x] `AUTO_LOOP_DOGFOOD_REPORT.md` written
- [x] no automatic source patch

## Official Smoke Command

```bash
python scripts/smoke_installed_wheel.py
```

Expected summary:

```text
[RC Fresh Install Smoke]

build wheel: PASS
create venv: PASS
install wheel: PASS
cambrian --help: PASS
cambrian doctor: PASS
demo create login-bug: PASS
pack list: PASS
pack show auth-bug-core: PASS
install pack auth-bug-core: PASS
activate auth-bug-core: PASS
pack start: PASS
job-ingest: PASS
job-validate: PASS

Result: PASS
```

## Notes

- The installed wheel bundles the seed pack catalog and Auth Bug Core manifest under `engine/_data/packs/`.
- The resolver still prefers a local `./packs/catalog.yaml` when present, then source-tree `packs/catalog.yaml`, then bundled wheel data.
- Auth Bug Core validation expects a Python + pytest project environment. The installed wheel smoke installs `pytest` into the temporary venv before validating the first-run fixture.
