# Cambrian RC Verification

## Verification Date

2026-05-25

## Environment

- OS: Windows
- Python: 3.14.2
- Install mode: fresh venv installed wheel
- Wheel: `dist/cambrian-0.3.0-py3-none-any.whl`

## Commands

```bash
python scripts/smoke_installed_wheel.py
```

Latest local evidence path:

```text
.launch_runs/installed_wheel_latest
```

Latest local re-run:

```text
python scripts/smoke_installed_wheel.py -> PASS
python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_launch_golden_path.py tests/test_launch_surface.py tests/test_launch_go_no_go.py tests/test_public_demo_kit.py tests/test_packaging_slice_ready.py -> 40 passed
```

## Result

PASS

## Step Results

| Step | Result | Notes |
| --- | ---: | --- |
| build wheel | PASS | `python -m build` 우선, 실패 시 pip wheel fallback |
| create venv | PASS | `venv.EnvBuilder` |
| install wheel | PASS | fresh venv |
| cambrian --help | PASS | pack-first help surface |
| cambrian doctor | PASS | installed entrypoint |
| demo create | PASS | `login-bug` fixture 생성 |
| pack list | PASS | bundled `auth-bug-core` catalog 확인 |
| pack show auth-bug-core | PASS | bundled manifest 확인 |
| install pack | PASS | local project install state 생성 |
| activate pack | PASS | active pack 설정 |
| pack start | PASS | pack job/packet 생성 |
| job-ingest | PASS | `fixtures/ai_reply_patch_candidate.yaml` canned AI reply fixture ingest |
| job-validate | PASS | pytest 기반 validation handoff |

## Open Risks

- Auth Bug Core validation은 Python + pytest lane이므로 사용자 프로젝트에도 pytest가 필요합니다.
- proof export, remote registry, marketplace, cloud execution은 이 RC의 핵심 경로가 아닙니다.
