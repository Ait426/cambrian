# Cambrian Public Launch Kit

## Product One-Liner

Cambrian installs AI worker packs into the AI you already use.

이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요.

## What We Show

- Auth Bug Core worker pack
- local install
- pack activation
- pack start
- canned AI reply ingest
- validation handoff
- local proof/outcome summary

## What We Do Not Show

- remote registry
- marketplace
- rollout
- vNext
- canary/challenger
- cloud execution
- provider API call

## Product Run Flow

```bash
cd examples/auth_bug_demo
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian install doctor
cambrian pack activate auth-bug-core
cambrian pack doctor auth-bug-core
cambrian pack start "로그인 에러 수정해"
cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml
cambrian pack job-validate <job-id>
cambrian pack proof auth-bug-core
```

The reproducible product run uses a canned AI reply fixture. It does not call any AI provider.

## Product Positioning

The web page is the hiring desk.

Your local Cambrian runtime does the install, job handoff, validation, and proof.

Auth Bug Core is the first launch pack. It is best for Python + pytest + narrow auth/login bug fixes.

## Links

- [Golden Path](LAUNCH_GOLDEN_PATH.md)
- [First Run Runbook](DEMO_RUNBOOK.md)
- [Go/No-Go](GO_NO_GO.md)
- [Screenshot and Recording Checklist](SCREENSHOT_AND_RECORDING_CHECKLIST.md)
- [Launch Product Run Assets](DEMO_ASSETS.md)
- [Recording Shot List](RECORDING_SHOT_LIST.md)
- [Sanitized Terminal Transcript](SANITIZED_TERMINAL_TRANSCRIPT.md)
- [Asset Privacy Checklist](ASSET_PRIVACY_CHECKLIST.md)
- [Private Pilot Outreach Kit](PILOT_OUTREACH_KIT.md)
- [Pilot Feedback Triage](PILOT_FEEDBACK_TRIAGE.md)
- [Pilot Learning Board](PILOT_LEARNING_BOARD.md)
- [Pilot Decision Log](PILOT_DECISION_LOG.md)
- [Launch Copy](LAUNCH_COPY.md)
- [One Minute Pitch](ONE_MINUTE_PITCH.md)
- [Five Minute Product Walkthrough Script](FIVE_MINUTE_DEMO_SCRIPT.md)
