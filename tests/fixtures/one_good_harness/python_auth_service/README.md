# One Good Harness Python Auth Service Fixture

This is a tiny, safe-to-commit fixture project for Cambrian One Good Harness replay.

It is intentionally small:

- Python source lives in `src/auth_service.py`.
- Tests live in `tests/test_auth_service.py`.
- Harness interview answers live in `fixtures/interview_answers.yaml`.
- The canned AI reply lives in `fixtures/ai_reply_analysis.yaml`.

The fixture does not contain secrets, private project data, or generated `.cambrian`
state. Cambrian should create all harness and job artifacts during replay.
