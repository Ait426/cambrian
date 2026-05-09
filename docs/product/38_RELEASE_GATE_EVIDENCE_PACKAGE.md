# Release Gate Evidence Package

## 목적

`quality_route=release_gate`까지 온 strong auto result를 실제 출시 판단 패키지로 닫는다.

이 단계는 코드를 배포하거나 source file을 수정하지 않는다. Cambrian은 release manager가 판단할 수 있는 evidence package를 `.cambrian/auto/release_gate/`에 저장한다.

## 명령

```bash
cambrian auto release-gate --json
```

## 입력

`auto release-gate`는 다음 evidence를 읽는다.

```text
.cambrian/auto/report.yaml
.cambrian/auto/plan.yaml
.cambrian/auto/execution_log.yaml
.cambrian/auto/external_results/*.yaml
```

## 출력

생성 파일:

```text
.cambrian/auto/release_gate/release-gate-*.yaml
```

핵심 필드:

```text
verdict
reason
quality_route
quality.score
quality.status
evidence_checklist
required_before_release
deferred_after_release
safety
```

## Verdict

가능한 판정:

```text
GO
CONDITIONAL GO
NO-GO
```

V1 판정 규칙:

```text
GO:
  - validated result 있음
  - quality_route=release_gate
  - result_quality.status=strong
  - test evidence 있음
  - evidence notes 또는 artifacts 있음
  - open blocker 없음
  - release-manager-agent가 release gate plan을 시작
  - source_code_modified=false

CONDITIONAL GO:
  - validated result는 있으나 release gate evidence 일부가 비어 있음
  - 또는 usable result라 다음 product step/review가 필요함

NO-GO:
  - validated result 없음
  - quality score가 threshold 미만
  - release 판단에 필요한 evidence가 부족함
```

## Safety

`auto release-gate`는 자동 release가 아니다.

금지:

```text
source code 수정
provider API 호출
자동 배포
자동 git commit/tag
secret 사용
```

이 명령은 local `.cambrian/auto` metadata만 생성한다.
