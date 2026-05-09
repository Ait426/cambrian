# Cambrian Product RC Checklist

## Split-Run Regression Gate

- [ ] `docs/release/SPLIT_RUN_REGRESSION_GATE.md` is current.
- [ ] installed wheel smoke is PASS.
- [ ] focused release gates are PASS.
- [ ] broad pytest validation uses split-run evidence instead of relying only on one long `python -m pytest -q`.
- [ ] timeout-only broad-suite failures are classified as `SPLIT_RUN_REQUIRED` only after isolated chunks pass.
- [ ] `.cambrian/auto/report.yaml` has no open blockers before release gate GO.

## Worktree Release Handoff Gate

- [ ] `docs/release/WORKTREE_RELEASE_HANDOFF.md` is current.
- [ ] worktree changes are reviewed by product area, not as one flat diff.
- [ ] latest auto release gate verdict is GO.
- [ ] commit slices are planned before tagging or packaging.
- [ ] no secrets or private project data are included.

## Commit Slicing Gate

- [ ] `docs/release/COMMIT_SLICING_PLAN.md` is current.
- [ ] each commit slice has a suggested commit message.
- [ ] each commit slice has a slice-specific validation gate.
- [ ] `.cambrian/` evidence is not committed by default.
- [ ] staged diffs are checked with `git diff --cached --stat`.

## Packaging Slice Gate

- [ ] `docs/release/PACKAGING_SLICE_READY.md` is current.
- [ ] `python scripts/smoke_installed_wheel.py` is PASS.
- [ ] packaging test gate is PASS.
- [ ] staged diff contains only Slice 1 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Auto Runtime Slice Gate

- [ ] `docs/release/AUTO_RUNTIME_SLICE_READY.md` is current.
- [ ] auto runtime test gate is PASS.
- [ ] authority mode remains `proposal_only` by default.
- [ ] full authority is explicit only.
- [ ] auto run stays bounded by `--max-steps`.
- [ ] release gate uses current evidence rather than stale blockers.
- [ ] staged diff contains only Slice 2 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Harness Workforce Skill Slice Gate

- [ ] `docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md` is current.
- [ ] harness workforce skill test gate is PASS.
- [ ] custom harness creation remains the primary path.
- [ ] presets remain optional seeds only.
- [ ] harness install requires approval and engineering gate evidence.
- [ ] install does not dispatch agents.
- [ ] `job start` returns selected agents and selected skills.
- [ ] staged diff contains only Slice 3 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Pack Template Benchmark Slice Gate

- [ ] `docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md` is current.
- [ ] pack/template/benchmark split-run test gate is PASS.
- [ ] broad timeout risk is classified through split-run evidence.
- [ ] advanced pack/template/benchmark surfaces do not become the default launch path.
- [ ] benchmark proof remains local validation evidence, not public proof claims.
- [ ] staged diff contains only Slice 4 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Launch Pilot Release Docs Slice Gate

- [ ] `docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md` is current.
- [ ] launch pilot release docs test gate is PASS.
- [ ] launch docs avoid fake proof claims.
- [ ] pilot docs avoid real participant names, emails, company names, and private project details.
- [ ] release docs point to split-run validation evidence.
- [ ] staged diff contains only Slice 5 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Web Tools Slice Gate

- [ ] `docs/release/WEB_TOOLS_SLICE_READY.md` is current.
- [ ] `python tools/generate_web_catalog.py` succeeds.
- [ ] web catalog test gate is PASS.
- [ ] web catalog remains a hiring desk, not the runtime.
- [ ] local Cambrian runtime boundary says install, job handoff, validation, and proof.
- [ ] web pages do not mutate `.cambrian/` runtime state.
- [ ] staged diff contains only Slice 6 files.
- [ ] `.cambrian/` runtime evidence is excluded unless intentionally staged.

## Runtime Evidence Archive Slice Gate

- [ ] `docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md` is current.
- [ ] evidence archive test gate is PASS.
- [ ] latest selected auto release gate verdict is GO.
- [ ] release gate evidence is summarized in `docs/release/` by default.
- [ ] full `.cambrian/` runtime tree is excluded by default.
- [ ] raw external AI replies, private project paths, user data, and secrets are excluded.
- [ ] staged diff contains only Slice 7 files unless this is an explicit evidence artifact commit.
- [ ] `.cambrian/auto` raw evidence is committed only with an explicit evidence archive scope.

## Final Commit Staging Handoff Gate

- [ ] `docs/release/FINAL_COMMIT_STAGING_HANDOFF.md` is current.
- [ ] final commit staging handoff test gate is PASS.
- [ ] stage and commit one slice at a time.
- [ ] latest auto release gate is GO.
- [ ] `git diff --cached --stat` matches the intended slice before each commit.
- [ ] `git diff --cached --name-only` contains no secrets, private data, raw external AI replies, or unintended `.cambrian/` files.
- [ ] no tag is created before the selected staged commits and RC smoke gate pass.

## 162R-REPLACE-V3 Conversational Harness, Workforce And Skill Builder

- [ ] `cambrian skill generate --json` creates a generated skillset draft
- [ ] `cambrian harness install --confirm --json` writes `.cambrian/skills/*.yaml`
- [ ] `workforce.yaml` includes agent-to-skill mapping
- [ ] `cambrian job start "..." --json` returns `selected_agents`
- [ ] `cambrian job start "..." --json` returns `selected_skills`
- [ ] preset skills remain optional seeds only
- [ ] generated skill files have `type: generated_skill`

## 162R-REPLACE-V2 Conversational Harness And Workforce Builder

- [ ] `cambrian harness design --json` creates a custom harness design
- [ ] `cambrian workforce generate --json` creates a generated workforce draft
- [ ] `cambrian harness install --confirm --json` writes `.cambrian/workforce.yaml`
- [ ] generated agents are written under `.cambrian/agents/`
- [ ] `dispatch_policy.auto_dispatch_on_install` is false
- [ ] install does not create a job
- [ ] `cambrian job start "..." --json` creates a job on demand
- [ ] `cambrian agent run <agent-id> "..." --json` can call a specific generated agent
- [ ] presets remain optional seeds only

## 162R Conversational Custom Harness Builder

- [ ] `cambrian harness interview start --json` creates AI-mediated questions
- [ ] `cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json` validates required answers
- [ ] `cambrian harness plan --json` creates `plan_type=custom`
- [ ] `cambrian harness install --json` is blocked without `--confirm`
- [ ] `cambrian harness install --confirm --json` writes `.cambrian/harness.yaml`
- [ ] `cambrian agent dispatch "로그인 에러 수정해" --json` uses the custom harness
- [ ] presets are optional seeds only
- [ ] no provider API call
- [ ] no automatic patch apply

## Fresh Install Gate

- [ ] `python -m build` 성공
- [ ] wheel 설치 성공
- [ ] `cambrian --help` 성공
- [ ] `cambrian doctor` 성공
- [ ] `cambrian demo create login-bug` 성공
- [ ] demo project에 `fixtures/ai_reply_patch_candidate.yaml` 존재
- [ ] `pack list`에서 `auth-bug-core` 표시
- [ ] `pack show auth-bug-core` 성공
- [ ] `install pack auth-bug-core` 성공
- [ ] `activate auth-bug-core` 성공
- [ ] `pack start "로그인 에러 수정해"` 성공
- [ ] `job-ingest` 성공
- [ ] `job-validate` 성공
- [ ] README quickstart와 실제 명령 일치
- [ ] help 첫 화면이 pack-first
- [ ] help 출력에 깨진 한글 없음
- [ ] advanced/future 기능이 README 첫 화면에 노출되지 않음

## Installed Wheel Pack Catalog Gate

- [x] wheel includes `engine/_data/packs/catalog.yaml`
- [x] wheel includes `engine/_data/packs/auth-bug-core.cambrian-pack.yaml`
- [x] extracted wheel can run `cambrian pack list --json`
- [x] extracted wheel can run `cambrian pack show auth-bug-core --json`
- [x] generated first-run project includes `fixtures/ai_reply_patch_candidate.yaml`

## TypeScript/Jest Harness Gate

- [ ] TypeScript + Jest auth/API project scan recommends `typescript-jest-auth-core`
- [ ] `cambrian harness plan --json` selects `typescript-jest-auth-core`
- [ ] `cambrian harness install --json` installs and activates `typescript-jest-auth-core`
- [ ] `cambrian agent dispatch "로그인 에러 수정해" --json` creates a `typescript-jest-auth-core` job
- [ ] TypeScript/Jest project blocks direct `auth-bug-core` install with `incompatible_harness`
- [ ] TypeScript/Jest job validation does not call the Python/pytest lane
- [ ] ONMI-STAY finding is recorded in `docs/release/ONMI_STAY_HARNESS_FINDING.md`

## Dogfood Gate

- [ ] 실제 Python/pytest 프로젝트를 대상으로 dogfood 실행
- [ ] 원본 프로젝트 보호 확인
- [ ] auth-bug-core start 성공
- [ ] AI reply ingest 성공 또는 `WAITING_FOR_AI_REPLY`로 정상 대기
- [ ] validate 성공 또는 명확한 실패 원인 기록
- [ ] `DOGFOOD_REPORT.md` 작성
- [ ] 다음 사용성 blocker가 P0/P1/P2로 분류됨
- [ ] `examples/auth_bug_demo`를 dogfood PASS로 사용하지 않음

## Auto Loop Dogfood Gate

- [ ] 실제 프로젝트 target 없이 fake PASS 하지 않음
- [ ] `examples/auth_bug_demo`를 auto loop dogfood PASS로 사용하지 않음
- [ ] `cambrian auto cycle --max-steps 1 --json`이 task directive를 생성
- [ ] 외부 Codex/Claude 결과 파일이 hardened result contract를 따름
- [ ] `cambrian auto step ingest <task-ref> --result <result-file> --json` 성공
- [ ] 결과 ingest 이후 다음 `cambrian auto cycle --max-steps 1 --json` 성공
- [ ] `AUTO_LOOP_DOGFOOD_REPORT.md` 작성
- [ ] source patch 자동 적용 없음

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
