# IMPLEMENTATION_NOTES.md

## 변경 요약

| 파일 | 내용 |
|------|------|
| engine/exceptions.py | SymlinkSecurityError, InputContractError, SandboxEnforcementError 추가 |
| engine/models.py | ExecutionResult.failure_type 필드 추가 |
| engine/sandbox/sitecustomize.py | 네트워크/파일시스템 차단 bootstrap |
| engine/executor.py | _apply_sandbox_env() 추가, _execute_mode_b() 내 sandbox 적용 |
| engine/absorber.py | _verify_no_symlinks() 추가, absorb() 내 호출 |
| engine/loop.py | _run_competitive() 내 input contract gate 삽입 |
| engine/loader.py | Mode A SKILL.md 허용 필터 라인 제거 |

## 설계 결정

### Sandbox: Python-level bootstrap injection
OS-level sandbox 미구현. engine/sandbox/sitecustomize.py를 PYTHONPATH prepend로 주입.
sitecustomize.py는 `python script.py`에서도 자동 로드됨 (PYTHONSTARTUP과 달리).
bootstrap 파일 누락 시 SandboxEnforcementError → fail-closed.

### builtins.open 패치 범위
Python 내부 import 로더는 C-level file ops 사용, builtins.open 패치 미영향.
스킬의 명시적 open() 호출만 차단. Python stdlib(sys.prefix) 허용.

### symlink: copytree 전 전수 검사
copytree 이전 검사로 부분 복사 후 실패(dirty pool 상태) 방지.

### InputContractError: failure_type 필드 방식
validate_input()의 list[str] 반환 타입 유지. failure_type="input_contract"으로 식별.
success=False 결과는 winner 선정에서 자동 제외.

### SKILL.md: filter 라인 제거만으로 구현
validator.py는 이미 SKILL.md 필수 검증 중.
loader.py의 Mode A 예외 처리 2줄 삭제로 완성.

## 알려진 한계
- C 확장의 network 호출은 socket 패치로 차단 불가
- os.open() 계열은 builtins.open 패치 범위 밖
- 향후 seccomp/bubblewrap 교체 시 engine/sandbox/ 내부만 수정하면 됨
