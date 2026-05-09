# Cambrian Studio

## 1. 한 줄 정의

Cambrian Studio는 브라우저에서 AI 에이전트 실행 계약을 만들고, 로컬 Cambrian Runtime에 설치 가능한 pack manifest로 내보내는 제작 화면이다.

```text
Studio creates the contract.
Local Cambrian Runtime installs, runs, validates, proves, and evolves it.
```

## 2. 현재 구현 범위

현재 Studio는 클라우드 SaaS가 아니다.

현재 구현은 정적 웹 표면이다.

```text
web/studio/index.html
```

지원하는 첫 vertical은 문서 정리 에이전트다.

사용자는 브라우저에서 아래를 입력한다.

- 에이전트 이름
- 제작자
- 맡길 일
- 문서 유형
- 결과물 형식
- 금지 행동
- 승인 필요한 행동
- 검증 기준
- known limits

Studio는 이 입력을 Cambrian pack manifest 형태로 만든다.

```text
<agent-id>.cambrian-pack.yaml
```

다운로드한 manifest는 로컬 프로젝트에서 아래 명령으로 설치한다.

```bash
cambrian install manifest ./document-organizer-agent.cambrian-pack.yaml
```

## 3. Agent Contract

Studio의 첫 핵심 단위는 Cambrian Agent Contract다.

에이전트는 프롬프트가 아니라 실행 계약이다.

계약에는 아래가 포함된다.

- role
- goals
- input / output assumptions
- permissions
- forbidden actions
- approval-required actions
- validation criteria
- proof seed
- evolution signals
- known limits
- marketplace 준비 metadata

현재 manifest에서는 `pack_kind: agent`와 `template_kind: agent_contract`로 표현한다.

## 4. Preflight Proof

Studio의 첫 검증은 성능 proof가 아니다.

실행 전에는 성공률, 사용자 수정률, 검증 통과율을 알 수 없다.

따라서 Studio는 `preflight_only` proof만 보여준다.

Preflight proof가 확인하는 것:

- 필수 계약 완성도
- 권한 위험도
- 금지 행동 존재 여부
- 승인 필요 행동 존재 여부
- 검증 기준 존재 여부
- 실제 runtime evidence가 아직 없다는 사실

금지:

- 실행 전 성공률 주장
- `validated_proposal_rate` 숫자 표시
- `100% success` 같은 가짜 proof 문구
- public proof 자동 생성

## 5. Runtime Boundary

Studio는 manifest를 만든다.

로컬 Cambrian Runtime은 아래를 담당한다.

- install
- dry-run
- job start
- validation
- proof card
- evolution proposal
- approval-based evolution apply
- rollback

즉 Studio는 제작 화면이고, Runtime은 현장 엔진이다.

## 6. Evolution Gate

Studio에서 만든 agent는 실행 데이터가 없으면 proof card가 `insufficient_data`로 시작한다.

이 상태는 자동 진화로 이어지지 않는다.

현재 연결된 흐름은 아래와 같다.

```text
Studio agent install
→ local proof card 생성
→ runtime evidence gap 감지
→ improvement queue에 first-job guide 제안
→ 사용자 accept 기록
→ derivative plan에서 vNext 후보 생성
```

핵심 원칙:

- proof gap은 제안만 만든다.
- vNext 계획은 사용자 승인 기록이 있어야 열린다.
- 첫 구현은 `improve_first_job_guide` → `first_job_guide_update`로 제한한다.
- 실제 성능 개선 주장은 runtime job evidence가 생긴 뒤에만 가능하다.

## 7. Marketplace 준비 경계

Studio manifest에는 미래 마켓플레이스에 필요한 metadata를 일부 남긴다.

- author
- license
- provenance
- checksum 준비 필드
- signature 준비 필드
- public/private visibility
- proof status
- evolution lineage
- known limits

하지만 현재 Studio는 아래를 하지 않는다.

- 결제
- 정산
- 공개 랭킹
- 리뷰 시스템
- 클라우드 실행
- 원격 proof 업로드
- public marketplace publish

## 8. 안전 원칙

Studio에서 생성한 pack은 기본적으로 안전한 설치 정책을 가져야 한다.

```yaml
install:
  install_as_library: true
  auto_apply: false
  auto_bootstrap: false
  auto_promote: false
  auto_canary: false
```

금지 행동과 승인 필요 행동이 충돌하면 런타임 manifest loader가 차단한다.

## 9. 다음 단계

다음 단계는 정적 생성기를 넘어서 로컬 Runtime과 더 깊게 연결하는 것이다.

우선순위:

1. Studio-generated agent pack의 install / doctor / dry-run golden path 고정
2. agent contract 전용 proof card 초기화
3. job start에서 agent pack을 더 잘 선택하도록 dispatch 보강
4. runtime evidence 기반 proof card 업데이트
5. evolution review / propose가 agent contract metadata를 개선하도록 연결

현재 반영된 것:

1. Studio-generated agent pack의 install / proof / improvement gate golden path 고정
2. proof gap을 `improve_first_job_guide` 제안으로 변환
3. 사용자 accept 기록 후 derivative plan에서 `first_job_guide_update` vNext 후보 생성
4. `cambrian job start --pack <agent-pack>`로 Studio agent를 직접 dispatch
5. job start 직후 usage event와 local proof card 자동 갱신
6. bridge packet execution contract에 Studio agent worker를 `selected_agents`로 표시
7. agent contract의 `validation_criteria`, 금지 행동, 승인 필요 행동을 request packet과 validation evidence에 보존
8. proof card가 최신 validation evidence를 읽어 계약 검증 상태를 metric, claim, weakness로 표시
9. job validation 직후 proof card를 자동 갱신하고, 계약 검증 gap을 improvement queue와 derivative plan으로 연결
10. `cambrian pack job-validate latest --criteria-status satisfied`로 사람이 검증 기준 판정을 기록하면 최신 proof card가 `satisfied`로 갱신
11. 검증 기준이 남아 있으면 `job-validate` 결과의 next command와 `job-show`가 수동 판정 경로를 직접 안내

## 10. 최종 문장

Cambrian Studio는 마켓플레이스가 아니다.

Cambrian Studio는 마켓플레이스에 올릴 수 있는 신뢰 가능한 에이전트를 만들기 위한 제작소다.

```text
만드는 곳은 Studio.
실행하고 증명하는 곳은 Local Cambrian Runtime.
거래하는 곳은 미래 Marketplace.
```
