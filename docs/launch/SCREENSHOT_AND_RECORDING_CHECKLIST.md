# Screenshot and Recording Checklist

## Capture Rules

- raw private path 노출 금지
- API key 노출 금지
- local absolute path 노출 최소화
- fake metrics 금지
- local proof는 fixture evidence와 real-world proof를 구분해서 설명

## Required Captures

### Web landing hero

- Suggested filename: `01_web_landing_hero.png`
- Must show: `Install AI workers into the AI you already use.`
- Hide: browser bookmarks, personal workspace paths
- Fake proof check: no unsupported metric

### Auth Bug Core pack page

- Suggested filename: `02_auth_bug_core_page.png`
- Must show: Auth Bug Core, Best for Python + pytest + narrow auth/login bug fixes
- Hide: private local file paths
- Fake proof check: proof section must say local proof required

### README quickstart

- Suggested filename: `03_readme_quickstart.png`
- Must show: quickstart commands for Auth Bug Core
- Hide: unrelated advanced command sections
- Fake proof check: no public performance claim

### pack show auth-bug-core

- Suggested filename: `04_pack_show.png`
- Must show: install command and lane fit
- Hide: full absolute paths if possible
- Fake proof check: proof status is honest

### install pack auth-bug-core

- Suggested filename: `05_install_pack.png`
- Must show: install completed or actionable warning
- Hide: user home path if visible
- Fake proof check: no success-rate claim

### pack activate auth-bug-core

- Suggested filename: `06_pack_activate.png`
- Must show: active pack and `cambrian pack start "로그인 에러 수정해"`
- Hide: unrelated state
- Fake proof check: no apply claim

### pack start "로그인 에러 수정해"

- Suggested filename: `07_pack_start.png`
- Must show: job id, packet, next command
- Hide: raw private path if not needed
- Fake proof check: no provider call claim

### job-ingest canned AI reply

- Suggested filename: `08_job_ingest.png`
- Must show: canned AI reply fixture and patch candidate routed
- Hide: unrelated source paths
- Fake proof check: make clear this is canned first-run input

### job-validate result

- Suggested filename: `09_job_validate.png`
- Must show: validated handoff or proposal ref
- Hide: private absolute paths
- Fake proof check: validation is not adoption

### proof/outcome summary

- Suggested filename: `10_pack_proof.png`
- Must show: local proof/outcome summary
- Hide: raw personal paths
- Fake proof check: no unsupported metric or public benchmark claim

## Recording Checklist

- [ ] Start with the one-liner.
- [ ] Mention web is the hiring desk.
- [ ] Mention local runtime performs install, job handoff, validation, and proof.
- [ ] Run the Auth Bug Core commands in order.
- [ ] Say the canned AI reply avoids provider/API dependency.
- [ ] Say validation is not source mutation.
- [ ] Close with local proof and honest limitations.
