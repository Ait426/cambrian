# Web Control Plane

> Static registry dependency resolver note:
> Web catalog can expose namespace, version, dependencies, maturity, and proof_status metadata.
> Local Cambrian runtime performs dependency resolve, digest verification, graph install, and lockfile pinning.
>
> ```bash
> cambrian install plan cambrian/auth-bug-core@0.2.0 --registry official
> cambrian install pack cambrian/auth-bug-core@0.2.0 --registry official --confirm-deps
> ```

## 1. 문서 목적

이 문서는 Cambrian에서 웹이 맡는 역할을 정의한다.

Cambrian은 로컬 runtime이다.
하지만 사용자가 AI 일꾼과 작업반을 쉽게 고르고 설치하려면 웹이 필요하다.

이 문서는 다음 질문에 답한다.

- Cambrian에서 웹은 무엇인가?
- 웹은 무엇을 해야 하고, 무엇을 하면 안 되는가?
- 웹과 로컬 Cambrian runtime은 어떻게 연결되는가?
- 사용자는 웹에서 무엇을 “고용”하는가?
- 설치 manifest는 무엇인가?
- 웹은 어떻게 evidence와 proof를 보여줘야 하는가?
- 장기적으로 웹은 marketplace인가, control plane인가?

핵심 원칙은 다음이다.

> **웹은 Cambrian의 실행 엔진이 아니라, AI 일꾼과 작업반을 고용·선택·설치하게 해주는 control plane이다.**

---

## 2. 한 문장 정의

**Cambrian Web Control Plane은 사용자가 AI worker pack, team pack, template pack, lane pack을 발견하고 선택하며, 로컬 Cambrian runtime에 설치할 수 있도록 install manifest를 제공하는 고용/배치 관제판이다.**

정식 경계 표현은 **Web control plane vs Local Cambrian runtime** 이다.

더 짧게 말하면:

> **웹은 AI 일꾼을 고르는 곳이고, 로컬 Cambrian은 그 일꾼을 실제 프로젝트에 설치하고 굴리는 곳이다.**

---

## 3. 왜 웹이 필요한가

CLI만으로도 Cambrian runtime은 동작할 수 있다.
하지만 제품 경험 관점에서 CLI만으로는 부족하다.

사용자는 보통 다음을 원한다.

- 어떤 AI 일꾼이 있는지 보고 싶다.
- 내 문제에 어떤 작업반이 맞는지 추천받고 싶다.
- 설치하기 전에 그 pack이 뭘 포함하는지 알고 싶다.
- 이 pack이 실제로 검증됐는지 보고 싶다.
- 설치 명령을 복잡하게 만들고 싶지 않다.

웹은 이 문제를 해결한다.

웹은 사용자가 Cambrian을 다음처럼 느끼게 만든다.

> “내가 필요한 AI 일꾼을 고르면, Cambrian이 내 프로젝트에 설치해준다.”

이 경험은 “하네스 엔지니어링”보다 훨씬 이해하기 쉽다.

---

## 4. 웹의 제품 역할

웹의 역할은 크게 다섯 가지다.

### 4.1 Catalog

사용자가 설치 가능한 pack을 탐색한다.

예:
- Auth Bug Core
- Safe Patch Core
- Review Support Team
- Docs Cleanup Team
- Research Triage Pack

### 4.2 Recommendation

사용자의 프로젝트/목적에 맞는 pack을 추천한다.

예:
- Python + pytest 프로젝트에는 `auth-bug-core`
- review-heavy 작업에는 `safe-patch-core`

### 4.3 Hiring Surface

사용자는 pack을 “고용”하는 느낌으로 선택한다.

외부 언어:
- 고용하기
- 설치하기
- 내 AI에 붙이기
- 작업반 투입하기

### 4.4 Install Manifest

웹은 로컬 Cambrian이 이해할 수 있는 manifest를 제공한다.

예:
```bash
cambrian install manifest ./auth-bug-core.cambrian-pack.yaml
```

또는 local catalog가 있는 경우:

```bash
cambrian install pack auth-bug-core
```

이 `install pack` 명령은 V1에서 local catalog alias로 구현되어 있다.
Static 웹/remote registry lookup은 구현되어 있다.
SaaS registry API, authentication, payment/licensing은 아직 planned다.

### 4.5 Proof Display

웹은 pack의 성과 증거를 보여줄 수 있다.

예:

* validated proposal rate
* benchmark proof
* known limits
* canary status
* compatible stack
* last qualification result

단, proof는 과장하면 안 된다.
가능하면 로컬 evidence 또는 검증된 published evidence를 기반으로 보여줘야 한다.

---

## 5. 웹이 하지 말아야 하는 것

웹은 runtime이 아니다.

웹이 기본적으로 하지 말아야 하는 것:

* 프로젝트 source code 실행
* source code execution
* source code 수정
* patch apply
* cloud patch/apply
* adoption
* benchmark replay 직접 실행
* local session 조작
* 현재 프로젝트 runtime state 몰래 변경
* cloud에서 사용자 코드를 무단 분석
* provider-specific AI execution 강제

웹은 control plane이다.
execution은 로컬 Cambrian runtime이 담당한다.

---

## 6. Web vs Local Runtime 경계

| 영역 | Web Control Plane | Local Cambrian Runtime |
| --- | --- | --- |
| pack 탐색 | 담당 | 보조 |
| pack 추천 | 담당 가능 | 담당 가능 |
| install manifest 발급 | 담당 | 소비 |
| source code 접근 | 기본적으로 하지 않음 | 로컬에서만 가능 |
| bridge packet 생성 | 하지 않음 | 담당 |
| AI reply ingest | 하지 않음 | 담당 |
| validation | 하지 않음 | 담당 |
| benchmark replay | 하지 않음 | 담당 |
| proof 생성 | 표시 가능 | 생성 담당 |
| canary / rollback | 표시 가능 | 실행 담당 |

핵심:

> **웹은 선택과 배포의 control plane이고, 로컬 Cambrian은 실행과 검증의 runtime이다.**

---

## 7. 웹의 초기 V1 범위

초기 웹은 marketplace 풀버전이 아니어야 한다.
처음에는 얇은 catalog + install control plane이면 충분하다.

### Web V1 필수 기능

* pack 목록
* pack 상세 페이지
* pack compatibility 표시
* pack 포함 구성 표시
* 설치 명령 제공
* manifest 다운로드
* strongest lane 설명
* known limits 표시

### Web V1에서 아직 하지 않을 것

* 결제 marketplace
* cloud execution
* 팀 협업 workflow
* browser code editing
* provider-native agent orchestration
* public review/rating system
* automatic remote optimization

처음 목표는 단순하다.

> **사용자가 필요한 AI 작업반을 이해하고, 설치할 수 있게 만든다.**

### Current static MVP

현재 repository에는 dependency-free static Web Pack Catalog MVP가 있다.

```text
web/
  index.html
  packs/index.html
  packs/auth-bug-core.html
  assets/catalog.json
  assets/auth-bug-core.cambrian-pack.yaml
```

생성 스크립트:

```bash
python tools/generate_web_catalog.py
```

Source-of-truth:

```text
packs/catalog.yaml
packs/auth-bug-core.cambrian-pack.yaml
```

Static registry pull:

```bash
cambrian registry add local-web web/assets/catalog.json
cambrian registry sync local-web
cambrian pack search auth --registry local-web
cambrian pack show auth-bug-core --registry local-web
cambrian install pack auth-bug-core --registry local-web
```

이 흐름은 static pull만 수행한다.
웹은 pack metadata와 manifest ref를 제공하고, 실제 설치, digest verification, lockfile, provenance 기록은 local Cambrian runtime이 수행한다.
Login, payment, cloud execution, source upload, remote project analysis는 여전히 non-goal이다.
no login, no payment, no cloud execution, no source upload.

`web/assets/catalog.json`과 `web/*.html`은 derived web artifacts다.
manifest download asset은 `web/assets/auth-bug-core.cambrian-pack.yaml`에 있다.
이 static MVP는 pack을 보여주고 install command/manifest를 제공할 뿐, source code 실행이나 local runtime mutation을 하지 않는다.

---

## 8. Pack Catalog 구조

웹 catalog의 기본 단위는 pack이다.

### 8.1 Worker Pack page

보여줄 것:

* worker 이름
* 역할
* capabilities
* 추천 사용 상황
* 포함된 prompts/contracts
* known limits
* install command

### 8.2 Team Pack page

보여줄 것:

* team 이름
* lead agent
* support agents
* 협업 방식
* 추천 lane
* validation style
* install command

### 8.3 Template Pack page

보여줄 것:

* template 이름
* project defaults
* safety defaults
* agent/team defaults
* policy defaults
* compatibility
* proof summary

### 8.4 Lane Pack page

가장 중요한 page.

보여줄 것:

* lane label
* 포함 workers
* 포함 team
* 포함 template
* 포함 benchmark workset
* proof summary
* known limits
* install command

초기 canonical lane pack:

```text
auth-bug-core
```

---

## 9. Pack Detail Page 예시

예시: `Auth Bug Core`

```text
Auth Bug Core

Best for:
  Python + pytest + narrow auth/login bug fixes

Includes:
  Workers:
    - bug-fix-agent
    - regression-test-agent
    - review-agent

  Team:
    - auth-bug-team

  Template:
    - auth-bug-template

  Benchmark:
    - auth-bug-workset

Default behavior:
  - test-first
  - narrow-scope
  - review-support

Known limits:
  - not for broad auth rewrites
  - not for multi-service migration
  - not for docs-only tasks

Install:
  cambrian install pack auth-bug-core
```

이 페이지는 사용자가 “이 pack을 설치하면 뭘 얻게 되는지”를 즉시 이해해야 한다.

---

## 10. Install Manifest

웹의 가장 중요한 출력물은 install manifest다.

Manifest는 로컬 Cambrian runtime이 설치할 수 있는 pack 정의다.

예:

```yaml
schema_version: "1.0"
pack_id: auth-bug-core
pack_name: Auth Bug Core
pack_kind: lane

description: >
  A lane pack for Python + pytest + narrow auth/login bug fixes.

compatibility:
  stacks:
    - python
  test_frameworks:
    - pytest
  lane_ids:
    - python-pytest-auth-bug-core

workers:
  - id: bug-fix-agent
  - id: regression-test-agent
  - id: review-agent

teams:
  - name: auth-bug-team
    lead_agent_id: bug-fix-agent
    supporting_agent_ids:
      - regression-test-agent
      - review-agent

templates:
  - name: auth-bug-template
    policy_defaults:
      test_first_practice: true
      narrow_change_scope: true
      increase_review_support: true

benchmarks:
  - name: auth-bug-workset

install:
  auto_apply: false
  auto_bootstrap: false
  install_as_library: true

warnings:
  - This pack is strongest for narrow auth/login bug fixes, not broad refactors.
```

원칙:

* manifest는 실행 명령이 아니다.
* manifest는 설치 정의다.
* 로컬 runtime이 manifest를 검증하고 설치한다.

---

## 11. Web-to-Local Install Flow

초기 사용자 흐름은 다음과 같다.

```text
웹에서 pack 선택
→ manifest 다운로드 또는 local catalog install command 복사
→ 로컬 Cambrian에서 install
→ doctor
→ bridge/do 시작
```

예:

```bash
cambrian install manifest ./auth-bug-core.cambrian-pack.yaml
cambrian install doctor
cambrian bridge prepare "로그인 에러 수정해"
```

local catalog seed pack:

```bash
cambrian install pack auth-bug-core
```

중요:

* 웹에서 pack을 고르는 것만으로 로컬 프로젝트가 바뀌면 안 된다.
* 로컬 사용자가 install command를 명시적으로 실행해야 한다.

---

## 12. Web Recommendation

웹은 사용자의 선택을 도와줄 수 있다.

추천 기준:

* 사용자가 고른 stack
* 사용자가 원하는 작업 유형
* pack compatibility
* known proof
* current strongest lane
* pack maturity

예:

```text
Recommended for you:
  Auth Bug Core

Because:
  - you selected Python
  - you use pytest
  - you want login/auth bug fixes
```

주의:

* 웹이 사용자의 실제 코드 전체를 알 필요는 없다.
* deep project analysis는 로컬 runtime이 해야 한다.

웹 추천은 coarse recommendation이고,
로컬 Cambrian 추천은 project-aware recommendation이다.

---

## 13. Proof on Web

웹은 pack의 proof를 보여줄 수 있다.

표시 가능한 proof:

* benchmark workset
* latest proof verdict
* supported lane
* known limits
* version
* compatibility
* qualification result

예:

```text
Proof Summary:
  Workset: auth-bug-workset
  Verdict: promising
  Best mode: cambrian_full
  Known bottleneck: ambiguous_context_selection
```

주의:

* proof가 없으면 없다고 말해야 한다.
* local proof와 public proof를 구분해야 한다.
* proof를 과장하면 제품 신뢰를 잃는다.

---

## 14. Public Proof vs Local Proof

### Public proof

웹 catalog에서 제공되는 pack-level proof.

예:

* pack author가 검증한 benchmark
* public example workset
* documented known limits

### Local proof

사용자 프로젝트에서 생성된 proof.

예:

* `.cambrian/benchmarks/proof/`
* `.cambrian/metrics/`
* `.cambrian/templates/canary_reports/`

원칙:

* public proof는 참고다.
* 실제 신뢰는 local proof로 쌓인다.
* 웹은 local proof를 자동 수집하면 안 된다.
* export / opt-in 방식이 필요하다.

Implemented V1 bridge:

```bash
cambrian pack proof auth-bug-core --save
cambrian pack proof-export auth-bug-core --out packs/proof_exports/auth-bug-core.public-proof.yaml
cambrian pack proof-export-show packs/proof_exports/auth-bug-core.public-proof.yaml
cambrian pack web-sync
```

`pack proof-export` creates a privacy-safe public snapshot from the local proof card.
The snapshot can expose aggregate metrics, reputation verdict, proof status, sample size, known limits, and caveats.
It must not expose raw request text, source code, patch text, session detail, proposal text, absolute local paths, or private notes.
`pack web-sync` consumes only public-safe proof exports from `packs/proof_exports/`; local-only or blocked-sensitive proof does not raise public maturity.

Static registry bundle export is the file-based distribution step between local authoring and future hosting.

```bash
cambrian registry export --out dist/cambrian-registry --namespace cambrian
cambrian registry export-check dist/cambrian-registry
```

The bundle contains `catalog.json`, `registry.yaml`, `checksums.sha256`, copied manifests, and public-safe proof exports.
It is upload-ready for static hosting, but Cambrian does no upload, no SaaS publish, no login, no payment, and no cloud execution.
The web hiring desk is for humans, while the exported `catalog.json` is for local Cambrian runtimes to pull:

```bash
cambrian registry add demo dist/cambrian-registry/catalog.json
cambrian registry sync demo
cambrian install pack cambrian/auth-bug-core --registry demo
```

---

## 15. Web and Privacy

웹 control plane은 privacy boundary를 명확히 지켜야 한다.

기본 원칙:

* 사용자 source code는 웹으로 보내지 않는다.
* 로컬 Cambrian이 project analysis를 수행한다.
* pack install은 manifest 기반이다.
* V1 local runtime verifies pack integrity with SHA-256 and `.cambrian/install/pack_lock.yaml`.
* `cambrian pack verify` and `cambrian install verify` are local runtime commands, not web execution.
* proof upload는 explicit opt-in이어야 한다.
* raw code보다 구조화된 outcome data가 중요하다.

Cambrian의 moat는 raw code 수집이 아니라:

* validated proposal rate
* intervention rate
* replay outcome
* qualification result
* canary outcome
* template evolution history

같은 structured evidence다.

---

## 16. Web Account Model

V1에서는 account model이 복잡할 필요 없다.

가능한 단계:

### V0

* static catalog
* manifest download
* install command copy

### V1

* user account
* installed pack tracking
* license / entitlement
* private manifest access

### V2

* private organization catalog
* team-approved pack
* internal pack registry
* shared proof summary

처음부터 enterprise SaaS로 가지 않는다.
먼저 pack catalog + local install 흐름이 살아야 한다.

---

## 17. Web Catalog Maturity Levels

Pack은 maturity level을 가질 수 있다.

예:

```text
experimental
candidate
verified
canary
recommended
retired
```

의미:

### experimental

아직 proof 부족.

### candidate

사용 가능하지만 검증 제한적.

### verified

basic proof 존재.

### canary

좋아 보이지만 더 태워보는 중.

### recommended

current strongest lane에서 추천 가능.

### retired

보존은 하지만 기본 추천하지 않음.

이 maturity는 local Cambrian의 evidence 개념과 맞춰야 한다.

---

## 18. Web and Local Registry

웹 catalog와 로컬 registry는 다르다.

### Web catalog

* 공개 또는 private pack 목록
* 설치 가능한 package source
* public metadata
* public proof summary

### Local registry

* 실제 설치된 pack
* local fork
* local derivative
* local proof
* local canary
* local decisions
* local rollback

중요:

* 웹 catalog가 local state를 덮어쓰면 안 된다.
* local derivative는 사용자의 자산이다.
* imported pack update가 local evolution을 망가뜨리면 안 된다.

---

## 19. Updating Packs from Web

Pack update는 install과 다르다.

현재 구현된 것은 **local lifecycle command**다.

```bash
cambrian install diff auth-bug-core
cambrian install update auth-bug-core
cambrian install update auth-bug-core --confirm
cambrian uninstall pack auth-bug-core
cambrian uninstall pack auth-bug-core --confirm
```

업데이트는 반드시 preview가 필요하다.

Update가 보여줘야 할 것:

* new version
* changed workers
* changed templates
* changed policies
* compatibility changes
* local fork conflict
* local evolution conflict

금지:

* local derivative overwrite
* lane default silent switch
* active project template silent change

중요:

* 웹은 update/uninstall을 직접 실행하지 않는다.
* 웹은 changelog, manifest, install/update guidance를 보여줄 수 있다.
* 웹은 manifest SHA-256, trust level, verify guidance를 보여줄 수 있다.
* 실제 diff/update/uninstall은 로컬 Cambrian runtime에서 preview-first로 실행한다.
* remote/web registry 기반 update는 아직 planned다.
* remote/web registry update is still planned.
* cryptographic signing and remote registry trust are planned future layers.

---

## 20. Web and Fork / Derivative

사용자가 imported template를 local derivative로 fork할 수 있어야 한다.

웹은 원본 pack을 제공한다.
로컬 Cambrian은 사용자의 프로젝트에서 derivative를 만든다.

예:

```bash
cambrian template fork imported-auth-bug-template --as auth-bug-template-local
cambrian template evolve auth-bug-template-local
```

웹은 이 derivative를 자동으로 소유하거나 수정하지 않는다.

future:

* 사용자가 derivative를 export하여 private catalog에 publish할 수 있음
* 하지만 explicit action이어야 함

---

## 20.1 Local Pack Authoring / Publish-local

V1에서 pack 생산 흐름은 local-only다.
사용자는 로컬에서 좋아진 worker/team/template/lane을 draft, validate, build한 뒤 local catalog에 publish할 수 있다.

```bash
cambrian pack draft auth-bug-core-local --kind lane \
  --template auth-bug-template-local \
  --team auth-bug-team \
  --benchmark auth-bug-workset \
  --lane python-pytest-auth-bug-core
cambrian pack build .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack release-check packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack release-check packs/generated/auth-bug-core-local.cambrian-pack.yaml --require-proof
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --require-proof
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --confirm
cambrian pack web-sync
```

`publish-local`은 `packs/catalog.yaml`만 갱신한다.
웹은 이 catalog를 읽어 pack을 보여줄 수 있지만, remote/web publish remains future/planned.
웹은 local authoring artifact를 자동 업로드하거나, 사용자의 source/proof를 자동 수집하지 않는다.

`pack release-check`는 publish 전에 maturity와 proof status를 계산한다.
`pack web-sync`는 local catalog를 static web hiring desk로 동기화하는 derived artifact 생성이다.
웹 catalog는 `maturity`, `proof_status`, `known_limits`, install command를 보여주되, proof가 없으면 `local proof required`로 표시한다.
fake proof나 실제 없는 `validated_proposal_rate` 숫자는 표시하면 안 된다.

`cambrian pack proof [pack-id]`는 local-only proof card를 생성한다.
이 card는 usage/outcome ledger에서 `unproven`, `promising`, `useful`, `strong`, `regressed`, `insufficient_data` verdict를 계산한다.
Web catalog나 release-check가 이를 참고할 수는 있지만, raw local proof를 자동 업로드하거나 public ranking으로 바꾸면 안 된다.

---

## 21. Web and Marketplace

장기적으로 웹은 marketplace처럼 보일 수 있다.
하지만 초기에는 marketplace보다 **hiring catalog**가 맞다.

### Marketplace-like features later

* paid packs
* private packs
* author profiles
* evidence-based ranking
* organization-approved packs
* license management

### 지금 하지 않을 것

* public ranking without proof
* unverified agent spam
* generic prompt marketplace
* code execution in cloud
* opaque scoring

Cambrian marketplace가 생긴다면 핵심 차별점은:

> **이 pack이 실제로 어떤 workset에서 어떤 성과를 냈는가**

여야 한다.

---

## 22. Web Page Structure V1

초기 웹의 page는 아래 정도면 충분하다.

```text
/
  landing
/packs
  pack catalog
/packs/:id
  pack detail
/install
  install guide
/docs
  concept docs
/proof
  public proof examples
```

### Landing page 핵심 문구

```text
Install AI workers into the AI you already use.
```

한국어:

```text
이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요.
```

### Pack catalog 핵심 필터

* stack
* task type
* pack kind
* maturity
* proof available
* strongest lane

---

## 23. Web V1 Success Criteria

웹 V1이 성공하려면 아래가 되어야 한다.

1. 사용자가 Cambrian을 “AI 일꾼 설치기”로 이해한다.
2. pack이 무엇인지 이해한다.
3. auth-bug-core 같은 lane pack을 설치할 수 있다.
4. 설치 전 known limits를 본다.
5. 설치 명령을 복사할 수 있다.
6. 로컬 Cambrian doctor까지 이어진다.
7. 웹이 runtime을 대체하지 않는다.

즉 웹 V1의 성공은 화려한 dashboard가 아니라
**install-to-local-runtime 흐름이 명확한 것**이다.

---

## 24. Web V1 Non-Goals

초기 웹에서 하지 않을 것:

* browser-based IDE
* cloud code runner
* remote patch apply
* provider API orchestration
* multi-user enterprise approval
* real marketplace payment
* public user review system
* automatic code upload
* automatic project analysis

이것들은 나중 문제다.

---

## 25. Web와 Strongest Lane

웹의 초기 기본 pack은 strongest lane과 맞아야 한다.

Canonical initial pack:

```text
auth-bug-core
```

이 pack page는 Cambrian의 첫 product proof를 보여주는 대표 page가 된다.

웹은 이 pack을 통해 다음을 설명한다.

* AI worker install
* team/template/lane pack
* proof
* known limits
* local runtime install

strongest lane 바깥의 pack은 나중에 늘려도 된다.
초기에는 너무 많은 pack을 보여주지 않는 것이 좋다.

---

## 26. Web Copy Principles

웹 copy는 쉬워야 한다.

좋은 문장:

* 이미 쓰는 AI에 일꾼을 설치하세요.
* 필요한 작업반을 고용하세요.
* 에이전트를 직접 만들지 않아도 됩니다.
* Cambrian이 로컬 프로젝트에 설치하고 검증합니다.
* 좋은 일꾼은 증거를 바탕으로 계속 진화합니다.

나쁜 문장:

* harness engineering substrate
* agentic orchestration topology
* multi-layer runtime abstraction
* policy overlay fabric

내부 문서는 정확해야 하지만,
웹은 사용자의 언어로 말해야 한다.

---

## 27. Web and CLI Contract

웹이 제공하는 install command는 실제 CLI와 맞아야 한다.

예:

```bash
cambrian install pack auth-bug-core
```

이 명령은 local catalog 기반으로 구현되어 있다.
만약 나중에 remote/web registry 기반 install을 문서화한다면, 구현 전에는 그대로 쓰면 안 된다.
그 경우 다음처럼 표시해야 한다.

```text
Planned remote command:
  cambrian install pack auth-bug-core

Current local install:
  cambrian install pack auth-bug-core

Current direct manifest install:
  cambrian install manifest ./auth-bug-core.cambrian-pack.yaml
```

웹과 CLI가 어긋나면 신뢰가 깨진다.

---

## 28. Web Control Plane의 장기 방향

장기적으로 웹은 다음으로 확장될 수 있다.

### Private registry

조직별 pack catalog.

### Evidence sharing

사용자가 local proof summary를 opt-in으로 공유.

### Pack publishing

사용자가 local derivative를 publish.

### Enterprise approval

검증된 pack만 설치 가능하게 제한.

### License management

paid worker pack / team pack / lane pack.

하지만 모든 확장은 아래 원칙을 지켜야 한다.

> **웹은 고용과 배포의 control plane이고, 로컬 Cambrian은 실행과 검증의 runtime이다.**

---

## 29. 최종 요약

Cambrian Web Control Plane은 Cambrian을 사용자에게 이해시키는 핵심 surface다.

하지만 웹은 본체가 아니다.
본체는 로컬 runtime이다.

웹의 역할은:

* pack을 보여주고
* pack을 설명하고
* pack을 추천하고
* install manifest를 제공하고
* proof를 보여주고
* 로컬 Cambrian으로 이어주는 것

한 문장으로 요약하면:

> **Cambrian 웹은 AI 일꾼을 고용하는 채용 데스크이고, 로컬 Cambrian은 그 일꾼을 프로젝트에 배치하고 검증하고 진화시키는 현장 엔진이다.**
