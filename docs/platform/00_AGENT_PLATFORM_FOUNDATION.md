# AI 에이전트 플랫폼 설계 토대

## 1. 한 줄 정의

이 트랙의 1차 제품은 비개발자가 브라우저에서 AI 에이전트를 만들고, 실행 가능한 패키지로 내려받아, 자기 PC에서 사용할 수 있게 하는 온라인 제작 플랫폼이다.

```text
브라우저에서 만든다.
패키지로 내려받는다.
내 PC에서 실행한다.
나중에 Cambrian Runtime과 연결할 수 있게 한다.
```

중요한 경계는 명확하다.

Platform-first 제품은 Cambrian Runtime을 필수 조건으로 만들지 않는다.
처음 만드는 것은 온라인 에이전트 제작 플랫폼이다.
Cambrian은 나중에 붙일 수 있는 고급 실행, 검증, 진화 adapter다.

### 1.1 MVP가 아니라 Defensible Alpha다

이 트랙은 단순 MVP를 빨리 내는 프로젝트가 아니다.
프롬프트 입력, 에이전트 카드, 다운로드 버튼만 있는 사이트는 빠르게 복제된다.

목표는 최소 기능 제품이 아니라 **방어 가능한 첫 시스템**이다.

```text
쉬운 Builder
-> 실행 계약
-> preflight 검증
-> Private Download Hub
-> promotion audit
-> verified lineage
-> future Cambrian proof/evolution
```

한국 시장에는 아직 이 카테고리가 뚜렷하게 박혀 있지 않다.
따라서 빠르게 선점해야 하지만, 선점 대상은 단순 에이전트 쇼핑몰 UI가 아니다.
선점해야 하는 것은 “AI 직원을 만들고 내 PC에 설치한다”는 사용자 언어와, 그 뒤를 받치는 계약·검증·감사·진화 표준이다.

## 2. 제품 원칙

### 2.1 Platform-first

초기 제품의 본체는 브라우저 플랫폼이다.

사용자는 아래 흐름만 이해하면 된다.

```text
무슨 일을 시키고 싶은지 고른다.
에이전트 성격과 규칙을 만든다.
사용할 입력과 결과물 형식을 정한다.
위험 행동과 금지 행동을 확인한다.
패키지를 내려받는다.
내 PC에서 실행한다.
```

초기 제품에서 Cambrian은 필수 설치물이 아니다.
사용자가 처음부터 Cambrian 용어를 배워야 할 필요도 없다.

### 2.2 Agent는 프롬프트가 아니라 실행 계약이다

플랫폼에서 판매하거나 공유하는 것은 단순 프롬프트가 아니다.
에이전트는 아래 내용을 포함한 실행 계약이다.

- 역할
- 목표
- 입력 형식
- 출력 형식
- 권한
- 금지 행동
- 사용자 승인 필요 행동
- 검증 기준
- 데이터 사용 범위
- 비용 또는 토큰 사용 방식
- 알려진 한계
- 제작자 출처
- 라이선스
- 버전과 변경 이력

이 구조가 있어야 비개발자도 안전하게 만들고, 구매자도 무엇을 받는지 이해할 수 있다.

### 2.3 다운로드 가능한 산출물이 1차 상품이다

초기 상품은 클라우드에서만 돌아가는 상자가 아니다.
사용자는 에이전트를 만든 뒤 패키지를 내려받을 수 있어야 한다.

패키지는 최소한 아래 파일을 포함한다.

```text
agent.json
agent_card.json
instructions.md
run_local.md
preflight_report.json
marketplace_review.json
manifest.json
legal_notice.md
```

선택 파일:

```text
cambrian-adapter.json
```

이렇게 해야 나중에 실행기, 데스크톱 앱, Cambrian Runtime, 다른 로컬 러너로 확장할 수 있다.

### 2.4 기본값은 비공개다

사용자가 만든 에이전트, 업로드한 파일, 작성한 업무 설명은 기본적으로 비공개다.
공개 마켓 등록은 별도 선택이어야 한다.
공개 등록 전에는 출처, 권한, 제한, 데이터 사용 범위를 다시 확인해야 한다.

### 2.5 자동화보다 통제감을 먼저 준다

비개발자에게 처음부터 완전 자율 에이전트를 주면 위험하다.
초기 제품의 가치는 아래에 있다.

- 내가 무슨 에이전트를 만들었는지 보인다.
- 에이전트가 무엇을 할 수 있고 못 하는지 보인다.
- 위험 행동은 승인 없이 못 한다.
- 결과물 형식과 검증 기준이 미리 정해진다.
- 내 PC에서 실행하는 방법을 이해할 수 있다.

## 3. 초기 아키텍처

```text
Web Builder
-> Agent Contract Generator
-> Risk and Legal Gate
-> Package Builder
-> Download Hub
-> Local Runner Guide
-> Future Cambrian Adapter
```

현재 첫 구현 위치:

```text
web/platform/index.html
```

현재 공식 계약 위치:

```text
schemas/agent_contract_v0_1.schema.json
schemas/agent_pack_bundle_v0_1.schema.json
schemas/manual_run_receipt_v0_1.schema.json
schemas/evolution_suggestion_v0_1.schema.json
schemas/evolution_review_decision_v0_1.schema.json
schemas/candidate_promotion_record_v0_1.schema.json
web/assets/document-organizer.agent-pack.json
web/assets/document-organizer.manual-run-receipt.json
web/assets/document-organizer.evolution-suggestion.json
web/assets/document-organizer.evolution-review-decision.json
web/assets/document-organizer.candidate.agent-pack.json
web/assets/document-organizer.candidate-diff-report.json
web/assets/document-organizer.promoted.agent-pack.json
web/assets/document-organizer.candidate-promotion-record.json
tools/validate_agent_pack.py
tools/validate_manual_run_receipt.py
tools/generate_evolution_suggestion.py
tools/validate_evolution_suggestion.py
tools/validate_evolution_review_decision.py
tools/generate_candidate_pack.py
tools/generate_candidate_diff_report.py
tools/validate_candidate_diff_report.py
tools/promote_candidate_pack.py
tools/validate_candidate_promotion_record.py
tools/verify_promotion_audit_link.py
```

현재 구현은 정적 브라우저 Builder다.
서버, 결제, 공개 마켓, Cambrian Runtime 연결 없이 아래를 먼저 검증한다.

- 문서 정리 에이전트 계약 생성
- Green / Yellow / Red 위험 평가
- agent.json 미리보기
- agent_card.json 생성
- instructions.md 생성
- run_local.md 생성
- legal_notice.md 생성
- preflight_report.json 생성
- marketplace_review.json 생성
- manifest.json 생성
- .agent-pack.json 다운로드
- agent_pack_preflight_v0_1 검증

### 3.1 Web Builder

사용자가 브라우저에서 에이전트를 만드는 화면이다.
첫 vertical은 문서 정리 에이전트가 적합하다.

이유:

- 비개발자가 이해하기 쉽다.
- 위험 권한이 낮다.
- 결과물 검증 기준을 만들기 쉽다.
- 기업 문서 정리, 지원 사례 보고, 지식관리로 확장 가능하다.

현재 Builder에는 Green 템플릿 선택기가 있다.

허용 템플릿:

- 문서 정리
- 회의록 정리
- 이메일 초안
- 체크리스트 생성

이 템플릿들은 모두 낮은 위험의 초안, 정리, 분류, 체크리스트 생성 업무만 다룬다.
의료, 법률, 투자, 채용 판단 템플릿은 만들지 않는다.

### 3.2 Agent Contract Generator

사용자 입력을 실행 계약으로 변환한다.
계약은 사람이 읽을 수 있어야 하고, 기계도 검증할 수 있어야 한다.

초기 `agent.json` 최소 필드:

```json
{
  "schema_version": "0.1",
  "agent_id": "document-organizer",
  "name": "문서 정리 에이전트",
  "author": "사용자",
  "role": "업로드된 문서를 분류하고 요약한다.",
  "goals": [],
  "inputs": [],
  "outputs": [],
  "permissions": [],
  "forbidden_actions": [],
  "approval_required_actions": [],
  "validation_criteria": [],
  "data_policy": {
    "default_visibility": "private",
    "retention": "local_or_user_selected",
    "third_party_sharing": "none_by_default"
  },
  "risk_level": "low",
  "known_limits": [],
  "license": "확인 필요",
  "provenance": [],
  "runtime": {
    "type": "generic",
    "cambrian_required": false,
    "cambrian_compatible": "planned"
  }
}
```

### 3.3 Risk and Legal Gate

Risk and Legal Gate는 패키지를 만들기 전에 위험도를 계산한다.
이 게이트는 법률 판단을 자동으로 내리는 장치가 아니다.
위험한 에이전트를 조기에 막고, 책임과 제한을 사용자에게 명확하게 보여주는 장치다.

게이트는 아래를 확인한다.

- 개인정보 또는 민감정보를 요구하는가
- 다른 계정 접속이나 파일 변경 권한이 있는가
- 결제, 송금, 계약, 법률 결정, 의료 결정, 투자 판단에 영향을 주는가
- 타인을 사칭하거나 대량 메시지를 보낼 수 있는가
- 비밀번호, 토큰, 개인 식별자를 요구하는가
- 검증되지 않은 결과물을 사실처럼 표시하는가

초기 정책:

- Green: 일반 문서 정리, 요약, 분류처럼 낮은 위험
- Yellow: 개인정보, 외부 전송, 승인 필요 행동이 포함된 위험
- Red: 의료 결정, 법률 결정, 투자·금융 결정, 채용·해고 판단, 비밀정보 요청처럼 차단 대상

### 3.4 Package Builder

검증을 통과한 계약을 다운로드 가능한 패키지로 만든다.
초기 패키지는 실행 엔진을 강제하지 않는다.

예시:

```text
my-agent.zip
  agent.json
  agent_card.json
  instructions.md
  run_local.md
  preflight_report.json
  marketplace_review.json
  manifest.json
  legal_notice.md
```

`legal_notice.md`는 사용자를 겁주기 위한 문서가 아니다.
에이전트가 할 수 있는 것, 할 수 없는 것, 데이터 처리 범위, 책임 경계를 명확하게 알려주는 사용자 보호 장치다.

`agent_card.json`은 마켓 공개용 판매 페이지가 아니다.
초기에는 Private Download Hub와 나중의 마켓 심사를 위한 private preview card다.
카드는 이름, 템플릿, 요약, capability, 위험도, preflight 상태, evidence 상태, known limits를 담는다.
카드의 기본값은 `visibility: private`, `sale_ready: false`, `proof_claim_allowed: false`다.

`marketplace_review.json`은 공개 listing 심사 전 게이트다.
초기 상태는 `private_marketplace_review`와 `not_ready`다.
이 파일은 왜 아직 판매할 수 없는지와 공개 전에 필요한 일을 기계가 읽을 수 있게 남긴다.
초기 필수 이유는 runtime evidence 없음, proof claim 불가, 라이선스/환불 정책 확인 필요, 공개 listing 심사 없음이다.

### 3.5 Download Hub

Download Hub는 사용자가 만든 에이전트를 내려받고, 버전별로 다시 받을 수 있는 공간이다.

현재 구현은 서버 없는 Private Download Hub다.

```text
web/platform/index.html
localStorage key: agent-platform-download-hub-v0-1
promotion audit key: agent-platform-promotion-audit-v0-1
hub handoff key: agent-platform-hub-handoff-v0-1
```

현재 Hub의 경계:

- 이 브라우저의 `localStorage`에만 저장한다.
- 서버 계정으로 동기화하지 않는다.
- 공개 마켓에 등록하지 않는다.
- Cambrian Runtime으로 전송하지 않는다.
- 저장된 패키지는 사용자가 다시 다운로드하거나 삭제할 수 있다.
- 기존 `.agent-pack.json`은 브라우저 안에서 client preflight 검증 후 가져올 수 있다.
- Hub에 저장된 버전은 `private_download_hub_to_manual_runner` handoff로 Local Runner에 바로 보낼 수 있다.
- Hub to Runner handoff도 `agent-platform-runner-handoff-v0-1`을 사용하고, `single_use: true`, `server_sync: false`, `api_key_collected: false`, `stores_raw_inputs: false` 경계를 유지한다.
- Evolution Review Gate의 `Private Hub로 보내기`는 `agent-platform-hub-handoff-v0-1` single-use handoff로 promoted pack과 promotion record를 함께 전달한다.
- Hub handoff는 `agent_platform_hub_handoff_v0_1`, `evolution_review_to_private_download_hub`, `single_use: true`, `server_sync: false`, `sends_to_cambrian_runtime: false`를 요구한다.
- Hub handoff는 읽은 뒤 localStorage에서 제거하며, promoted pack 본문 해시와 promotion record의 `promoted_pack_hash`가 일치할 때만 저장한다.
- 가져오기 검증은 bundle schema, 필수 파일, `agent_id`, `risk_level`, `no_runtime_evidence`, `sale_ready: false`, `proof_claim_allowed: false` 경계를 확인한다.
- 같은 `agent_id`를 다시 저장하면 `revision`, `version_label`, `fingerprint`, `change_summary`가 남는다.
- 각 저장 레코드는 `builder_private_draft`, `candidate_not_applied`, `promoted_private_version` 같은 `lifecycle_stage`를 남긴다.
- Hub는 `agent.json.provenance`의 `evolution_promoted` 기록을 세어 `evolution_count`와 `진화 N회` 배지로 표시한다.
- `진화 N회`는 proof나 성공률이 아니라 promotion lineage의 누적 회차 표시다.
- Hub는 저장 버전마다 `private_hub_lineage_card_v0_1`을 화면에 표시하거나 JSON으로 내려받을 수 있다.
- lineage card는 agent id, version label, lifecycle stage, evolution count, content hash, promotion hash, audit link status, proof/sale boundary만 담고 원문 입력과 원문 결과는 담지 않는다.
- lineage card도 proof나 성공률 주장이 아니라 private audit lineage다.
- 내려받은 lineage card는 `lineage card 검증`으로 다시 열어 현재 Hub의 content hash, fingerprint, evolution count, verified audit link와 대조할 수 있다.
- lineage card 검증 결과는 `private_hub_lineage_card_verifier_v0_1`이며, 검증 실패 시 저장이나 실행을 진행하지 않고 오류만 표시한다.
- lineage card 검증 완료와 실패는 모두 Hub storage, promotion audit storage, Runner handoff를 변경하지 않는다.
- lineage verifier report는 `effect: report_only`와 `side_effects.hub_storage_write: false`, `side_effects.promotion_audit_storage_write: false`, `side_effects.runner_handoff_write: false`, `side_effects.installs_or_runs_agent: false`를 포함한다.
- lineage verifier report는 `report_kind: private_hub_lineage_card_verifier_report_v0_1`, `report_version: 0.1`, `report_privacy.stores_raw_card: false`, `report_privacy.echoes_non_lineage_identity: false`를 포함한다.
- Hub는 Builder Golden Path가 실제로 끝난 뒤 `external_alpha_builder_gold_path_share_receipt.json`을 내려받을 수 있다.
- 이 receipt는 `external_alpha_builder_gold_path_share_receipt_v0_1`, `safe_to_share: true`, `proof_claim_allowed: false`, `success_rate_claim_allowed: false`, `sale_ready: false`를 유지한다.
- receipt 생성 조건은 Builder draft 저장, manual_no_api Runner handoff, evolution suggestion, `review_pass_not_promoted` diff report, `promoted_private_version`, verified promotion audit, passing lineage verifier report가 모두 true일 때만 통과한다.
- receipt는 `browser_share_safe_summary_v0_1` 요약만 담고 raw browser storage, 다운로드 경로, 원문 입력, 원문 AI 결과, secret은 담지 않는다.
- malformed JSON lineage card도 `private_hub_lineage_card_verifier_v0_1` fail report로 표시하고 이전 report를 그대로 남기지 않는다.
- agent pack처럼 lineage card가 아닌 valid JSON도 `card_kind` mismatch fail report로 표시하고 Hub/Runner 상태를 변경하지 않는다.
- lineage card가 아닌 JSON의 agent_id, version_label, raw content는 verifier report/status에 echo하지 않고 `unknown`으로 표시한다.
- 배열이나 문자열 같은 non-object JSON도 `lineage card 객체` fail report로 표시하고 원문 값을 echo하지 않는다.
- 변조된 lineage card는 content hash, fingerprint, evolution count, audit link 중 하나라도 맞지 않으면 fail로 표시한다.
- lineage card가 원문 입력, 원문 결과, secret을 저장한다고 주장하도록 변조되어도 `privacy_boundary_blocked` fail로 표시한다.
- lineage card가 proof claim, success rate claim, sale ready를 주장하도록 변조되어도 fail로 표시한다.
- lineage card가 `verified linked`를 주장해도 audit fingerprint와 promoted pack hash가 Hub audit과 맞지 않으면 fail로 표시한다.
- audit import 전에 받은 stale `not linked` lineage card는 Hub에 verified audit이 생긴 뒤 fail로 표시한다.
- Hub는 candidate pack과 promoted pack을 가져올 수 있지만, 둘 다 `proof blocked`, `sale blocked` 경계를 그대로 표시한다.
- Hub는 `candidate_promotion_record_v0_1`을 별도 promotion audit record로 가져와 promoted pack과 해시로 연결한다.
- promotion audit record는 원본 입력이나 secret을 저장하지 않고, 원본/candidate/diff/promoted pack 해시와 수동 승격 gate만 저장한다.
- promotion audit record는 Hub 안에서 JSON 보기, 다시 다운로드, 개별 삭제가 가능하다.
- Hub는 promoted pack을 가져올 때 본문 `content_hash`를 계산하고, audit의 `promoted_pack_hash`, `candidate_pack_hash`, `diff_report_hash`, `agent_id`가 모두 맞을 때만 `verified linked`로 표시한다.
- 같은 agent의 promoted pack이 있어도 `promoted_pack_hash`가 다르면 `promoted hash mismatch`로 표시하고 Hub 카드의 audit badge를 붙이지 않는다.
- 버전 이력의 `input_provenance`는 템플릿, 출력 형식, 권한, 검증 기준 개수 같은 생성 맥락만 저장한다.
- 원문 문서, 사용자 입력 파일 내용, secret 값 자체는 저장하지 않는다.
- 저장된 버전은 client preflight를 다시 통과한 뒤 Builder 입력값으로 복원할 수 있다.
- candidate 또는 promoted pack을 Builder로 복원하면 편집 가능한 Builder 초안이 되며, 다시 저장하면 새 `Builder draft`로 저장된다.
- 같은 `agent_id`의 이전 버전과 이름, 역할, 목표, 출력, 권한, 금지 행동, 검증 기준, 위험 등급, 템플릿, 카드 요약 차이를 비교할 수 있다.
- 저장 개수는 최근 20개로 제한한다.
- Hub 비우기는 package records와 promotion audit records를 함께 지운다.
- 브라우저 smoke 검증은 promoted private version 가져오기, promotion audit record 연결, audit 보기/다운로드/삭제, lifecycle 표시, Builder 초안 복원 흐름을 확인한다.

초기 상태 모델:

- draft
- preflight_passed
- blocked
- downloaded
- listed_private
- listed_public_requested

공개 판매 상태는 초기 Defensible Alpha에서 제외한다.

### 3.6 Preflight Validator

다운로드한 `.agent-pack.json`은 마켓 업로드나 Cambrian adapter 변환 전에 먼저 검증해야 한다.

현재 검증기:

```bash
python tools/validate_agent_pack.py web/assets/document-organizer.agent-pack.json --pretty
```

검증기는 아래를 확인한다.

- bundle schema 통과 여부
- 내부 `agent.json` schema 통과 여부
- 내부 `agent_card.json` 공개 카드 경계 통과 여부
- manifest 파일 목록과 실제 bundle 파일 일치 여부
- embedded `preflight_report.json` 일치 여부
- bundle schema의 `x-required_preflight_checks`와 embedded check 목록 일치 여부
- `agent_id` 일치 여부
- `riskReport.level`과 `agent.json.risk_level` 일치 여부
- `no_runtime_evidence` 상태에서 proof claim 차단 여부
- `marketplace.sale_ready: false`
- `marketplace.proof_claim_allowed: false`
- `cambrian_required: false`

검증 결과 상태:

- `pass`: 패키지 구조가 안전한 초기 조건을 만족한다.
- `blocked`: 스키마는 맞지만 Red 위험이 포함되어 사용 또는 판매 전에 범위를 줄여야 한다.
- `fail`: 스키마나 필수 경계가 깨져 패키지로 인정하지 않는다.

### 3.7 Local Runner Guide

처음에는 강한 로컬 런타임보다 실행 안내가 먼저다.

`run_local.md`는 사용자가 어떤 AI 도구에서 어떤 순서로 쓰면 되는지 알려준다.
API 키나 비밀번호를 플랫폼에 맡기도록 유도하지 않는다.
이 단계에서 플랫폼은 실행 결과를 보장하지 않는다.
플랫폼은 에이전트 계약과 실행 안내를 생성한다.

현재 Local Runner 구현:

```text
web/runner/index.html
localStorage key: agent-platform-manual-runner-v0-1
builder handoff key: agent-platform-runner-handoff-v0-1
evolution handoff key: agent-platform-evolution-handoff-v0-1
runner_mode: manual_no_api
```

Local Runner는 `.agent-pack.json`을 브라우저에서 불러와 client preflight를 확인하고, 사용자가 이미 쓰는 AI 도구에 붙여 넣을 실행 프롬프트를 만든다.
API 키를 받지 않고, Cambrian Runtime도 요구하지 않는다.
Red 위험이나 깨진 package는 실행 프롬프트 생성을 막는다.
로컬 실행 기록은 원문 입력과 결과를 저장하지 않고 `agent_id`, 시간, 입력 길이, 출력 길이, 검증 기준 개수 같은 메타데이터만 저장한다.
이 기록은 proof나 성공률이 아니라 `manual_review_only` 상태다.

Builder는 `Local Runner로 보내기` 버튼으로 현재 pack을 `agent_platform_runner_handoff_v0_1` 형태로 같은 브라우저의 `localStorage`에 저장할 수 있다.
이 handoff는 `builder_to_manual_runner`이며 `single_use: true`다.
Runner는 `?handoff=builder`로 열릴 때 handoff를 자동으로 읽고, client preflight와 handoff privacy/proof boundary를 확인한 뒤 `localStorage`에서 제거한다.
handoff는 서버로 동기화하지 않고, Cambrian Runtime으로 전송하지 않고, API key나 secret을 수집하지 않는다.
handoff가 실패하면 사용자는 기존처럼 `.agent-pack.json` 파일을 내려받아 Runner에서 직접 열 수 있어야 한다.

Runner는 AI 결과가 붙여 넣어진 receipt에서만 `Evolution으로 보내기`를 허용한다.
이 흐름은 receipt 메타데이터만 사용해 `evolution_suggestion_v0_1` 초안을 만들고, `agent_platform_evolution_handoff_v0_1` 형태로 같은 브라우저의 `localStorage`에 저장한다.
이 handoff는 `manual_runner_to_evolution_review`이며 `single_use: true`다.
Evolution Review Gate는 `?handoff=runner`로 열릴 때 이 handoff를 자동으로 읽고, suggestion preflight와 privacy/proof boundary를 확인한 뒤 `localStorage`에서 제거한다.
이 suggestion은 `draft_requires_user_approval`이며 `auto_apply: false`, `auto_promote: false`, `can_create_new_version: false`를 유지한다.
handoff는 원문 입력과 원문 결과를 넘기지 않고, 입력 길이, 출력 길이, manual check 개수 같은 receipt metadata만 사용한다.
Runner handoff에는 candidate 생성을 위한 원본 agent pack도 `source_bundle`로 함께 들어간다.
이 `source_bundle`은 raw input이 아니라 Builder가 만든 `.agent-pack.json` 계약이며, Evolution Review Gate는 agent_id, no_runtime_evidence, sale_ready false, proof_claim_allowed false, candidate/promoted metadata 없음 조건을 확인한다.
Hub 저장 버전을 Runner로 실행한 경우 `source_bundle`은 `promoted_private_version`일 수 있다.
이때 Evolution Review Gate는 `promotion_metadata`가 검증된 promoted source만 허용하고, 새 candidate pack을 만들 때 이전 `promotion_metadata`를 제거한다.
이 제거는 새 후보가 이미 승격된 것처럼 보이지 않게 하는 lineage 경계이며, diff report에는 승인된 `promotion_metadata` removal로 기록된다.
Evolution Review Gate의 `후보 pack 내보내기`는 사용자가 별도로 누르는 명시 명령이다.
이 버튼은 approved decision이 하나 이상 있을 때만 `candidate_agent_pack_metadata_v0_1`이 포함된 candidate pack을 만든다.
candidate pack은 `candidate_not_applied`, `auto_apply: false`, `auto_promote: false`, `requires_user_final_review: true`, `original_pack_preserved: true`를 유지하며 원본 pack을 수정하지 않는다.
Evolution Review Gate의 `diff report 내보내기`는 원본 pack과 candidate pack의 변경 경로를 비교해 `candidate_diff_report_v0_1`을 만든다.
diff report는 `review_pass_not_promoted` 상태에서만 통과하고, `unexpected_changes`가 비어 있어야 한다.
diff report도 `auto_promote: false`, `promotion_requires_separate_command: true`, `automatic_candidate_promotion` 차단을 유지한다.
Evolution Review Gate의 `promoted pack 내보내기`와 `promotion record 내보내기`는 diff report가 현재 decision으로 먼저 생성된 뒤에만 열린다.
promoted pack은 `promoted_private_version`이며 `candidate_metadata`를 제거하고 `promotion_metadata`를 포함한다.
promotion metadata는 `user_command_required: true`, `auto_promote: false`, `proof_claim_allowed: false`, `marketplace_sale_ready: false`를 유지한다.
promotion record는 `candidate_promotion_record_v0_1`이며 원본 pack, candidate pack, diff report, promoted pack의 sha256을 모두 연결한다.
promotion record도 자동 승격이 아니라 private version 감사 기록이고, Public marketplace publish나 proof badge를 만들지 않는다.

Local Runner는 필요하면 `manual_run_receipt_v0_1` JSON을 내보낸다.
이 receipt는 `runner_mode: manual_no_api`, `source_bundle`, `input_summary`, `output_summary`, `manual_checks`, `privacy`, `proof_boundary`, `evolution_signal`을 담는다.
원문 입력, 원문 결과, API 키, secret은 저장하지 않는다.
`proof_boundary`는 `proof_claim_allowed: false`, `success_rate_claim_allowed: false`, `marketplace_sale_ready: false`를 유지한다.
따라서 receipt는 proof가 아니라 나중에 Cambrian adapter나 evolution loop가 참고할 수 있는 수동 검토 메타데이터다.

receipt 검증기:

```bash
python tools/validate_manual_run_receipt.py web/assets/document-organizer.manual-run-receipt.json --pretty
```

`manual_run_receipt_v0_1`은 `.agent-pack.json` 내부 파일이 아니다.
사용자가 Local Runner에서 수동 실행을 끝낸 뒤 별도로 내보내는 실행 메타데이터다.
pack 검증은 `validate_agent_pack.py`, receipt 검증은 `validate_manual_run_receipt.py`가 담당한다.

receipt 이후에는 `evolution_suggestion_v0_1` 초안을 만들 수 있다.
단, `evolution_signal.eligible_for_suggestion: true`와 `requires_user_approval: true`가 있는 receipt만 진화 제안 입력이 된다.
생성된 suggestion의 `source_receipt`에도 이 두 신호를 다시 남겨 나중에 자동 적용과 proof로 오해되지 않게 한다.

```bash
python tools/generate_evolution_suggestion.py web/assets/document-organizer.agent-pack.json web/assets/document-organizer.manual-run-receipt.json --pretty
python tools/validate_evolution_suggestion.py web/assets/document-organizer.evolution-suggestion.json --pretty
```

진화 제안은 `draft_requires_user_approval` 상태다.
`auto_apply: false`, `auto_promote: false`, `can_create_new_version: false`를 유지한다.
제안은 `instructions.md`, `agent.json.validation_criteria`, `agent.json.known_limits`, `agent_card.json` 같은 목표 지점과 이유를 설명할 뿐이다.
사용자 승인 전에는 pack을 수정하거나 새 버전으로 승격하지 않는다.

진화 제안 이후에는 Evolution Review Gate에서 `evolution_review_decision_v0_1`을 만든다.

```text
web/evolution/index.html
```

이 화면은 suggestion을 불러와 recommendation별로 `approved`, `rejected`, `deferred`를 기록한다.
내보낸 decision은 `reviewed_not_applied` 상태다.
`auto_apply: false`, `auto_promote: false`, `apply_requires_separate_step: true`, `can_create_new_version: false`를 유지한다.
decision의 `source_suggestion`에는 `recommendation_ids`, `source_receipt_eligible_for_suggestion: true`, `source_receipt_requires_user_approval: true`를 다시 남긴다.
모든 recommendation_id에는 정확히 하나의 decision이 있어야 하며, 각 decision에는 빈 문자열이 아닌 `reviewer_note`가 필요하다.
다음 단계로 허용되는 것은 `generate_candidate_pack_after_user_command`뿐이고, `automatic_pack_mutation`은 차단한다.

decision 검증기:

```bash
python tools/validate_evolution_review_decision.py web/assets/document-organizer.evolution-review-decision.json --pretty
```

사용자가 별도로 후보 생성을 명령하면 `generate_candidate_pack.py`가 승인된 decision만 반영한 새 `.agent-pack.json` 후보를 만든다.

```bash
python tools/generate_candidate_pack.py web/assets/document-organizer.agent-pack.json web/assets/document-organizer.evolution-suggestion.json web/assets/document-organizer.evolution-review-decision.json --pretty --output web/assets/document-organizer.candidate.agent-pack.json
python tools/validate_agent_pack.py web/assets/document-organizer.candidate.agent-pack.json --pretty
```

이 단계의 경계:

- 원본 `.agent-pack.json` 경로와 같은 `--output`은 실패한다.
- `approved` decision만 반영한다.
- `approved` decision이 하나도 없으면 후보 pack을 생성하지 않는다.
- `deferred`, `rejected` decision은 반영하지 않는다.
- 후보 pack도 `sale_ready: false`, `proof_claim_allowed: false`, `no_runtime_evidence`를 유지한다.
- 후보 pack은 `generated_by: tools/generate_candidate_pack.py`와 `evolution_candidate` provenance를 남긴다.
- 후보 pack은 `candidate_metadata`를 반드시 포함한다.
- `candidate_metadata.apply_status: candidate_not_applied`를 유지한다.
- `candidate_metadata.auto_apply: false`, `candidate_metadata.auto_promote: false`를 유지한다.
- `candidate_metadata.approved_decision_ids`와 `candidate_metadata.approved_recommendation_ids`로 실제 반영 근거를 남긴다.
- `candidate_metadata.requires_user_final_review: true`, `candidate_metadata.original_pack_preserved: true`를 유지한다.
- 후보 pack 생성은 적용이 아니라 별도 최종 검토 대상 산출물이다.

candidate pack을 만든 뒤에는 diff gate를 통과해야 한다.

```bash
python tools/generate_candidate_diff_report.py web/assets/document-organizer.agent-pack.json web/assets/document-organizer.candidate.agent-pack.json web/assets/document-organizer.evolution-review-decision.json --pretty --output web/assets/document-organizer.candidate-diff-report.json
python tools/validate_candidate_diff_report.py web/assets/document-organizer.candidate-diff-report.json --pretty
```

diff report는 원본과 candidate의 해시, 변경 경로, 승인 decision 연결, 예상 밖 변경 여부를 기록한다.
`unexpected_changes`는 비어 있어야 한다.
`deferred` 또는 `rejected` decision 대상이 candidate에 반영되면 diff gate는 실패해야 한다.
diff gate가 통과해도 `review_pass_not_promoted` 상태이며, 자동 승격은 `automatic_candidate_promotion`으로 차단한다.

사용자가 diff report를 확인한 뒤 별도 명령을 내리면 `promote_candidate_pack.py`가 candidate pack을 private version으로 승격한다.

```bash
python tools/promote_candidate_pack.py web/assets/document-organizer.agent-pack.json web/assets/document-organizer.candidate.agent-pack.json web/assets/document-organizer.candidate-diff-report.json --pretty --pack-output web/assets/document-organizer.promoted.agent-pack.json --record-output web/assets/document-organizer.candidate-promotion-record.json
python tools/validate_agent_pack.py web/assets/document-organizer.promoted.agent-pack.json --pretty
python tools/validate_candidate_promotion_record.py web/assets/document-organizer.candidate-promotion-record.json --pretty
python tools/verify_promotion_audit_link.py web/assets/document-organizer.promoted.agent-pack.json web/assets/document-organizer.candidate-promotion-record.json --pretty
```

promotion 단계의 경계:

- 원본 pack, candidate pack, diff report의 `agent_id`가 같아야 한다.
- diff report의 `original_pack_hash`, `candidate_pack_hash`가 현재 입력 파일과 일치해야 한다.
- diff report는 `review_pass_not_promoted` 상태여야 한다.
- candidate pack은 `candidate_not_applied` 상태여야 한다.
- promoted pack은 `candidate_metadata`를 제거하고 `promotion_metadata`를 포함한다.
- promotion 단계는 `candidate_promotion_record_v0_1`을 별도 감사 기록으로 남긴다.
- `promotion_metadata.promotion_status: promoted_private_version`을 유지한다.
- `promotion_metadata.user_command_required: true`, `promotion_metadata.auto_promote: false`를 유지한다.
- `promotion_metadata.proof_claim_allowed: false`, `promotion_metadata.marketplace_sale_ready: false`를 유지한다.
- promotion record는 원본, candidate, diff report, promoted pack의 해시를 모두 남긴다.
- promotion record의 `gate.auto_promote: false`, `gate.output_overwrite_blocked: true`를 유지한다.
- promoted pack도 `sale_ready: false`, `proof_claim_allowed: false`, `no_runtime_evidence` 상태다.
- promoted pack은 공개 marketplace 등록이나 판매 준비가 아니라 Private Download Hub의 새 private version 후보일 뿐이다.
- `verify_promotion_audit_link.py`는 promoted pack 해시, diff report 해시, candidate pack 해시, agent_id, private/proof 경계를 promotion record와 다시 대조한다.

Private Download Hub promotion audit:

- Private Download Hub는 promotion record를 `agent-platform-promotion-audit-v0-1` localStorage에 별도로 보관한다.
- Private Download Hub의 promotion audit records는 pack 본문과 분리된 감사 로그다.
- promotion audit record는 promoted pack의 본문 `content_hash`, `promotion_metadata.diff_report_hash`, `promotion_metadata.promoted_from_candidate_hash`, `agent_id`가 모두 맞을 때만 Hub 카드에 자동 연결된다.
- promotion audit record가 같은 agent의 promoted pack과 해시가 다르면 연결 대기 대신 `promoted hash mismatch`로 표시한다.
- promotion audit record는 Hub에서 보기, 다운로드, 삭제가 가능하다.
- 연결된 audit가 있어도 `proof blocked`, `sale blocked` 상태는 유지된다.

### 3.8 Future Cambrian Adapter

나중에 Cambrian을 붙일 때는 `agent.json`을 Cambrian manifest로 변환한다.

```text
agent.json
-> cambrian-pack.yaml
-> cambrian install manifest
-> dry-run
-> proof
-> evolution
-> marketplace update
```

이 adapter는 고급 사용자와 기업 사용자를 위한 확장이다.
초기 platform-first 제품이 Cambrian 설치를 요구해서는 안 된다.

## 4. Defensible Alpha 범위

Defensible Alpha에 포함한다.

- 문서 정리 에이전트 builder
- 에이전트 계약 미리보기
- 위험 게이트
- fake proof 금지 문구
- agent package 다운로드
- local runner guide
- platform-first 제품 설명
- Private Download Hub
- version history
- candidate/promotion audit lineage
- verified promotion audit link
- 한국 시장 카테고리 선점 문구
- Cambrian future adapter 자리 표시

Defensible Alpha에서 제외한다.

- 결제
- 공개 마켓 등록
- 서버 계정
- 자동 에이전트 실행
- Cambrian Runtime 필수 설치
- 실제 성능 proof
- 법률 판단 자동화
- 의료 판단 자동화
- 투자 판단 자동화

## 5. 검증 기준

초기 검증은 아래 기준으로 한다.

- 사용자가 Cambrian 없이도 사용할 수 있다는 점이 명확한가
- 다운로드 패키지에 필요한 계약 파일이 들어가는가
- 위험 게이트가 Red 작업을 차단하는가
- 실제 실행 evidence 없이 성공률을 표시하지 않는가
- 나중에 Cambrian adapter로 연결할 자리가 있는가
- 공개 마켓보다 개인 제작, 로컬 실행, 검증 가능한 lineage가 먼저인가
- 단순 에이전트 쇼핑몰보다 계약·검증·감사 표준이 먼저인가

## 6. 장기 방향

장기적으로 이 트랙은 Agent Marketplace로 확장된다.
하지만 시장의 핵심은 프롬프트 판매가 아니다.
핵심은 실행 계약, 검증 evidence, 진화 이력, 제작자 신뢰, 라이선스, 공식 업데이트다.

플랫폼은 먼저 비개발자가 안전하게 에이전트를 만들 수 있게 해야 한다.
그 다음 Cambrian Runtime을 붙여 실행, 검증, proof, 진화를 담당하게 한다.

한국 시장 선점 전략은 “마켓을 먼저 여는 것”이 아니라 “에이전트를 고용한다”는 카테고리 언어와 “검증 가능한 에이전트만 신뢰한다”는 기준을 먼저 박는 것이다.

## 7. 고정 계획

이 트랙은 아래 순서로만 진행한다.
순서를 바꾸면 시장처럼 보이는 화면은 빨리 만들 수 있지만, 실제 신뢰 자산은 쌓이지 않는다.

### 7.1 Phase 0: 계약을 먼저 고정한다

현재 단계다.

반드시 고정할 것:

- `agent_contract_v0_1`
- `agent_pack_bundle_v0_1`
- `agent_pack_preflight_v0_1`
- `document-organizer.agent-pack.json`
- `validate_agent_pack.py`
- `cambrian_required: false`
- `marketplace.sale_ready: false`
- `marketplace.proof_claim_allowed: false`
- `evidence_status: no_runtime_evidence`

이 단계에서 하지 않을 것:

- 공개 마켓 등록
- 결제
- 판매 가능 배지
- 성공률 표시
- 자동 실행
- Cambrian Runtime 필수 설치

### 7.2 Phase 1: 다운로드 가능한 안전 패키지를 만든다

목표는 사용자가 브라우저에서 만든 에이전트를 자기 PC로 가져갈 수 있게 하는 것이다.

완료 조건:

- 생성된 `.agent-pack.json`이 bundle schema를 통과한다.
- 내부 `agent.json`이 agent contract schema를 통과한다.
- 내부 `agent_card.json`이 private card 경계를 통과한다.
- `preflight_report.json`이 bundle 내부 상태와 일치한다.
- Red 위험은 `blocked`가 된다.
- Green 패키지만 개인 다운로드 흐름에서 pass가 된다.
- legal notice가 책임 경계, 데이터 경계, no proof 상태를 명시한다.

### 7.3 Phase 2: 개인 보관함과 버전 이력을 붙인다

이 단계에서도 공개 마켓은 열지 않는다.

목표:

- 사용자가 만든 agent pack을 다시 받을 수 있다.
- 버전별 변경 이력이 남는다.
- 어떤 입력으로 생성했는지 provenance가 남는다.
- secret, 원문 문서, 개인정보는 기본 저장 대상이 아니다.
- 사용자가 명시적으로 선택한 공개 범위만 저장한다.

완료 조건:

- 같은 `agent_id`의 최신 레코드를 기준으로 다음 `revision`을 계산한다.
- 각 저장 레코드는 사람이 읽는 `version_label`을 가진다.
- 각 저장 레코드는 계약 핵심값으로 만든 `fingerprint`를 가진다.
- 이전 버전이 있으면 `change_summary`에 이름, 역할, 목표, 출력, 권한, 금지 행동, 검증 기준, 위험 등급, 템플릿, 카드 요약 변경 여부를 남긴다.
- `input_provenance`는 생성 맥락 요약만 남기고 원문 문서나 secret 값 자체를 저장하지 않는다.
- 다운로드 파일명은 `agent_id-version_label.agent-pack.json` 형식으로 구분된다.
- 저장된 버전을 Builder로 복원하기 전 `clientPreflightBundle`을 다시 실행한다.
- 버전 비교는 같은 `agent_id`의 직전 저장 레코드와 계약 핵심 필드 차이만 보여준다.
- 브라우저 smoke 검증은 독립 브라우저 context에서 저장, 수정, 재저장, 비교, 복원 흐름을 확인한다.

### 7.4 Phase 3: Cambrian Adapter를 붙인다

Cambrian Runtime은 platform-first Defensible Alpha의 필수 조건이 아니라 고급 adapter다.

adapter가 할 일:

- `agent.json`을 Cambrian manifest 후보로 변환한다.
- Cambrian install 전 dry-run을 만든다.
- 권한과 금지 행동을 authority profile로 변환한다.
- validation criteria를 test/checklist/evidence contract로 변환한다.
- 실행 결과가 쌓인 뒤에만 proof와 evolution을 허용한다.

adapter가 하지 않을 일:

- 사용자 PC나 프로젝트를 자동 수정
- secret 자동 사용
- provider API 자동 호출
- proof 없는 marketplace 성능 주장

### 7.5 Phase 4: Marketplace는 proof 이후에만 연다

Marketplace는 에이전트 파일을 사고파는 장소가 아니다.
Marketplace는 검증된 실행 계약, proof, 버전 이력, 제작자 책임, 라이선스, 공식 업데이트 채널을 보여주는 신뢰 레이어다.

공개 listing 최소 조건:

- schema pass
- Red risk 없음
- no_runtime_evidence 해소
- 검증 가능한 실행 evidence
- legal notice 최신화
- license 명시
- provenance 명시
- rollback 또는 update channel 명시
- 제작자 연락/책임 경계 명시

## 8. 법률과 위험 게이트

이 문서는 법률 자문이 아니다.
플랫폼은 법률 판단을 자동화하지 않는다.
플랫폼의 역할은 사용자가 위험을 보지 못한 채 에이전트를 만들거나 판매하지 않게 하는 것이다.

### 8.1 차단 대상

초기 제품에서 아래는 Red로 차단한다.

- 의료 결정
- 법률 결정
- 투자·금융 결정
- 채용·해고 판단
- 비밀번호, 토큰, 개인 API 키 요청
- 결제 또는 송금 실행
- 타인 사칭
- 대량 메시지 발송
- 검증 없는 성공률 또는 proof 주장

### 8.2 Yellow 승인 대상

아래는 차단은 아니지만 명시 승인이 필요하다.

- 사용자 선택 파일 읽기
- 새 파일 생성
- 외부 서비스 전송
- 개인정보 포함 가능성
- 결과를 다른 사람에게 공유

### 8.3 legal_notice.md의 역할

`legal_notice.md`는 면책 문구만 모아둔 문서가 아니다.
사용자 보호와 제작자 책임 경계를 사람이 읽을 수 있게 만드는 계약 설명서다.

반드시 포함할 것:

- 이 에이전트가 할 수 있는 일
- 이 에이전트가 할 수 없는 일
- 금지된 고위험 결정
- 데이터 처리 범위
- secret 수집 금지
- no_runtime_evidence 상태
- proof와 성공률 주장을 하지 않는다는 점
- 사용자가 결과물을 직접 검토해야 한다는 점

## 9. 다음 작업 기준

다음 구현은 아래 순서로만 진행한다.

1. schema와 sample pack의 사람이 읽을 수 있는 문구를 정상 한국어로 고정한다.
2. `validate_agent_pack.py`가 pass, blocked, fail을 안정적으로 구분하게 유지한다.
3. `test_agent_pack_validator.py`에 법률/위험/마켓 금지 조건 회귀를 추가한다.
4. platform HTML은 schema와 sample pack이 가진 계약을 그대로 생성해야 한다.
5. Cambrian adapter는 이 4단계가 안정화된 뒤에 시작한다.

## 10. 2026-05-11 Task Direction Lock

판정: 방향은 맞지만 다음 우선순위는 Builder Golden Path다.

지금까지의 진행은 agent contract, preflight, Private Download Hub, Local Runner, evolution review, candidate/promotion audit, 외부 알파 릴리즈 게이트를 단단하게 만들었다.
이 방향은 단순 에이전트 쇼핑몰 복제가 아니라 검증 가능한 에이전트 제작 표준을 만드는 방향이므로 옳다.

하지만 다음 작업이 계속 릴리즈/파일럿 문서와 운영 게이트로만 깊어지면, 사용자가 실제로 느끼는 제품 핵심인 “브라우저에서 만들고 내려받아 내 PC에서 사용한다”는 흐름이 약해질 수 있다.
따라서 이후 작업은 아래 판정으로 고정한다.

### 10.1 현재 상태 판정

Green:

- 외부 알파 릴리즈, 검증, handoff, send-ready, pilot-ready, dispatch, review, evidence, decision, iteration 체인은 충분히 방어적이다.
- `.agent-pack.json`, manual receipt, evolution suggestion, review decision, candidate pack, diff report, promotion record의 계약 경계는 유지되고 있다.
- no proof, no success rate, no sale ready, no API key, no Cambrian required 경계는 현재 방향과 맞다.

Yellow:

- Builder Golden Path가 외부 알파 운영 체인보다 더 앞에 보여야 한다.
- 비개발자가 템플릿을 고르고, 계약을 이해하고, 위험을 보고, 패키지를 내려받고, Local Runner로 실행 프롬프트를 만드는 흐름을 더 짧고 강하게 만들어야 한다.
- 현재 proof와 evolution은 실제 runtime evidence가 아니라 manual review metadata라는 점을 UI와 문서가 계속 분명히 해야 한다.

Red line:

- Cambrian Runtime을 platform-first 알파의 필수 조건으로 바꾸지 않는다.
- provider API key, secret, 비밀번호를 수집하지 않는다.
- 공개 마켓, 결제, 판매 가능 배지, 성공률, proof claim을 먼저 만들지 않는다.
- 사용자의 원문 문서, 원문 AI 답변, 브라우저 localStorage 내용을 외부로 보내지 않는다.
- candidate나 promoted pack을 공개 상품처럼 표현하지 않는다.

### 10.2 다음 단계: Builder Golden Path Lock

다음 단계는 Builder Golden Path Lock이다.

사용자가 이해해야 하는 첫 화면 흐름은 아래 하나로 고정한다.

```text
Green 템플릿 선택
-> Agent Contract 생성
-> Risk and Legal Gate 확인
-> agent pack private download
-> Local Runner로 보내기
-> manual_no_api Local Runner 열기
-> 실행 프롬프트 생성
-> manual_run_receipt 내보내기
-> Evolution으로 보내기
-> evolution suggestion 초안 생성
-> 사용자가 recommendation 검토
-> 후보 pack 내보내기
-> diff report 내보내기
-> promoted pack 내보내기
-> promotion record 내보내기
-> Private Hub로 보내기
-> Hub가 promoted pack + promotion audit verified linked 표시
-> Hub 저장 버전 Runner로 실행
-> lineage verifier pass
-> external_alpha_builder_gold_path_share_receipt.json 내려받기
-> promoted_private_version source로 2회차 Evolution 재검토
```

이 흐름은 Cambrian 없이도 끝까지 설명되어야 한다.
Cambrian adapter는 이 흐름 뒤에 붙는 고급 경로로만 둔다.

### 10.3 완료 조건

Builder Golden Path Lock의 완료 조건:

- 첫 사용자가 `START_HERE_EXTERNAL_ALPHA.md`를 보고 10분 안에 Builder, Private Download Hub, Local Runner의 역할을 구분할 수 있다.
- Builder 화면에서 “AI 직원을 만들고 내 PC에 설치한다”는 제품 언어가 첫 흐름으로 보인다.
- `.agent-pack.json` 다운로드 전 preflight 상태와 Red/Yellow/Green 위험이 보인다.
- 다운로드된 pack은 `validate_agent_pack.py`를 통과한다.
- Local Runner는 API key 없이 `manual_no_api` 실행 프롬프트를 만든다.
- Builder handoff는 `agent-platform-runner-handoff-v0-1`에 한 번만 저장되고 Runner가 읽은 뒤 제거한다.
- Evolution handoff는 `agent-platform-evolution-handoff-v0-1`에 한 번만 저장되고 Evolution Review Gate가 읽은 뒤 제거한다.
- Hub handoff는 `agent-platform-hub-handoff-v0-1`에 한 번만 저장되고 Private Download Hub가 읽은 뒤 제거한다.
- Hub에 저장된 버전은 `private_download_hub_to_manual_runner` handoff로 Local Runner에 바로 보낼 수 있다.
- Hub에서 다시 실행한 promoted pack은 `promoted_private_version` source로 2회차 Evolution 재검토가 가능하다.
- 2회차 candidate 생성 시 이전 `promotion_metadata`는 제거되고 diff report에는 허용된 removal로만 남는다.
- receipt는 proof가 아니라 `manual_review_only` metadata로만 표시된다.
- evolution suggestion은 자동 적용이 아니라 사용자 승인 전 초안으로만 표시된다.
- candidate pack은 자동 적용이 아니라 `candidate_not_applied` preview/export로만 표시된다.
- diff report는 자동 승격이 아니라 `review_pass_not_promoted` review gate로만 표시된다.
- promoted pack은 공개 배포가 아니라 `promoted_private_version` private export로만 표시된다.
- promotion record는 promoted pack hash까지 연결하는 audit record로만 표시된다.
- Private Hub로 보내기는 promoted pack과 promotion record를 함께 저장하되, 검증 연결 실패 시 Hub에 verified linked badge를 붙이지 않는다.
- Private Download Hub는 저장된 버전에 `진화 N회` 배지를 표시하되, 이 값은 proof가 아니라 `evolution_promoted` provenance count다.
- Private Download Hub의 promoted private version도 `proof blocked`, `sale blocked`를 유지한다.
- Builder Golden Path 완료 receipt는 `external_alpha_builder_gold_path_share_receipt.json`으로 내려받을 수 있으며, 이 파일은 proof나 성공률 주장이 아니라 share-safe 완료 receipt다.

### 10.4 지금 하지 않을 일

지금 하지 않을 일:

- public marketplace listing
- 결제, 정산, 판매자 대시보드
- provider API 호출형 cloud execution
- Cambrian Runtime 강제 설치
- public proof badge
- agent ranking
- success rate dashboard
- 자동 진화 적용

### 10.5 다음 구현 순서

다음 구현은 아래 순서로 진행한다.

1. Builder 화면의 첫 사용 흐름을 더 짧게 고정한다.
2. `START_HERE_EXTERNAL_ALPHA.md`의 첫 사용 흐름을 Builder Golden Path 기준으로 정리한다.
3. `verify_platform_alpha.py`가 Builder Golden Path Lock 문구를 확인하게 한다.
4. 브라우저 smoke 또는 pytest가 Builder, Hub, Runner 연결 문구를 회귀로 잡게 한다.
5. 이 흐름이 안정화된 뒤에만 Cambrian adapter 또는 marketplace export를 다시 본다.
