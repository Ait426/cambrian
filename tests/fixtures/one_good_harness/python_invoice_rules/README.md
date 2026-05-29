# Python Invoice Rules Fixture

This fixture is a small invoice rules project for Cambrian One Good Harness replay.
It is intentionally safe to commit and contains no secrets, private paths, network
credentials, or external service dependencies.

The fixture exists to prove that the replay gate is not tied to the auth-service
shape. Cambrian should scan it, build a project-specific harness, generate agents
and skills, accept a canned AI reply envelope, run pytest, and record a verified
job verdict without mutating source files.
