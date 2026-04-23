# Cambrian Alpha Install

Cambrian 알파는 로컬 전용 설치 흐름을 기준으로 안내합니다.
외부 telemetry, cloud login, PyPI publish는 이번 범위에 포함되지 않습니다.

## 1. Local Editable Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## 2. Doctor

설치가 끝나면 먼저 환경을 점검합니다.

```bash
cambrian doctor
```

`cambrian doctor`는 아래를 확인합니다.

- Python 3.11+
- CLI import 가능 여부
- 필수 의존성 `yaml`, `jsonschema`
- `pytest` 사용 가능 여부
- workspace 쓰기 가능 여부
- project mode 초기화 상태
- demo create 사용 가능 여부

## 3. Demo Smoke

```bash
cambrian demo create login-bug --out ./demo
cd ./demo
cambrian init --wizard --answers-file demo_answers.yaml
cambrian do "로그인 정규화 버그 수정해"
```

길을 잃으면 언제든 아래 명령으로 현재 상태를 다시 확인합니다.

```bash
cambrian status
```

## 4. Notes

- Cambrian은 local-only 흐름을 기준으로 합니다.
- automatic adoption은 기본으로 꺼져 있습니다.
- 실제 source 수정은 explicit apply 단계에서만 일어납니다.
- apply에는 반드시 사람이 적은 `--reason`이 필요합니다.
- project mode의 기본 경로는 `cambrian do`와 `cambrian do --continue`입니다.

## 5. Optional Build Smoke

로컬 빌드 sanity를 보고 싶다면:

```bash
python -m build
# 또는
python -m pip wheel . --no-deps -w ./dist
python scripts/alpha_smoke_install.py
```
