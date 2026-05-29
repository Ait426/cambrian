# PyPI Release

## Purpose

## Current Decision

PyPI is not the current external-user release path.

The current release path is the portable install kit and external alpha bundle. This PyPI lane stays prepared but deferred until the operator explicitly resumes it, provides local-only TestPyPI/PyPI tokens, verifies TestPyPI install, uploads to PyPI, and verifies fresh `pip install cambrian`.

Until then, do not claim that `pip install cambrian` works and do not make PyPI upload the default next task.

이 문서는 Cambrian을 `pip install cambrian`으로 설치할 수 있게 만드는 PyPI 배포 절차를 고정한다.

목표:

```text
1. dist/pypi/에 wheel과 sdist만 격리해서 빌드한다.
2. twine check를 통과한다.
3. TestPyPI에 먼저 업로드하고 설치를 확인한다.
4. 최종 PyPI에 업로드한다.
5. 다른 PC에서 pip install cambrian으로 설치 가능하게 만든다.
```

## Prepare

토큰 없이 가능한 준비/검증:

```bash
python scripts/prepare_pypi_release.py
```

이 명령은 임시 venv에 `build`와 `twine`을 설치하고, 아래를 수행한다.

```text
dist/pypi/ 정리
sdist/wheel 빌드
twine check
wheel metadata local path 검사
PyPI package name 조회
dist/pypi_release_receipt.json 생성
```

receipt 단독 재검증:

```bash
python scripts/prepare_pypi_release.py --verify-receipt dist/pypi_release_receipt.json
```

이 검증은 `dist/pypi/`의 wheel/sdist 파일명, bytes, sha256을 receipt와 다시 맞추고, receipt body hash, 절대경로 누락, command output 원문 누락, token placeholder 정책을 확인한다.

업로드 전 로컬 wheel fresh install smoke:

```bash
python scripts/verify_pypi_install.py --wheel dist/pypi/cambrian-0.3.0-py3-none-any.whl --repository pypi --version 0.3.0 --receipt dist/pypi_local_wheel_install_receipt.json
python scripts/verify_pypi_install.py --verify-receipt dist/pypi_local_wheel_install_receipt.json
```

업로드 전 TestPyPI preflight:

```bash
python scripts/prepare_pypi_release.py --preflight-upload testpypi
python scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json
python scripts/check_pypi_publish_ready.py --repository testpypi
python scripts/check_pypi_publish_ready.py --verify-ready dist/pypi-publish-ready-testpypi.json
```

토큰이 아직 없으면 status는 `ready_for_testpypi_token`이어야 한다. 이 상태는 업로드 가능 산출물과 local wheel fresh install은 통과했고, 남은 일이 로컬 토큰 설정뿐이라는 뜻이다.
토큰을 설정한 뒤에는 `python scripts/prepare_pypi_release.py --preflight-upload testpypi --require-token-env`가 `ready_to_upload_testpypi`를 반환해야 한다. receipt에는 토큰 값이 아니라 `twine_password_present=true`, `twine_password_recorded=false`만 남는다.
`check_pypi_publish_ready.py`는 같은 증거를 `WAITING_FOR_TOKEN`, `GO`, `BLOCKED` 중 하나로 묶고 `dist/pypi-publish-ready-testpypi.json`과 Markdown handoff를 만든다.

## TestPyPI Upload

토큰은 채팅에 붙여넣지 않는다.
로컬 터미널 환경변수로만 설정한다.

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=<testpypi-token> python scripts/prepare_pypi_release.py --upload testpypi --publish-ready-receipt dist/pypi-publish-ready-testpypi.json
```

Windows PowerShell:

```powershell
$env:TWINE_USERNAME="__token__"
$env:TWINE_PASSWORD="<testpypi-token>"
python scripts\prepare_pypi_release.py --upload testpypi --publish-ready-receipt dist\pypi-publish-ready-testpypi.json
Remove-Item Env:\TWINE_PASSWORD
```

Upload commands fail before build unless `TWINE_USERNAME=__token__` and `TWINE_PASSWORD` are present in the local environment.
Upload commands also fail before upload unless the matching publish-ready receipt has verdict `GO`.

TestPyPI 설치 확인:

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cambrian
cambrian --help
cambrian doctor --json
```

자동 검증:

```bash
python scripts/verify_pypi_install.py --repository testpypi --version 0.3.0 --receipt dist/pypi_testpypi_install_receipt.json
python scripts/verify_pypi_install.py --verify-receipt dist/pypi_testpypi_install_receipt.json
```

`dist/pypi_testpypi_install_receipt.json` is the required gate for final PyPI upload.

최종 PyPI preflight:

```bash
python scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json
python scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env
python scripts/check_pypi_publish_ready.py --repository pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env
python scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json
```

토큰이 아직 없으면 status는 `ready_for_pypi_token`이어야 한다. TestPyPI 설치 receipt가 없거나 같은 버전이 아니면 preflight는 blocked가 된다.
PyPI token이 로컬 환경변수에 있고 TestPyPI 설치 receipt가 검증되면 status는 `ready_to_upload_pypi`여야 한다. receipt에는 토큰 값이 아니라 `twine_password_present=true`, `twine_password_recorded=false`만 남는다.
blocked 상태도 `dist/pypi_publish_preflight_receipt.json`에 남아야 하며, TestPyPI 설치 receipt가 빠진 경우 `blocking_checks`는 `testpypi_install_receipt_verified`를 포함한다.

## PyPI Upload

TestPyPI 설치 확인 후에만 실행한다.

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=<pypi-token> python scripts/prepare_pypi_release.py --upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --publish-ready-receipt dist/pypi-publish-ready-pypi.json
```

Windows PowerShell:

```powershell
$env:TWINE_USERNAME="__token__"
$env:TWINE_PASSWORD="<pypi-token>"
python scripts\prepare_pypi_release.py --upload pypi --testpypi-install-receipt dist\pypi_testpypi_install_receipt.json --publish-ready-receipt dist\pypi-publish-ready-pypi.json
Remove-Item Env:\TWINE_PASSWORD
```

최종 설치 확인:

```bash
python -m pip install cambrian
cambrian --help
cambrian doctor --json
```

자동 검증:

```bash
python scripts/verify_pypi_install.py --repository pypi --version 0.3.0
```

## Safety Rules

- PyPI token을 채팅, 문서, git diff에 쓰지 않는다.
- 토큰을 채팅에 붙여넣지 않는다.
- `dist/*` 전체를 업로드하지 않는다. 업로드 대상은 `dist/pypi/*`뿐이다.
- `dist/pypi_release_receipt.json`은 `--verify-receipt`로 통과해야 한다.
- TestPyPI를 먼저 통과한다.
- 한번 업로드한 PyPI 버전은 덮어쓰지 않는다.
- dirty worktree에서 업로드하기 전에는 변경 범위를 다시 확인한다.
- 실제 업로드는 사용자 계정/토큰이 있을 때만 실행한다.
- 업로드 후 fresh venv 설치 검증 receipt를 남긴다.

- `--upload pypi` is blocked unless `dist/pypi_testpypi_install_receipt.json` verifies a same-version TestPyPI install.
- `--upload testpypi` and `--upload pypi` are blocked unless the matching `pypi-publish-ready-*.json` receipt has verdict `GO`.
- TestPyPI/PyPI upload commands fail before build when `TWINE_PASSWORD` is missing or `TWINE_USERNAME` is not `__token__`.

## Current Package

```text
name: cambrian
version: 0.3.0
entrypoint: cambrian
requires-python: >=3.11
license: MIT
```

## References

- PyPI upload API: https://docs.pypi.org/api/upload/
- twine: https://pypi.org/project/twine/
