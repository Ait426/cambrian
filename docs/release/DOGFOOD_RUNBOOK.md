# Cambrian Dogfood Runbook

## 1. Purpose

설치형 Cambrian RC를 실제 Python + pytest 프로젝트에서 사용해 Auth Bug Core 작업 흐름이 실무에 쓸 수 있는지 확인한다.

이번 dogfood는 데모 프로젝트를 다시 돌리는 검증이 아니다. `examples/auth_bug_demo`는 smoke fixture이고, 실제 dogfood PASS로 사용할 수 없다.

## 2. Preconditions

- Task 159R-1 PASS
- Task 159R-2 PASS
- `python scripts/smoke_installed_wheel.py` PASS
- fresh install에서 `auth-bug-core` pack list/show/install/activate/start PASS

사전 smoke:

```bash
python scripts/smoke_installed_wheel.py
```

## 3. Target project requirements

- Python 프로젝트
- pytest 또는 equivalent test command 존재
- auth/login 관련 버그 또는 실패 테스트 존재
- 작업 전 git clean 상태 권장
- 원본 프로젝트 직접 수정 금지, 복사본에서 실행 권장
- examples/auth_bug_demo는 dogfood 대상이 아님

대상 지정:

```bash
set CAMBRIAN_DOGFOOD_TARGET=C:\path\to\real-python-pytest-auth-project
```

또는:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\real-python-pytest-auth-project
```

## 4. Install Cambrian RC

README와 `RC_INSTALL_GUIDE.md`의 local wheel 설치 흐름을 사용한다.

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
```

## 5. Prepare target project

권장:

```bash
git status --short
python -m pytest -q
```

dirty tree면 dogfood report에 기록한다. git repo가 아니어도 실행은 가능하지만 source protection evidence가 약해진다.

## 6. Run Auth Bug Core

```bash
cambrian doctor
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
cambrian pack start "로그인 에러 수정해"
```

자동화:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\target
```

AI reply가 없으면 결과는 `WAITING_FOR_AI_REPLY`다. 이 상태는 실패가 아니다.

## 7. Capture AI reply

이번 RC는 AI provider API를 호출하지 않는다.

허용 흐름:

1. `cambrian pack start "로그인 에러 수정해" --json > .cambrian/dogfood/job_start.json`
2. 사용자가 packet을 기존 AI 도구에 붙여넣음
3. AI 응답을 YAML 파일로 저장
4. `cambrian pack job-ingest`로 다시 넣음

## 8. Ingest AI reply

```bash
cambrian pack job-ingest latest ./ai_reply_patch_candidate.yaml --json
```

스크립트 실행:

```bash
python scripts/dogfood_auth_bug_run.py --target C:\path\to\target --ai-reply C:\path\to\ai_reply_patch_candidate.yaml
```

## 9. Validate job

```bash
cambrian pack job-validate latest --json
```

validation이 실패하면 아래 중 하나로 분류한다.

- AI_REPLY_FORMAT_FAILURE
- JOB_INGEST_FAILURE
- JOB_VALIDATE_FAILURE
- VALIDATION_NOT_TRUSTWORTHY
- OUTPUT_NOT_ACTIONABLE

## 10. Evaluate result

사람이 직접 평가한다.

- 다음 명령이 명확했는가?
- 출력이 actionable 했는가?
- 결과가 useful patch/test 방향을 제시했는가?
- validate 결과를 믿을 수 있는가?
- 헷갈린 지점은 무엇인가?

## 11. Failure handling

실패 분류:

- INSTALL_FAILURE
- DOCTOR_FAILURE
- PACK_CATALOG_FAILURE
- PACK_INSTALL_FAILURE
- PACK_ACTIVATE_FAILURE
- PACK_START_FAILURE
- AI_REPLY_FORMAT_FAILURE
- JOB_INGEST_FAILURE
- JOB_VALIDATE_FAILURE
- OUTPUT_NOT_ACTIONABLE
- VALIDATION_NOT_TRUSTWORTHY
- USER_FLOW_CONFUSING

P0은 install/activate/start/ingest/validate가 실제 target에서 반복 실패하는 경우다. P1은 흐름은 되지만 사용자가 다음 행동을 이해하지 못하는 경우다. P2는 문구/문서/fixture 개선이다.

## 12. What counts as PASS

- 실제 Python + pytest auth/login 프로젝트를 target으로 사용
- `doctor`, `pack list`, `pack show`, `install`, `activate`, `pack start` 통과
- job id 추출
- AI reply가 있으면 `job-ingest`와 `job-validate`까지 통과
- 원본 프로젝트 source file 자동 수정 없음
- `DOGFOOD_REPORT.md` 작성

## 13. What counts as FAIL

- target 없이 demo fixture로 PASS 처리
- `examples/auth_bug_demo`를 dogfood target으로 사용
- install/activate/start 중 하나 실패
- job id 추출 실패
- AI reply가 있는데 ingest/validate 실패 원인을 설명하지 못함
- source code 자동 apply 발생
- provider API key나 외부 네트워크가 필수인 상태
