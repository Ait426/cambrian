# Runtime Evidence Archive Slice Readiness

## Purpose

This document records the readiness of the seventh recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 7 covers the release decision evidence produced by the local Cambrian auto loop. The default policy is not to commit the full `.cambrian/` runtime tree. Instead, preserve the final release evidence summary in `docs/release/` and only commit selected `.cambrian/auto` artifacts if an explicit evidence-artifact commit is intended.

## Slice

Suggested commit:

```text
docs(evidence): Cambrian auto loop evidence archive
```

## Include

Default include:

- `docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md`
- `docs/release/RC_CHECKLIST.md`
- `tests/test_runtime_evidence_archive_slice_ready.py`

Optional include only for an explicit evidence artifact commit:

- selected `.cambrian/auto/iterations/`
- selected `.cambrian/auto/release_gate/`
- selected `.cambrian/auto/report.yaml`

## Do Not Include

- full `.cambrian/` runtime tree by default
- `.cambrian/jobs/` local project job contents
- private project paths, user data, or raw external AI replies
- `.env` or secret files
- `.env or secret files` must remain excluded even for an explicit evidence artifact commit
- pycache directories such as `tools/__pycache__/`
- unrelated source, web, pack, harness, launch, or packaging changes

## Evidence Summary

The current staged evidence policy is summary-first:

```text
Commit docs/release summaries by default.
Do not commit the raw .cambrian runtime evidence tree unless the commit is explicitly scoped as an evidence archive.
```

Selected release gate evidence:

| Slice | Area | Release Gate | Verdict |
|---|---|---:|---|
| Slice 1 | Packaging RC Runtime | `release-gate-20260509-162228` | GO |
| Slice 2 | AI Company Auto Runtime | `release-gate-20260509-162905` | GO |
| Slice 3 | Harness Workforce Skill | `release-gate-20260509-163438` | GO |
| Slice 4 | Pack Template Benchmark | `release-gate-20260509-171309` | GO |
| Slice 5 | Launch Pilot Release Docs | `release-gate-20260509-173239` | GO |
| Slice 6 | Web Tools | `release-gate-20260509-174102` | GO |

Latest current release gate:

```text
release-gate-20260509-174102
Verdict: GO
Reason: Strong validated result has release gate evidence.
Quality score: 95
Required before release: none
```

## Validation

Slice 7 validates the evidence archive policy rather than product runtime behavior.

### Prior Slice Gates

Completed slice readiness gates:

```text
Packaging Slice Gate: PASS
Auto Runtime Slice Gate: PASS
Harness Workforce Skill Slice Gate: PASS
Pack Template Benchmark Slice Gate: PASS
Launch Pilot Release Docs Slice Gate: PASS
Web Tools Slice Gate: PASS
```

### Evidence Archive Test Gate

```bash
python -m pytest -q tests/test_runtime_evidence_archive_slice_ready.py
```

Expected result:

```text
PASS
```

## Review Notes

- Runtime evidence is useful for local audit, but it is noisy and should not be mixed into normal source commits.
- Summary docs are the stable release record for review.
- If raw `.cambrian/auto` files are committed, that must be a separate explicit evidence artifact commit.
- The evidence archive slice must not introduce product runtime behavior.
- The evidence archive slice must not call provider APIs, deploy, access secrets, or apply source patches.

## Slice Verdict

GO for review/staging as Slice 7, provided the staged diff contains only the evidence archive summary, RC checklist update, and the evidence archive test unless an explicit evidence artifact commit is requested.
