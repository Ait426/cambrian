# Packaging RC Runtime Slice Readiness

## Purpose

This document records the readiness of the first recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 1 covers the installable RC runtime and pack catalog behavior needed for Cambrian to work from a built wheel.

## Slice

Suggested commit:

```text
fix(packaging): 설치형 wheel pack catalog 경로 안정화
```

## Include

- `pyproject.toml`
- `engine/_data_path.py`
- `engine/_data/packs/`
- `engine/project_pack_catalog.py`
- `engine/project_pack_dependencies.py`
- `engine/project_pack_readiness.py`
- `engine/project_pack_install.py`
- `engine/demo_project.py`
- `scripts/smoke_installed_wheel.py`
- packaging, catalog, install, readiness, and launch golden path tests

## Do Not Include

- auto mode source files
- harness/workforce/skill source files
- launch copy unrelated to installation
- `.cambrian/` runtime evidence unless intentionally committing evidence
- private local project files
- `.env` or secret files

## Validation

### Installed Wheel Smoke

```bash
python scripts/smoke_installed_wheel.py
```

Result:

```text
Result: PASS
```

Smoke summary path:

```text
.launch_runs/installed_wheel_latest
```

### Packaging Test Gate

```bash
python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_alpha_packaging.py tests/test_pack_catalog.py tests/test_pack_install.py tests/test_pack_readiness.py tests/test_launch_golden_path.py tests/test_launch_surface.py tests/test_packaging_slice_ready.py
```

Result:

```text
64 passed in 87.59s
```

## Review Notes

- Wheel install sees bundled pack catalog data.
- Installed-wheel smoke writes its temporary wheel build output under `.launch_runs/installed_wheel_latest/wheel-build-dist` and does not delete release `dist/` artifacts.
- Extracted wheel pack list/show works without source tree `packs/`.
- Demo project includes `fixtures/ai_reply_patch_candidate.yaml`.
- Auth Bug Core golden path remains the packaging smoke lane.
- No remote registry, marketplace, payment, provider API, cloud execution, or automatic patch apply is part of this slice.

## Slice Verdict

GO for review/staging as Slice 1, provided the staged diff matches only the intended files.
