# Cambrian Agent Marketplace Future

## 1. 문서 위치

이 문서는 Cambrian의 현재 제품 정의를 바꾸기 위한 문서가 아니다.

현재 Cambrian의 중심은 여전히 다음이다.

```text
Cambrian is an installable AI company runtime.
Every project becomes an AI company.
```

이 문서는 그 위에 가능한 장기 미래 중 하나를 고정한다.

```text
Cambrian은 AI 에이전트를 만들고, 고용하고, 실행하고, 검증하고, 진화시키고, 거래하는 신뢰 기반 플랫폼이 될 수 있다.
```

## 2. 핵심 통찰

단순 AI 에이전트 마켓플레이스는 복제되기 쉽다.

진짜 해자는 에이전트 목록이 아니라 다음이다.

- 실행 런타임
- 검증 시스템
- proof card
- 진화 이력
- 권한과 안전 경계
- 라이선스와 정품 실행권
- 익명화된 outcome evidence
- 제작자와 사용자 사이의 신뢰 네트워크

따라서 Cambrian의 장기 방향은 단순한 에이전트 쇼핑몰이 아니라, AI 노동시장의 신뢰 운영체계가 되는 것이다.

## 3. 사용자와 플랫폼의 분리

이 미래에서 사용자와 Cambrian은 같은 위치에 있지 않다.

사용자는 에이전트를 만든다.
사용자는 에이전트를 고용한다.
사용자는 에이전트를 실행한다.
사용자는 에이전트를 평가한다.

Cambrian은 그 위에서 다음을 관리한다.

- 에이전트의 출생
- 에이전트의 정의와 권한
- 에이전트의 실행 조건
- 에이전트의 검증 결과
- 에이전트의 진화 이력
- 에이전트의 유통과 라이선스
- 에이전트 제작자의 수익화

한 문장으로:

```text
사용자는 AI 직원을 만들고 고용한다.
Cambrian은 그 AI 직원의 자격, 실행, 성과, 진화, 거래를 관리한다.
```

## 4. 세 종류의 사용자

### 4.1 구매자 또는 고용자

AI를 잘 몰라도 필요한 에이전트를 찾고 고용한다.

예:

- 쇼핑몰 CS 에이전트
- 문서 정리 에이전트
- 엑셀 정리 에이전트
- 블로그 기획 에이전트
- 개발 프로젝트 보조 에이전트

### 4.2 제작자

에이전트를 만들고, 검증하고, 진화시킨 뒤 판매한다.

제작자의 수익은 단순 다운로드 수가 아니라 검증된 성과와 지속 사용에 연결되어야 한다.

### 4.3 기업 또는 팀 사용자

조직 내부에서 private agent registry를 운영한다.

필요한 것:

- 권한 관리
- 감사 로그
- private registry
- 팀 승인 흐름
- 보안 정책
- proof export 통제

## 5. 장기 제품 구조

```text
Browser Platform
-> agent builder
-> hiring marketplace
-> signed pack distribution
-> Cambrian Runtime
-> execution
-> validation
-> proof
-> evolution
-> marketplace update
```

브라우저는 사용자가 에이전트를 만들고 고용하는 표면이다.

로컬 Cambrian Runtime은 실제 실행, 검증, 로그, proof, 진화를 담당한다.

AI 모델은 두뇌다.
Cambrian은 두뇌 위에 역할, 권한, 검증, 진화, 라이선스 체계를 입히는 운영체계다.

## 6. 비개발자용 에이전트 생성 환경

사용자는 프롬프트, API, 토큰, 모델을 몰라도 에이전트를 만들 수 있어야 한다.

빌더는 질문형이어야 한다.

예:

```text
어떤 일을 맡기고 싶나요?
어떤 결과물이 좋아야 하나요?
어떤 행동은 금지해야 하나요?
실행 전 승인이 필요한 행동은 무엇인가요?
어떤 파일이나 서비스에 접근할 수 있나요?
결과는 어떻게 검증해야 하나요?
```

빌더의 결과물은 단순 프롬프트가 아니어야 한다.

결과물은 Cambrian agent contract 또는 Cambrian pack이어야 한다.

포함해야 할 것:

- role
- goals
- permissions
- forbidden actions
- validation rules
- risk gates
- expected outputs
- evolution signals
- known limits
- version
- license
- provenance

## 7. 새 언어가 아니라 실행 계약

복사 방지만을 위해 새 프로그래밍 언어를 만드는 것은 우선순위가 아니다.

대신 Cambrian 전용 에이전트 실행 계약이 필요하다.

가능한 이름:

- Cambrian Agent Manifest
- Cambrian Runtime Contract
- Cambrian Pack Language
- Cambrian Evolution Contract

핵심은 다음이다.

```text
에이전트는 프롬프트가 아니라 권한, 검증, 실행 조건, 진화 신호를 가진 계약이다.
```

프롬프트만 복사해도 핵심 상품 가치는 복사되지 않아야 한다.

## 8. 진화 데이터 네트워크

Cambrian이 장기적으로 강해지는 이유는 에이전트 실행에서 생기는 outcome evidence다.

수집해도 되는 데이터는 원문 데이터가 아니라 구조화된 성과 증거여야 한다.

수집 후보:

- 실행 성공 여부
- 실패 단계
- 검증 통과 여부
- 사용자 수정 여부
- 사용자 채택 여부
- 위험 행동 차단 여부
- 평균 실행 비용
- 평균 처리 시간
- 반복 실패 패턴
- 진화 전후 지표 변화

기본 원칙:

```text
Raw data는 로컬에 둔다.
플랫폼은 사용자가 동의한 익명 outcome evidence만 받는다.
```

수집하면 안 되는 것:

- 원본 코드
- 고객 문서 원문
- 개인정보
- API 키
- 계약서 원문
- 메일 원문
- 결제 정보 원문
- 비밀 값

## 9. 진화 표시 방식

에이전트 판매 페이지는 단순 리뷰보다 proof를 중심으로 해야 한다.

예:

```text
이 에이전트는 42회 진화했습니다.

검증 결과:
- 작업 성공률: 87%
- 사용자 수정률: 낮음
- 위험 행동 차단률: 100%
- 평균 실행 비용: 320 credits
- 최근 개선: 환불 문의 분류 정확도 향상
```

중요한 것은 진화 횟수 자체가 아니다.

진짜 중요한 것은 진화가 어떤 실패를 줄였고 어떤 지표를 개선했는지다.

## 10. 정품 실행권과 복사 방지

완벽한 복사 방지는 불가능하다.

명품에도 짝퉁이 있고, 소프트웨어에도 크랙이 있다.
에이전트도 일부는 복사될 수 있다.

따라서 전략은 복사 차단이 아니라 정품을 쓸 이유를 압도적으로 크게 만드는 것이다.

정품이 가져야 할 가치:

- 공식 실행 권한
- signed Cambrian pack
- 공식 proof score
- 공식 진화 이력
- 정품 업데이트
- rollback
- 제작자 지원
- 라이선스
- 팀 감사 로그
- 마켓 노출
- 수익 정산

복사본이 잃어야 할 것:

- 공식 검증 점수
- 공식 진화 이력
- 업데이트 채널
- 마켓 신뢰
- 제작자 수익
- 기업용 인증
- Cambrian proof badge

한 문장으로:

```text
에이전트 파일은 복사될 수 있지만, 에이전트의 신뢰와 진화 이력은 복사되지 않아야 한다.
```

## 11. 마켓 연동을 지금 구현하지 않는 이유

지금의 우선순위는 마켓플레이스 구현이 아니다.

지금 완성해야 하는 것은 Cambrian Runtime의 골든 패스다.

```text
pack 선택
-> 설치
-> job 실행
-> 결과 검증
-> proof 생성
-> 실패 기록
-> 진화 제안
-> 승인 후 진화
-> vNext pack 생성
```

마켓은 이 흐름 위에 올라가는 2층이다.

1층이 약하면 마켓은 단순 프롬프트 장터가 된다.

## 12. 하지만 지금부터 박아야 할 계약

마켓 기능은 나중에 만들더라도, 마켓이 요구할 계약은 지금부터 설계에 포함해야 한다.

필수 metadata:

- pack id
- version
- author
- license
- checksum
- signature 준비 필드
- provenance
- compatibility
- proof status
- known limits
- public/private visibility
- evolution lineage
- rollback hints
- install manifest
- usage/outcome evidence refs

지금 하면 안 되는 것:

- 결제
- 판매자 정산
- 공개 랭킹
- 리뷰 시스템
- 복잡한 SaaS 계정
- 원격 실행
- 클라우드 코드 분석
- 자동 업로드
- 과도한 DRM

## 13. 비즈니스 모델

가능한 수익 구조:

- 무료 로컬 런타임
- Pro 구독
- Team private registry
- Enterprise local appliance
- 유료 pack 판매 수수료
- proof 검증 수수료
- 제작자 수익화
- signed registry access
- 기업용 감사와 권한 관리

핵심 판매 단위는 에이전트 파일이 아니다.

핵심 판매 단위는 다음이다.

```text
검증된 실행권
진화하는 작업반
신뢰 가능한 proof
반복 사용으로 좋아지는 AI 노동력
```

## 14. 장기 해자

Cambrian의 해자는 다음 순서로 쌓인다.

```text
로컬 실행 신뢰
-> proof card
-> 에이전트 진화 이력
-> signed pack
-> creator ecosystem
-> outcome evidence network
-> private registry
-> proof-backed marketplace
```

순서를 바꾸면 위험하다.

마켓을 먼저 만들면 복제 가능한 장터가 된다.
런타임과 proof를 먼저 만들면 따라잡기 어려운 신뢰 네트워크가 된다.

## 15. 최종 문장

이 미래의 Cambrian은 단순 AI 에이전트 쇼핑몰이 아니다.

```text
Cambrian은 누구나 만든 에이전트가 무분별하게 팔리는 장터가 아니라,
검증된 에이전트만 살아남고,
실제 사용 증거로 진화하며,
정품 실행권과 proof로 신뢰를 거래하는 AI 노동시장의 운영체계가 된다.
```
