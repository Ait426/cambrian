# 162R-REPLACE-V3 Harness, Workforce And Skill Install Rule

Cambrian의 기본 install은 preset pack 설치가 아닙니다.

기본 생성/설치 흐름:

```bash
cambrian project scan
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
cambrian harness design
cambrian workforce generate
cambrian skill generate
cambrian harness install --confirm
```

`harness install --confirm`은 `.cambrian/harness.yaml`, `.cambrian/workforce.yaml`, `.cambrian/agents/*.yaml`, `.cambrian/skills/*.yaml`, `.cambrian/validation.yaml`, `.cambrian/operating_rules.yaml`을 설치합니다.

Pack/preset은 optional seed입니다. 프리셋 하네스/에이전트/스킬은 사용자가 명시적으로 선택할 때만 custom harness/workforce/skill 설계 참고 자료로 사용합니다.

# 162R-REPLACE-V2 Harness And Workforce Install Rule

Cambrian의 기본 install은 preset pack 설치가 아닙니다.

기본 생성/설치 흐름:

```bash
cambrian project scan
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
cambrian harness design
cambrian workforce generate
cambrian harness install --confirm
```

`harness install --confirm`은 `.cambrian/harness.yaml`, `.cambrian/workforce.yaml`, `.cambrian/agents/*.yaml`, `.cambrian/validation.yaml`, `.cambrian/operating_rules.yaml`을 설치합니다.

설치 직후 agent는 파견되지 않습니다. `workforce.yaml`에는 반드시 다음 정책이 들어갑니다.

```yaml
dispatch_policy:
  mode: on_demand
  auto_dispatch_on_install: false
```

Pack/preset은 optional seed입니다. 사용자가 명시적으로 선택할 때만 custom harness/workforce 설계 참고 자료로 사용합니다.

# 162R Custom Harness Install Rule

Cambrian의 기본 install은 preset 설치가 아니라 custom harness 설치입니다.

기본 흐름:

```bash
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
cambrian harness plan
cambrian harness install --confirm
```

`harness install`은 `--confirm` 없이는 설치하지 않습니다.

Pack/preset은 optional seed입니다. `cambrian pack install` 계열 명령은 호환/내부 distribution 경로로 유지하지만, 기본 제품 spine은 custom harness install입니다.

# Packs and Install

## 161R Compatibility Gate

Pack은 내부 distribution unit이고, 사용자가 보는 기본 단위는 harness입니다.

- Python + pytest + auth 프로젝트: `auth-bug-core`
- TypeScript + Jest + auth/API 프로젝트: `typescript-jest-auth-core`

명백히 다른 stack에 pack을 설치하려 하면 Cambrian은 `incompatible_harness`로 막고 `cambrian harness plan`, `cambrian harness install`을 안내합니다.

## 0. 160R Pack / Harness 역할 정정

사용자-facing 기본 단어는 `harness`다.

- `harness`: 특정 프로젝트에 설치되는 작업 시스템이다.
- `pack`: harness preset, worker, team, template을 담는 내부 배포 단위다.
- `auth-bug-core`: 첫 built-in harness preset이며, Cambrian 자체의 제품 정의가 아니다.

기본 설치 흐름:

```bash
cambrian project scan
cambrian harness plan
cambrian harness install
```

호환/내부 경로:

```bash
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
```

## 1. 문서 목적

이 문서는 Cambrian의 **pack** 개념과 **install** 모델을 정의한다.

Cambrian은 사용자가 직접 에이전트를 설계하게 만드는 제품이 아니다.
Cambrian은 사용자가 이미 쓰는 AI에 **검증된 AI 일꾼과 작업반을 설치**하게 해주는 제품이다.

따라서 Cambrian의 핵심 제품 단위는 단순한 agent 하나가 아니라, 설치 가능한 pack이다.

이 문서는 다음 질문에 답한다.

- Cambrian에서 pack이란 무엇인가?
- worker pack, team pack, template pack, lane pack은 어떻게 다른가?
- 웹에서 고용한 일꾼은 로컬 Cambrian에 어떻게 설치되는가?
- 설치는 정확히 어떤 artifact를 만든다는 뜻인가?
- install / update / uninstall / doctor는 어떤 원칙을 따라야 하는가?
- pack 설치가 current runtime과 future defaults에 어떤 영향을 주는가?
- 어떤 것은 설치하고, 어떤 것은 절대 설치하면 안 되는가?

---

## 2. 한 문장 정의

**Cambrian pack은 AI 일꾼, 작업반, 템플릿, 정책, benchmark evidence를 로컬 프로젝트에 설치 가능한 운영 단위로 묶은 것이다.**

사용자는 pack을 통해 다음을 얻는다.

- 직접 agent를 설계하지 않아도 됨
- 검증된 worker/team/template/policy를 로컬에 설치 가능
- 현재 프로젝트에 맞게 추천/적용/진화 가능
- benchmark와 proof로 성과를 확인 가능

즉 pack은 단순 파일 묶음이 아니라:

> **AI 일꾼을 프로젝트에 배치하기 위한 설치 가능한 운영 패키지**

다.

---

## 3. 왜 Pack이 필요한가

대부분의 사용자는 “에이전트 설계”를 하고 싶어하지 않는다.

사용자가 원하는 것은 보통 다음에 가깝다.

- 로그인 버그 고치는 작업반 설치해줘
- 리뷰 잘하는 일꾼 붙여줘
- 안전한 패치 팀 하나 넣어줘
- 내 AI를 이 프로젝트에 맞게 일하게 만들어줘

그래서 Cambrian의 제품 단위는 “agent 하나”보다 pack이어야 한다.

### 3.1 Agent 하나는 너무 작다

agent 하나만 설치하면 사용자는 여전히 많은 걸 직접 결정해야 한다.

- 이 agent를 언제 쓰는가?
- 어떤 team에 붙이는가?
- 어떤 policy가 필요한가?
- 어떤 template와 잘 맞는가?
- 검증은 어떻게 하는가?

### 3.2 Pack은 바로 일할 수 있는 단위다

pack은 필요한 구성을 같이 제공한다.

예:

- bug-fix-agent
- regression-test-agent
- review-agent
- auth-bug-team
- auth-bug-template
- auth-bug-workset
- test-first / narrow-scope policy hints

즉 pack은 사용자가 이해하기 쉬운 단위다.

> “이 일꾼 하나를 설치하세요”보다
> “로그인 버그 작업반을 설치하세요”가 훨씬 좋다.

---

## 4. Pack 종류

Cambrian은 네 가지 주요 pack 단위를 가진다.

```text
worker pack
team pack
template pack
lane pack
```

이 네 가지는 서로 중첩될 수 있다.
더 큰 pack은 더 작은 pack을 포함할 수 있다.

---

## 5. Worker Pack

### 5.1 정의

Worker Pack은 하나 또는 소수의 agent를 설치하는 pack이다.

예:

```text
bug-fix-worker-pack
review-worker-pack
regression-test-worker-pack
```

### 5.2 포함 가능 항목

Worker Pack은 다음을 포함할 수 있다.

* agent definition
* agent passport
* capabilities
* fit hints
* usage examples
* safety notes
* benchmark snippets
* recommended team roles

### 5.3 설치 결과

Worker Pack 설치 시 로컬에 반영될 수 있는 위치:

```text
.cambrian/agents/registry.yaml
.cambrian/agents/passports/
.cambrian/agents/imported/
```

### 5.4 예시

```yaml
pack_kind: worker
pack_name: auth-bug-fix-worker
agents:
  - bug-fix-agent
capabilities:
  - narrow bug fix
  - auth/login issue analysis
  - patch candidate generation
recommended_roles:
  - lead
```

### 5.5 주의

Worker Pack은 가장 작은 단위다.
초기 사용자에게는 Worker Pack보다 Team Pack 또는 Lane Pack이 더 이해하기 쉽다.

---

## 6. Team Pack

### 6.1 정의

Team Pack은 실제로 함께 일하는 agent 조합을 설치하는 pack이다.

예:

```text
auth-bug-team-pack
safe-patch-team-pack
review-heavy-team-pack
```

### 6.2 포함 가능 항목

Team Pack은 다음을 포함할 수 있다.

* team preset
* lead agent
* support agents
* recommended roles
* team fit hints
* trial/review evidence
* default use cases

### 6.3 설치 결과

Team Pack 설치 시 로컬에 반영될 수 있는 위치:

```text
.cambrian/agents/teams.yaml
.cambrian/agents/team_decisions.yaml
.cambrian/agents/team_policy_overlay.yaml
```

단, 설치만으로 active team이 자동 변경되면 안 된다.
active team 변경은 explicit `team apply` 또는 equivalent command로만 해야 한다.

### 6.4 예시

```yaml
pack_kind: team
pack_name: auth-bug-team-pack
team:
  name: auth-bug-team
  lead_agent_id: bug-fix-agent
  supporting_agent_ids:
    - regression-test-agent
    - review-agent
tags:
  - auth
  - login
  - bug_fix
  - regression_test
```

### 6.5 좋은 Team Pack의 조건

좋은 Team Pack은 다음을 가져야 한다.

* clear lead/support structure
* narrow use case
* safety notes
* test/review practice
* benchmark evidence or trial evidence

---

## 7. Template Pack

### 7.1 정의

Template Pack은 프로젝트 운영 기본값을 설치하는 pack이다.

예:

```text
auth-bug-template-pack
safe-patch-template-pack
docs-review-template-pack
```

### 7.2 포함 가능 항목

Template Pack은 다음을 포함할 수 있다.

* project defaults
* safety defaults
* agent defaults
* team defaults
* policy defaults
* context defaults
* fit hints
* lineage information
* qualification evidence

### 7.3 설치 결과

Template Pack 설치 시 로컬에 반영될 수 있는 위치:

```text
.cambrian/templates/templates.yaml
.cambrian/templates/imported/
.cambrian/templates/lineage.yaml
```

Template Pack 설치는 template를 local library에 추가하는 것이다.
현재 프로젝트에 바로 적용하는 것은 아니다.

현재 프로젝트에 적용하려면 별도 명령이 필요하다.

```bash
cambrian template diff auth-bug-template
cambrian template review auth-bug-template
cambrian template apply auth-bug-template
```

또는 uninitialized project에서는:

```bash
cambrian init --template auth-bug-template
```

### 7.4 예시

```yaml
pack_kind: template
pack_name: auth-bug-template-pack
template:
  name: auth-bug-template
  project_defaults:
    stack:
      - python
    test_command: pytest -q
    primary_use_cases:
      - bug_fix
      - regression_test
  safety_defaults:
    explicit_adoption_only: true
    preserve_source_artifacts: true
  policy_defaults:
    test_first_practice: true
    narrow_change_scope: true
    increase_review_support: true
  context_defaults:
    preferred_context_paths:
      - src/auth.py
    preferred_test_paths:
      - tests/test_auth.py
```

---

## 8. Lane Pack

### 8.1 정의

Lane Pack은 Cambrian의 가장 중요한 설치 단위다.

Lane Pack은 특정 작업군을 바로 수행할 수 있도록 아래를 함께 묶는다.

* workers
* team
* template
* policy
* benchmark workset
* proof metadata
* install guidance

예:

```text
auth-bug-core
safe-patch-core
review-support-core
```

### 8.2 왜 Lane Pack이 중요한가

사용자는 보통 “agent 하나”를 사고 싶어하지 않는다.
사용자는 특정 일을 해결하고 싶어한다.

따라서 초기 Cambrian의 가장 좋은 제품 단위는 Lane Pack이다.

예:

```text
auth-bug-core
```

이 pack은 사용자가 이렇게 이해할 수 있다.

> “로그인/인증 버그를 안전하게 고치는 작업반을 설치한다.”

### 8.3 포함 가능 항목

Lane Pack은 다음을 포함할 수 있다.

```text
worker pack references
team pack references
template pack references
policy defaults
benchmark workset
proof pack summary
doctor checks
first-run commands
```

### 8.4 설치 결과

Lane Pack 설치 시 로컬에 반영될 수 있는 위치:

```text
.cambrian/agents/
.cambrian/templates/
.cambrian/lane/
.cambrian/benchmarks/
.cambrian/harness/
```

다만 설치만으로 current runtime을 무조건 바꾸면 안 된다.
install은 library와 future defaults를 준비하는 단계다.

### 8.5 예시

```yaml
pack_kind: lane
pack_name: auth-bug-core
lane:
  lane_id: python-pytest-auth-bug-core
  label: Python + pytest + auth/login bug fixes

workers:
  - bug-fix-agent
  - regression-test-agent
  - review-agent

teams:
  - auth-bug-team

templates:
  - auth-bug-template

benchmarks:
  - auth-bug-workset

policies:
  - test_first_practice
  - narrow_change_scope
  - review_support
```

---

## 9. Pack 설치의 의미

Cambrian에서 “설치”는 다음을 의미한다.

> **pack이 포함한 agent/team/template/policy/benchmark 정의를 로컬 `.cambrian/` library와 future default 후보로 등록하는 것**

설치는 반드시 다음과 구분되어야 한다.

| 행동 | 의미 |
| --- | --- |
| install | pack을 로컬 library에 등록 |
| apply | current project에 template/team 등을 실제 반영 |
| bootstrap | 새 프로젝트 초기화 시 template defaults 사용 |
| promote | library/lane default 후보로 승격 |
| canary | stable default 전 controlled alternative로 stage |
| rollback | 승격/적용된 future default를 복구 |

즉 install은 시작일 뿐이다.

---

## 10. Web Control Plane와 Install

웹은 pack을 보여주는 catalog다.

### 웹의 역할

* pack listing
* pack 상세 설명
* recommended pack 제안
* install manifest 발급
* future private registry

### 웹이 하지 않는 것

* 프로젝트 source code 실행
* patch apply
* local benchmark replay
* runtime mutation
* current session 조작

웹은 사용자가 pack을 **고용/선택**하는 곳이다.

현재 static Web Pack Catalog MVP는 `web/` 아래에 있다.
이 웹 catalog는 `packs/catalog.yaml`에서 파생된 `web/assets/catalog.json`과 HTML page를 제공한다.
실제 설치는 여전히 로컬 CLI에서 수행한다.

```bash
cambrian install pack auth-bug-core
```

---

## 11. Local Runtime와 Install

로컬 Cambrian runtime은 pack을 실제로 설치한다.

V1에서 구현된 local catalog 탐색 명령:

```bash
cambrian pack list
cambrian pack show auth-bug-core
cambrian pack recommend
```

V1에서 구현된 local catalog 기반 설치 명령:

```bash
cambrian install pack auth-bug-core
```

이 명령은 새로운 install semantics가 아니다.
로컬 `packs/catalog.yaml`에서 manifest path를 찾고, 내부적으로 `cambrian install manifest`와 같은 installer를 사용한다.

Manifest path를 직접 지정하는 명령도 계속 지원한다.

```bash
cambrian install manifest ./packs/auth-bug-core.cambrian-pack.yaml
cambrian install list
cambrian install show auth-bug-core
cambrian install doctor
```

Static registry pull도 V1에서 구현되어 있다.
이 경로는 static web catalog 또는 local catalog file을 registry source로 등록한 뒤, local Cambrian runtime이 cache를 만들고 같은 manifest installer로 설치한다.

```bash
cambrian registry add local-web web/assets/catalog.json
cambrian registry sync local-web
cambrian pack search auth --registry local-web
cambrian pack show auth-bug-core --registry local-web
cambrian install pack auth-bug-core --registry local-web
```

Registry state:

```text
.cambrian/registries/registries.yaml
.cambrian/registries/cache/
.cambrian/registries/manifests/
.cambrian/registries/syncs/
```

`install pack --registry`는 registry cache에서 manifest ref를 찾고, manifest digest가 있으면 검증한 뒤 기존 manifest installer를 재사용한다.
서버 API, login, payment, cloud execution은 여전히 planned/non-goal이다.
no login, no payment, no cloud execution, no source upload.

Namespace / version / dependency resolver V1도 구현되어 있다.
여러 registry에 같은 pack id가 있을 때는 namespace로 구분하고, 설치 version은 lockfile에 pin한다.

Pack ref format:

```text
auth-bug-core
auth-bug-core@0.2.0
cambrian/auth-bug-core
cambrian/auth-bug-core@0.2.0
```

Dependency-aware install flow:

```bash
cambrian install plan cambrian/auth-bug-core@0.2.0 --registry official
cambrian install pack cambrian/auth-bug-core@0.2.0 --registry official --confirm-deps
```

Resolver state:

```text
.cambrian/install/graphs/
.cambrian/install/pack_lock.yaml
```

V1 resolver policy:

* exact version
* minimum version, for example `>=0.1.0`
* latest available when version is omitted
* missing required dependency blocks install
* circular dependency blocks install
* ambiguous namespace blocks install
* `--no-deps` disables dependency resolution
* dependencies require explicit `--confirm-deps` before graph install

Complex npm-style semver, dependency auto-update cascade, remote auth/licensing, and package signing are future/planned.

Future remote/web registry 기반 설치 명령:

```bash
cambrian install pack auth-bug-core
```

위 명령 이름은 이미 local catalog alias로 구현되어 있다.
Static remote/web registry lookup은 구현되어 있다.
SaaS registry API, authentication, payment/licensing은 아직 planned다.

Future 웹 발급 URL 기반:

```bash
cambrian install https://example.com/packs/auth-bug-core.yaml
```

V1에서 꼭 URL install이 필요하지는 않다.
처음에는 구현된 local catalog와 local manifest install이 기준이다.

---

## 12. Install Manifest

Pack 설치는 manifest를 중심으로 정의되어야 한다.

예시 schema:

```yaml
schema_version: "1.0"
pack_id: auth-bug-core
pack_name: Auth Bug Core
pack_kind: lane
created_at: "2026-05-02T00:00:00Z"

description: >
  Python + pytest + auth/login narrow bug-fix lane pack.

source:
  kind: local_catalog
  registry: cambrian-web-catalog
  origin_ref: auth-bug-core

compatibility:
  stack:
    - python
  test_frameworks:
    - pytest
  strongest_lane:
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
    project_defaults:
      stack:
        - python
      test_command: pytest -q
      primary_use_cases:
        - bug_fix
        - regression_test
    policy_defaults:
      test_first_practice: true
      narrow_change_scope: true
      increase_review_support: true

benchmarks:
  - name: auth-bug-workset

install:
  default_lane: python-pytest-auth-bug-core
  install_as_library: true
  auto_apply: false
  auto_bootstrap: false

warnings:
  - This pack is strongest for narrow auth/login bug fixes, not broad refactors.
```

---

## 13. Install Safety Rules

Pack install must be safe.

### 13.1 No source code mutation

Pack install must not modify project source files.

### 13.2 No auto apply

Installing a template pack must not automatically apply that template to the current project.

### 13.3 No auto bootstrap

Installing a pack must not initialize an uninitialized project unless the user explicitly runs init/start.

### 13.4 No auto promotion

Installing a pack must not automatically promote it as lane default.

### 13.5 No auto trust

Imported or installed packs should carry provenance and may require doctor/compatibility checks.

V1 trust는 signing이 아니라 SHA-256 integrity와 lockfile에서 시작한다.
`verified`는 manifest hash와 artifact refs가 맞는다는 뜻이고, `trusted`는 source policy상 허용 가능한 출처라는 뜻이다.

### 13.6 Explicit commands only

State-changing operations must require explicit commands.

Examples:

```bash
cambrian template apply auth-bug-template
cambrian team apply auth-bug-team
cambrian template qualify-stage qualification-...
```

---

## 14. Install Provenance

Every installed pack must leave provenance.

Recommended artifact:

```text
.cambrian/install/installed_packs.yaml
.cambrian/install/pack_lock.yaml
```

Possible record:

```yaml
schema_version: "1.0"
updated_at: "2026-05-02T00:00:00Z"
packs:
  - pack_id: auth-bug-core
    pack_name: Auth Bug Core
    pack_kind: lane
    status: installed
    installed_at: "2026-05-02T00:00:00Z"
    updated_at: null
    uninstalled_at: null
    source_kind: web_catalog
    source_ref: https://example.com/packs/auth-bug-core.yaml
    trust_level: trusted
    manifest_sha256: "..."
    manifest_size_bytes: 1234
    verified_at: "2026-05-02T00:00:00Z"
    latest_manifest_ref: .cambrian/install/manifests/auth-bug-core_0.1.0.yaml
    manifest_history:
      - .cambrian/install/manifests/auth-bug-core_0.1.0.yaml
    update_history: []
    uninstall_ref: null
    installed_artifacts:
      agents:
        - bug-fix-agent
        - regression-test-agent
        - review-agent
      teams:
        - auth-bug-team
      templates:
        - auth-bug-template
      benchmarks:
        - auth-bug-workset
    warnings: []
```

This provenance matters because:

* installed packs may evolve
* users may uninstall
* doctor can validate installation
* benchmark proof can link back to pack origin
* install verify can detect tampered manifest copies or missing artifact refs

V1 integrity commands:

```bash
cambrian pack verify auth-bug-core
cambrian pack verify ./packs/auth-bug-core.cambrian-pack.yaml
cambrian install verify
cambrian install verify auth-bug-core
```

V1 integrity model:

* manifest SHA-256 digest is stored in `installed_packs.yaml`
* installed pack refs are locked in `.cambrian/install/pack_lock.yaml`
* catalog entries can declare `manifest_sha256` and `trust_level`
* `--require-trusted` blocks unknown/untrusted install or update sources
* cryptographic signing, key management, and remote registry trust are planned future layers

---

## 15. Installed Pack Doctor

Cambrian should eventually support:

```bash
cambrian install doctor
```

or integrate into:

```bash
cambrian doctor
```

Doctor should check:

* installed pack manifests are valid
* referenced agents exist
* referenced teams exist
* referenced templates exist
* referenced benchmark worksets exist
* strongest lane alignment
* missing dependencies
* imported/forked template compatibility
* no source mutation occurred during install

Doctor output example:

```text
Installed packs:
  auth-bug-core

Checks:
  ✓ agents installed
  ✓ team installed
  ✓ template installed
  ✓ benchmark workset installed
  ! current project is only partial fit for auth-bug-core
```

---

## 16. Install, Apply, and Bootstrap Flow

### 16.1 Install only

```bash
cambrian install pack auth-bug-core
```

Meaning:

* add pack definitions to local library
* do not alter current runtime automatically

### 16.2 Apply to current project

```bash
cambrian template diff auth-bug-template
cambrian template review auth-bug-template
cambrian template apply auth-bug-template
```

Meaning:

* user explicitly applies template defaults to current initialized project

### 16.3 Bootstrap new project

```bash
cambrian init --template auth-bug-template
```

Meaning:

* template defaults used during project initialization

### 16.4 Guided bootstrap

```bash
cambrian init --wizard --use-recommended-template
```

Meaning:

* Cambrian recommends a template
* user explicitly selects or skips
* no silent auto bootstrap

---

## 17. Pack Upgrade

Pack upgrade is different from install.

Implemented local lifecycle commands:

```bash
cambrian install diff auth-bug-core
cambrian install update auth-bug-core
cambrian install update auth-bug-core --confirm
```

Upgrade should:

* compare installed version vs new version
* show diff
* require explicit confirmation for mutation
* avoid overwriting local forks/derivatives
* preserve lineage
* preserve local evolution

Important:

* if a user forked or evolved a template, upstream update must not silently overwrite it.
* `cambrian install update <pack-id>` is preview-first.
* actual update requires `--confirm`.
* local/remote web registry update is still planned; V1 update is local catalog or explicit manifest based.

---

## 18. Pack Uninstall

Implemented local lifecycle command:

```bash
cambrian uninstall pack auth-bug-core
cambrian uninstall pack auth-bug-core --confirm
```

Uninstall should be careful.

It may remove:

* installed pack references
* unused imported definitions
* pack provenance

It must not automatically remove:

* local derivatives
* templates currently applied
* templates used as lane default
* benchmark proof artifacts
* historical evidence
* sessions or proposals

Uninstall produces a preview first.

```bash
cambrian uninstall pack auth-bug-core
```

Actual removal requires:

```bash
cambrian uninstall pack auth-bug-core --confirm
```

If current runtime or future default references block removal, uninstall is blocked unless the user explicitly chooses `--force`.
Even with `--force`, historical proof, metrics, benchmark history, sessions, requests, proposals, local derivatives, and evolved templates must be preserved.

---

## 19. Pack Compatibility

Each pack should declare compatibility.

Example:

```yaml
compatibility:
  stacks:
    - python
  test_frameworks:
    - pytest
  request_classes:
    - bug_fix
    - regression_test
  lane_ids:
    - python-pytest-auth-bug-core
```

Compatibility is not a hard block by default.
It should inform:

* recommendation
* warning
* doctor
* bootstrap choice
* proof interpretation

Possible compatibility statuses:

* strong
* partial
* weak
* incompatible

---

## 20. Pack Evidence

A pack should not only say what it does.
It should eventually show evidence.

Possible evidence:

* benchmark report
* proof pack
* qualification report
* canary report
* replay matrix
* adoption rate
* validated proposal rate
* human intervention rate

Example:

```yaml
evidence:
  benchmark_worksets:
    - auth-bug-workset
  latest_proof_ref: .cambrian/benchmarks/proof/proof_auth-bug-workset_....yaml
  metrics:
    validated_proposal_rate: 0.52
    human_intervention_rate: 0.28
```

For V1, evidence can be local and optional.
Long term, evidence is the moat.

---

## 21. Web Catalog Product Shape

The web catalog should show packs like a hiring desk.

Each pack page should eventually show:

* name
* pack kind
* what it is good for
* install command
* compatible stack
* included workers
* included team
* included template
* benchmark/proof summary
* known limits
* version
* changelog

Example copy:

```text
Auth Bug Core

Best for:
  Python + pytest + auth/login narrow bug fixes

Includes:
  - bug-fix-agent
  - regression-test-agent
  - review-agent
  - auth-bug-team
  - auth-bug-template
  - auth-bug-workset

Install:
  cambrian install pack auth-bug-core
```

The catalog should not imply broad unsupported capability.

---

## 22. Pack Lifecycle

A pack can move through the following lifecycle.

```text
draft
→ published
→ installed
→ applied or bootstrapped
→ benchmarked
→ evolved / forked
→ qualified
→ canary
→ promoted
→ retired
```

### draft

Pack exists but is not ready.

### published

Pack is listed in catalog.

### installed

Pack is present in local Cambrian library.

### applied / bootstrapped

Pack template/team has been used.

### benchmarked

Evidence exists.

### evolved / forked

Local derivative exists.

### qualified

Derivative or variant has been compared.

### canary

Candidate is being tested as controlled alternative.

### promoted

Candidate becomes preferred lane default or library standing.

### retired

Pack remains visible but is no longer recommended by default.

---

## 23. Pack and Lineage

Packs may include templates that can be forked.

Example:

```text
imported auth-bug-template
→ local fork auth-bug-template-local
→ evolved auth-bug-template-local-v2
→ qualified stronger
→ staged as canary
→ promoted as lane default
```

Lineage must be preserved.

This matters because:

* users need to know origin
* imported templates must not be mutated in place
* local derivatives can evolve
* rollback needs provenance

---

## 24. Pack and Strongest Lane

The current strongest lane is:

```text
Python + pytest + narrow auth/login bug fix
```

The canonical initial lane pack should be:

```text
auth-bug-core
```

It should include:

* auth-bug-team
* auth-bug-template
* auth-bug-workset
* test-first / narrow-scope / review-support defaults

This is the first pack that should prove the product.

---

## 25. What Pack Install Must Not Do

Pack install must never do the following by default.

* Modify project source files
* Apply a template to current project
* Change current active team
* Change current lane default
* Promote a candidate
* Stage a canary
* Run benchmark replay
* Send code to cloud
* Start provider-specific AI execution
* Adopt a patch

All of those require explicit user actions.

---

## 26. Recommended V1 Commands

Implemented V1 local catalog commands:

```bash
cambrian pack list
cambrian pack show <pack-id-or-name>
cambrian pack recommend
cambrian pack draft <pack-id>
cambrian pack validate <draft-or-manifest>
cambrian pack build <draft-or-pack-id>
cambrian pack release-check <manifest-or-pack-id>
cambrian pack publish-local <manifest-path>
cambrian pack web-sync
cambrian install pack <pack-id-or-name>
cambrian install manifest <path>
cambrian install list
cambrian install show <pack-id-or-name>
cambrian install doctor
cambrian pack verify <pack-id-or-manifest-path>
cambrian install verify [pack-id]
cambrian install diff <pack-id>
cambrian install update <pack-id>
cambrian install update <pack-id> --confirm
cambrian uninstall pack <pack-id>
cambrian uninstall pack <pack-id> --confirm
cambrian pack doctor [pack-id-or-ref]
cambrian pack doctor auth-bug-core
cambrian pack setup [pack-id-or-ref]
cambrian pack setup auth-bug-core
cambrian pack setup-show latest
cambrian pack setup-apply latest
cambrian pack activate <pack-id>
cambrian pack active
cambrian pack next
cambrian pack start "로그인 에러 수정해"
cambrian pack job-paste job-...
cambrian pack job-ingest job-... reply.yaml
cambrian pack job-validate job-...
cambrian pack jobs
cambrian pack job-show latest
cambrian pack job-next latest
cambrian pack deactivate
cambrian pack usage [pack-id]
cambrian pack events [pack-id]
cambrian pack outcomes <pack-id>
```

Pack activation commands are implemented as first-job onboarding commands.
`pack activate` is not install, apply, bootstrap, promote, canary, or source mutation.
It only selects an installed pack as the current soft work context and lets `pack next`, `status`, `bridge prepare`, and `do` surface that context.

Pack readiness commands are implemented as a project fit doctor before activation.
`pack doctor` distinguishes installable packs from ready packs, checks project stack fit, test framework fit, installed artifact refs, trust/digest/lockfile signals, known limits, and expected first-job commands.
It does not apply templates, activate packs, bootstrap projects, install dependencies, replay benchmarks, or mutate source code.
If no pack ref is provided, `pack doctor` checks the active pack first.
Blocked reports include exact next actions such as `cambrian install pack auth-bug-core`; ready reports point to `cambrian pack activate auth-bug-core` and `cambrian pack next`.

Pack setup commands are implemented as guided repair plans for readiness blockers.
`pack setup` reads a fresh or latest readiness report and writes a checklist under `.cambrian/packs/setup_plans/`.
Steps are classified as `safe_auto_fix`, `safe_cambrian_state_fix`, `user_action_required`, `unsupported`, or `informational`.
`pack setup-apply` only applies Cambrian-state safe fixes such as activating an installed pack, regenerating the next guide, and rebuilding the readiness report.
It will not install packs, install pytest, create source/test files, apply templates, apply teams, bootstrap projects, run benchmark replay, or mutate source code.
User actions remain visible as checklist items.

Pack job commands are implemented as a pack-first first-job handoff.
`pack start` uses the active pack by default, or `--pack <pack-id>` for a specific installed pack, then creates a bridge packet and job artifact under `.cambrian/packs/jobs/`.
It respects readiness: `ready` proceeds, `partial` proceeds with warnings, and `blocked` or `unsupported` blocks with setup/doctor next actions.
It does not call an AI provider, apply code, adopt changes, bootstrap projects, promote packs, or mutate source code.
The pack-level next command remains explicit: `cambrian pack job-paste job-...`, followed by `cambrian pack job-validate job-...`.
Lower-level `cambrian bridge paste --packet packet-...` and `cambrian continue --session do-... --validate` remain the reused internals and fallback path.

Pack usage commands are implemented as local-only outcome ledger commands.
They distinguish usage events from outcomes: `pack usage` summarizes use, `pack events` lists raw local events, and `pack outcomes` links usage to validated proposal, adoption, regression-free apply, human intervention, and validation autonomy evidence where local artifacts make that attribution possible.
They do not upload telemetry, rank packs remotely, promote packs, apply templates, bootstrap projects, or mutate source code.

Pack proof card commands are implemented as local-only reputation reports.

```bash
cambrian pack proof [pack-id]
cambrian pack proof [pack-id] --save
cambrian pack proof-show latest
```

`pack proof` reads installed pack provenance, active pack context, usage summaries, outcome attribution, release metadata, and local benchmark evidence when available.
It produces a conservative reputation verdict: `unproven`, `promising`, `useful`, `strong`, `regressed`, or `insufficient_data`.
It may save YAML and Markdown cards under `.cambrian/packs/proof/`.
It does not upload local proof, auto-promote packs, auto-rank marketplace entries, apply templates, bootstrap projects, or mutate source code.

Privacy-safe public proof export commands are implemented as explicit opt-in.

```bash
cambrian pack proof-export [pack-id]
cambrian pack proof-export [pack-id] --out packs/proof_exports/<pack-id>.public-proof.yaml
cambrian pack proof-export-show <id-or-path>
```

`pack proof-export` projects a local proof card into a public-safe snapshot under `.cambrian/packs/proof_exports/` and optionally `packs/proof_exports/`.
The export keeps only aggregate metrics, verdict, proof status, maturity hint, sample size, known limits, caveats, and safe claims.
It redacts or blocks raw request text, source code, patch text, session logs, proposal text, absolute local paths, and private notes.
`pack web-sync` can read `packs/proof_exports/*.public-proof.yaml` and show the public proof summary in the static hiring desk.
No cloud upload, remote proof publish, public leaderboard, auto ranking, or fake proof is performed.

Static registry bundle export commands are implemented for publish-ready local distribution.

```bash
cambrian registry export --out dist/cambrian-registry
cambrian registry export --out dist/cambrian-registry --namespace cambrian
cambrian registry export-check dist/cambrian-registry
```

`registry export` reads `packs/catalog.yaml`, copies referenced pack manifests, copies only `public_safe` proof exports, writes `catalog.json`, `registry.yaml`, and `checksums.sha256`, and keeps all manifest refs relative to the bundle.
It does not upload the bundle, create a registry server, install packs, apply templates, bootstrap projects, or mutate source code.
`registry export-check` verifies catalog presence, manifest digest matches, proof export privacy classification, checksum consistency, and static registry sync compatibility.

Another Cambrian runtime can consume the bundle:

```bash
cambrian registry add demo dist/cambrian-registry/catalog.json
cambrian registry sync demo
cambrian install pack cambrian/auth-bug-core --registry demo
```

Implemented V1 trust option:

```bash
cambrian install pack <pack-id-or-name> --require-trusted
cambrian install manifest <path> --require-trusted
cambrian install update <pack-id> --require-trusted --confirm
```

Future remote registry commands:

```bash
cambrian install update <pack-id> --from-registry
cambrian install pack <pack-id> --registry <registry>
```

Current docs should not overpromise commands that do not exist yet.
If remote/web registry commands are not implemented, label them as future or planned.

---

## 26.1 Pack Authoring / Build / Publish-local

Pack install은 pack 소비 흐름이고, pack authoring은 좋은 local learning을 다시 설치 가능한 pack으로 만드는 생산 흐름이다.

Implemented V1 local authoring commands:

```bash
cambrian pack draft auth-bug-core-local --kind lane \
  --template auth-bug-template-local \
  --team auth-bug-team \
  --benchmark auth-bug-workset \
  --lane python-pytest-auth-bug-core

cambrian pack validate .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack build .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack release-check packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack release-check packs/generated/auth-bug-core-local.cambrian-pack.yaml --require-proof
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --require-proof
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --confirm
cambrian pack web-sync
```

Authoring artifacts:

```text
.cambrian/packs/drafts/
.cambrian/packs/builds/
.cambrian/packs/publishes/
.cambrian/packs/releases/
.cambrian/packs/web_sync/
packs/generated/
packs/catalog.yaml
```

Rules:

* `pack draft` creates editable refs, not an installed pack.
* `pack validate` checks required fields and local refs.
* `pack build` creates an installable `.cambrian-pack.yaml` manifest and computes SHA-256.
* `pack release-check` computes maturity and proof summary before catalog publish.
* `pack publish-local` is preview-first and only updates `packs/catalog.yaml` with `--confirm`.
* `publish-local` stores `manifest_sha256`, `trust_level: local`, `maturity`, `proof_status`, and release report refs.
* `--require-proof` blocks publish when proof refs are missing or too weak.
* `pack web-sync` regenerates web catalog assets from `packs/catalog.yaml`.
* build/publish never auto install, auto apply, auto bootstrap, auto promote, or auto canary.
* remote/web publish remains future/planned.

Maturity levels are conservative:

```text
draft
candidate
verified
canary
recommended
retired
```

Proof 없는 pack은 `candidate` 또는 `local proof required`로 표시한다.
Cambrian must not invent validated proposal numbers or fake proof.

The acceptance path is:

```bash
cambrian pack build .cambrian/packs/drafts/draft_auth-bug-core-local.yaml
cambrian pack release-check packs/generated/auth-bug-core-local.cambrian-pack.yaml
cambrian pack publish-local packs/generated/auth-bug-core-local.cambrian-pack.yaml --confirm
cambrian pack web-sync
cambrian pack show auth-bug-core-local
cambrian install pack auth-bug-core-local
```

---

## 27. Recommended User Journey

### Step 1. User sees pack in web catalog

```text
Auth Bug Core
```

### Step 2. User installs it locally

```bash
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
```

### Step 3. Cambrian checks fit

```bash
cambrian install doctor
```

### Step 4. User starts work

```bash
cambrian pack activate auth-bug-core
cambrian pack next
cambrian bridge prepare "로그인 에러 수정해"
```

Activation is explicit. Installing `auth-bug-core` does not automatically activate it or apply its template.

### Step 5. AI reply comes back

```bash
cambrian pack job-paste job-...
```

### Step 6. Cambrian validates

```bash
cambrian pack job-validate job-...
```

### Step 7. Cambrian measures

```bash
cambrian metrics week
cambrian benchmark proof auth-bug-workset
```

### Step 8. Cambrian evolves

```bash
cambrian improve next auth-bug-workset
```

This is the core install-to-evolution journey.

---

## 27.1 Derivative Workspace / vNext Draft

Accepted improvements are decisions, not implementation. Cambrian turns them into a derivative plan first:

```bash
cambrian pack improve auth-bug-core
cambrian pack improvement-accept item-... --resolution "vNext에서 context hint를 강화한다"
cambrian pack derivative-plan auth-bug-core
cambrian pack derivative-show latest
cambrian pack derivative-create latest --as auth-bug-core-v2
```

`derivative-create` creates only a draft under `.cambrian/packs/drafts/`.
It does not evolve templates, create benchmark cases, build, publish, install, or mutate source code.
Unresolved required changes stay visible in derivative metadata and release-check warnings until a human runs the explicit follow-up commands.

The vNext workbench turns those unresolved changes into explicit work orders:

```bash
cambrian pack derivative-workbench latest
cambrian pack workorders auth-bug-core
cambrian pack workorder-show wo-...
cambrian pack workorder-done wo-... --evidence .cambrian/templates/evolution_proposals/proposal_...yaml
cambrian pack workorder-skip wo-... --note "Not in this version"
```

Work orders track human execution only. `workorder-done` requires evidence or a note, and `workorder-skip` requires a note. Cambrian does not auto-evolve templates, create benchmark cases, change teams, mutate source code, build, publish, install, or promote a pack from the workbench. Required open/skipped work orders keep release readiness blocked and surface in validate/build/release-check warnings.

```bash
cambrian pack validate .cambrian/packs/drafts/draft_auth-bug-core-v2.yaml
cambrian pack build .cambrian/packs/drafts/draft_auth-bug-core-v2.yaml
cambrian pack release-check packs/generated/auth-bug-core-v2.cambrian-pack.yaml
cambrian pack rc .cambrian/packs/drafts/draft_auth-bug-core-v2.yaml
cambrian pack rc-show latest
cambrian pack release-local latest
cambrian pack release-local latest --confirm
cambrian pack rollout auth-bug-core-v2
cambrian pack rollout-show latest
cambrian pack rollout-apply latest
cambrian pack rollout-apply latest --confirm --install --activate
```

Release candidates freeze the current vNext draft, derivative evidence, completed workorders, build report, release-check report, changelog, and release notes under `.cambrian/packs/releases/candidates/`.
Required open workorders block `pack rc` by default. `--allow-unresolved` may create a candidate-only snapshot, but that candidate is not safe for local release.
`pack release-local` is preview-only unless `--confirm` is passed. Confirmed release reuses `pack publish-local` and updates only the local catalog/artifacts; it does not remote-publish, auto-install the new pack, uninstall the old pack, mutate source files, bootstrap, promote, or canary anything automatically.

Rollout is intentionally separate from release.
`pack rollout <new-pack>` creates a local plan that compares the previous pack, current active pack, new local release, proof/readiness summaries, changelog, and rollback hint.
`pack rollout-apply` is preview-only by default. `--confirm --install` installs the new pack through the existing pack install path, and `--confirm --activate` switches active context explicitly.
The old pack is preserved and can be restored with `cambrian pack activate <old-pack>`.

---

## 28. Success Criteria for Pack System

The pack system is working if:

1. A user can understand what to install.
2. A pack can be installed without source code mutation.
3. Installed artifacts have provenance.
4. Doctor can verify the install.
5. The pack can be used in bridge/do/benchmark flows.
6. Pack performance can be measured.
7. A pack can be forked/evolved if needed.
8. A better derivative can be qualified and promoted.
9. Bad promotion can be rolled back.
10. The user does not need to understand all internal harness details to get value.

---

## 29. Final Summary

Cambrian packs are the bridge between product language and runtime architecture.

Externally, they are:

> **AI 일꾼과 작업반을 설치하는 상품 단위**

Internally, they are:

> **agents, teams, templates, policies, benchmarks, and proof metadata bundled into a local-first installable operating unit**

The first important pack should be:

```text
auth-bug-core
```

because it aligns with Cambrian's current strongest lane:

```text
Python + pytest + narrow auth/login bug fix
```

One sentence summary:

> **A Cambrian pack is an installable AI workforce unit that gives a user ready-to-run workers, teams, templates, and proof paths without requiring them to design agents from scratch.**
