# Cambrian Worktree Release Handoff

## Purpose

This handoff makes the current Cambrian worktree reviewable before commit, tag, or packaging.

The repo contains a large product evolution batch. Reviewers should not treat the diff as one flat change. It should be reviewed by product area and validation gate.

## Current Snapshot

- Total git status entries: 188
- Tracked modified files: 26
- Untracked files/directories: 162
- Slice candidate entries: 188
- Excluded-by-default entries: 0
- Manual review entries: 0
- Engine/runtime slice entries: 0
- Harness/workforce/skill slice entries: 0
- Launch/pilot/release docs slice entries: 173
- Pack/template/benchmark slice entries: 0
- Web/tool slice entries: 12
- Runtime evidence archive entries: 3
- Generated test/tool caches and local session handoff notes are ignored before staging. Runtime evidence and noisy generated entries remain excluded by default if they appear in git status.

## Primary Change Areas

### Installable RC Runtime

- Bundled pack data under `engine/_data/packs/`
- Installed wheel catalog resolution
- Demo project fixture generation
- Fresh install smoke script

Review focus:
- installed wheel can find pack catalog and manifests,
- `auth-bug-core` remains usable from source and wheel,
- smoke script does not depend on `PYTHONPATH`.

### AI Company Runtime

- Authority mode
- Auto mode
- Boardroom, plan, run, report, release gate
- Role-specific result contracts
- Evidence-based handoff and next-iteration flow

Review focus:
- proposal-only remains the safe default,
- full authority is explicit only,
- auto run does not mutate source code by itself,
- release gate uses current evidence rather than stale blockers.

### Conversational Harness / Workforce / Skill System

- Project scan and harness profile
- Interview answers
- Harness engineering design/review/dry-run
- Workforce generation
- Skill generation
- Job start with selected agents and skills
- Evolution proposals and confirm-gated apply

Review focus:
- custom harness is the default direction,
- presets are optional seeds only,
- install requires approval,
- dispatch happens on demand, not at install time.

### Pack And Template Systems

- Pack catalog/install/readiness/proof/release/trust flows
- TypeScript/Jest auth harness compatibility
- Template qualification, challenge, canary, rollback, and library policy

Review focus:
- advanced systems do not override the primary local-first safety model,
- compatibility gates prevent wrong preset installation,
- test suite is split-run gated because the broad suite is long.

### Launch / Pilot / Release Docs

- Public demo and launch assets
- Private pilot outreach and learning board
- Dogfood and RC verification docs
- Split-run regression gate

Review focus:
- no fake proof claims,
- no private participant data,
- launch copy does not promise marketplace, payment, cloud execution, or provider API automation.

## Validation Evidence

Latest evidence recorded in this worktree:

- Installed wheel smoke: PASS
- Packaging and launch focused gate: `61 passed`
- Auto runtime focused gate: `93 passed`
- Harness/company focused split groups: `132 passed`
- Broad split-run chunks: 1413 passed, 14 skipped before template isolation
- Template isolation group: `73 passed`
- Final broad chunk: `62 passed`
- Auto/release regression subset after stale blocker fixes: `48 passed`
- Split-run gate doc subset: `29 passed`
- Latest auto release gate: GO
- `.cambrian/auto/report.yaml` open blockers: `0`
- Auto report source code modified: `false`

## Release Blocking Checklist

- [x] `python scripts/smoke_installed_wheel.py` is PASS.
- [x] Split-run regression evidence has no failed chunk.
- [x] `docs/release/SPLIT_RUN_REGRESSION_GATE.md` is current.
- [x] `.cambrian/auto/report.yaml` has no open blockers.
- [x] `.cambrian/auto/release_gate/*.yaml` latest verdict is GO.
- [x] No source code was automatically patched by auto mode.
- [x] `.env`, API keys, private usernames, and private project data are not included in release candidate docs or tests.

## Review Order

1. Review packaging and installed wheel path resolution.
2. Review authority/auto mode safety invariants.
3. Review harness/workforce/skill creation and install approval gates.
4. Review pack/template advanced surfaces for accidental launch-surface creep.
5. Review launch/release docs for overclaims.
6. Run split-run regression gates instead of a single long full pytest command.

## Known Non-Blocking Risks

- A single `python -m pytest -q` command can exceed local interactive timeout.
- The split-run evidence baseline must be refreshed after major test additions.
- The worktree is intentionally large and should be committed in coherent slices, not as one opaque mega-commit.

## Suggested Commit Slices

- `feat(packaging): 설치형 wheel pack catalog 경로 안정화`
- `feat(auto): authority and auto company runtime 추가`
- `feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가`
- `feat(pack): pack/template qualification and release surfaces 추가`
- `docs(launch): launch pilot release 문서 정리`
- `test(release): split-run regression gate 고정`
