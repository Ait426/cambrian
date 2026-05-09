# Cambrian Project Mode Quickstart

## 0. 160R 기본 흐름

Project mode의 기본 spine은 이제 project-first다.

```bash
cambrian doctor
cambrian project scan
cambrian harness plan
cambrian harness install
cambrian agent dispatch "로그인 에러 수정해"
```

AI 응답을 받은 뒤에는 다음 경로를 사용한다.

```bash
cambrian job ingest latest ai_reply_patch_candidate.yaml
cambrian job validate latest
```

`auth-bug-core`는 첫 built-in harness preset이며, Cambrian 제품 본체가 아니다.

Project mode는 로컬 Cambrian runtime이 현재 프로젝트에 AI 일꾼, 작업반, template, lane playbook을 입히는 흐름이다.

Cambrian은 AI Worker Installer / AI 인력 설치기다. 내부적으로는 harness engineering runtime이며, 작업 결과를 evidence-based evolution engine으로 개선한다.

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

이 lane 밖에서는 warning과 추가 evidence를 더 중요하게 본다.

## 기본 흐름

```bash
cambrian init --wizard
cambrian run -d coding -t auth bug -i '{"request":"fix login bug"}'
cambrian do "fix the login bug"
cambrian do --continue
cambrian status
```

Legacy command compatibility:

```bash
cambrian patch propose
cambrian patch apply
```

## 1. Install loop

```bash
cambrian init --wizard
```

생성되는 주요 로컬 상태:

- `.cambrian/project.yaml`
- `.cambrian/rules.yaml`
- `.cambrian/profile.yaml`
- `.cambrian/templates/`

install은 source code를 바꾸지 않는다.

## 2. Work loop

```bash
cambrian do "로그인 정규화 버그 수정해"
cambrian do --continue --use-suggestion 1 --execute
```

Cambrian은 project memory, context scan, diagnosis, related tests를 사용한다. source 변경 전에는 evidence artifact만 만든다.

## 3. Validation loop

```bash
cambrian do --continue --old-choice old-1 --new-text "return username.strip().lower()" --validate
```

patch intent, proposal, isolated validation을 만든다. source는 아직 변경되지 않는다.

## 4. Explicit apply/adoption

```bash
cambrian do --continue --apply --reason "normalize username before login"
```

검증된 proposal만 적용하고, post-apply test와 adoption record를 남긴다.

## 5. Proof and evolution

```bash
cambrian metrics week
cambrian benchmark replay-workset auth-bug-workset
cambrian benchmark proof auth-bug-workset
cambrian template canary-report
```

metrics/proof/canary는 자동 승격이 아니라 운영 판단 근거다.

## Source-of-truth reminder

- Web control plane: catalog, recommendation, install manifest
- Local runtime: 실제 install/work/validation/replay/canary/rollback
- `.cambrian/`: file-first state와 derived evidence
- source code: explicit apply/adoption 전에는 변경하지 않음

## 다음 문서

- [Product doctrine](product/00_INDEX.md)
- [First-run demo](FIRST_RUN_DEMO.md)
- [Alpha install](ALPHA_INSTALL.md)
