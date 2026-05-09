# Pilot Feedback Triage

## Purpose

Turn raw pilot feedback into launch decisions.

Use this triage after each private pilot call so feedback becomes a decision, a fix priority, or a deferred note instead of loose conversation memory.

## Privacy Rule

Do not commit real participant names, emails, company names, or private project details.
Use anonymized IDs such as P01, P02.
Keep the real tracker in a private location outside the repo.

## Severity

### P0 - Launch blocker

Fix before the next public-facing product run or pilot round.

- 3+ out of 5 users cannot understand the product one-liner.
- Users do not understand what Auth Bug Core is.
- install / activate / start repeatedly fails during the product run.
- The "AI worker pack" / "AI 작업반 설치" phrase fails for most users.
- A pilot flags fake proof or overclaim.
- The product run cannot be reproduced without an API key or external network.

### P1 - Pilot conversion blocker

Fix before expanding the pilot group.

- Users understand the product but do not feel a reason to try it.
- CLI difficulty appears in repeated feedback.
- Users do not know what to do after `pack start`.
- proof/validation does not feel important or credible.
- Price/value connection is weak.

### P2 - Product improvement

Track for the next polish pass.

- Specific command copy feels awkward.
- README or runbook needs clearer wording.
- Users request another pack.
- The product run fixture feels too narrow.
- Screenshot or recording assets need improvement.

### P3 - Later / nice-to-have

Important input, but not a launch blocker.

- marketplace request.
- remote registry request.
- team collaboration SaaS request.
- provider API automation request.
- enterprise admin request.

## Feedback Categories

- understanding
- install friction
- activation friction
- first-job friction
- validation/proof confusion
- value signal
- buying signal
- trust concern
- requested pack
- messaging confusion

## Triage Table Template

| ID | Participant | Category | Severity | Raw signal | Interpretation | Next action | Owner | Status |
|---|---|---|---|---|---|---|---|---|
| T-001 | P01 | understanding | P1 |  |  |  |  | open |

## Rules

- Do not store real personal info in the repo.
- Use anonymized participant IDs.
- Do not overreact to one-off feedback.
- Repeated confusion from 3+ users becomes P1 or P0.
- A single direct trust concern about overclaim should be reviewed before the next product run.
- Requested packs are signal, not permission to expand launch scope immediately.
