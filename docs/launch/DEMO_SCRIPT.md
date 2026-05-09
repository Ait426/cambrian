# Product Walkthrough Script

## 1. 문제 제기

“AI는 이미 다들 쓰고 있습니다. 그런데 매번 어떤 역할을 시킬지, 어떤 컨텍스트를 줄지, 어떻게 검증할지 사람이 다시 조립합니다. Cambrian은 이 반복을 작업반 단위로 설치합니다.”

## 2. Cambrian 한 문장 소개

“Cambrian installs AI worker packs into the AI you already use.”

“한국어로 말하면, 이미 쓰는 AI에 검증된 AI 일꾼을 설치하는 local-first runtime입니다.”

## 3. Auth Bug Core 작업반 보기

```bash
cambrian pack list
cambrian pack show auth-bug-core
```

“오늘은 넓은 catalog가 아니라 하나만 봅니다. Auth Bug Core는 Python + pytest + auth/login bug fix에 맞춘 lane pack입니다.”

## 4. 설치

```bash
cambrian install pack auth-bug-core
cambrian install doctor
```

“설치는 source code를 고치지 않습니다. worker, team, template, workset을 로컬 Cambrian state에 설치하고 상태를 확인합니다.”

## 5. 활성화

```bash
cambrian pack activate auth-bug-core
cambrian pack doctor auth-bug-core
```

“활성화는 현재 프로젝트에서 이 작업반을 기본 작업 context로 선택하는 것입니다. template apply나 bootstrap이 아닙니다.”

## 6. 작업 맡기기

```bash
cambrian pack start "로그인 에러 수정해"
```

“여기서 Cambrian은 AI를 호출하지 않습니다. 대신 Auth Bug Core context가 들어간 packet과 job을 만들고, 사용자가 이미 쓰는 AI에 붙여넣을 수 있게 합니다.”

## 7. 준비된 AI 답변 붙이기

```bash
cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml
```

“실제 무대 데모에서는 네트워크나 API 상태에 흔들리지 않도록 준비된 AI 답변 fixture를 사용합니다. 사용자는 bridge packet id, session id를 외우지 않아도 됩니다. pack job이 중심입니다.”

## 8. 검증

```bash
cambrian pack job-validate latest
```

“검증은 apply가 아닙니다. validated proposal까지 가는 경로입니다. source 변경은 여전히 명시적인 apply 단계가 필요합니다.”

## 9. Proof 확인

```bash
cambrian pack proof auth-bug-core
```

“이 pack이 어떤 성과를 냈는지 local evidence로 봅니다. 아직 결과가 없으면 없다고 말합니다. fake proof 숫자는 만들지 않습니다.”

## 10. 마무리 문장

“Cambrian은 AI를 새로 만드는 제품이 아닙니다. 사용자가 이미 쓰는 AI에 검증된 작업반을 설치하고, 일을 맡기고, 결과를 검증하고, evidence로 남기는 제품입니다.”
