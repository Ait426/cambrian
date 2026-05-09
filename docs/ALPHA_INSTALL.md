# Cambrian Alpha Install

160R 기준 Cambrian은 project-specific harness installer + agent dispatch runtime이다.

기본 설치/작업 흐름:

```bash
cambrian project scan
cambrian harness plan
cambrian harness install
cambrian agent dispatch "로그인 에러 수정해"
```

`auth-bug-core`는 첫 built-in harness preset으로 유지한다.

Cambrian은 AI Worker Installer다. 설치 후 로컬 Cambrian runtime이 프로젝트에 worker/team/template/lane pack을 입히고, 실제 작업과 검증은 로컬에서 수행한다.

웹은 control plane이고, 로컬 Cambrian이 runtime이다. 이 alpha install 문서는 로컬 실행 기준만 다룬다.

## Current strongest lane

```text
Python + pytest + auth/login narrow bug fix
test-first
narrow-scope
review-support
```

기본값:

- Default team: `auth-bug-team`
- Default template: `auth-bug-template`
- Default workset: `auth-bug-workset`

## 1. Local editable install

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e .[dev]
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
```

## 2. Doctor

```bash
cambrian doctor
```

`doctor`는 Python, dependency, CLI import, pytest, workspace write, project mode 상태를 확인한다.

## 3. Demo smoke

```bash
cambrian demo create login-bug --out ./cambrian-login-demo
cd ./cambrian-login-demo
cambrian init --wizard --answers-file demo_answers.yaml
cambrian do "로그인 정규화 버그 수정해"
cambrian status
```

데모는 source를 바로 바꾸지 않는다. diagnose, proposal, validation을 먼저 만들고, explicit apply/adoption 단계에서만 실제 source 변경이 일어난다.

## 4. local-only safety

- cloud telemetry 없음
- cloud source execution 없음
- automatic adoption 없음
- source 변경 전 file-first evidence 생성
- apply/adoption에는 사람의 명시적 이유 필요

## 5. Optional build smoke

```bash
python -m build
python -m pip wheel . --no-deps -w ./dist
python scripts/alpha_smoke_install.py
```
