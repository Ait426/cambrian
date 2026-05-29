# Perfect Harness Research

Research date: 2026-05-20

## Problem Redefined

The question is not "how do we generate better harness files?"

The real question is:

```text
How do we build an external control system that makes AI behavior bounded, observable, verifiable, recoverable, and better over time?
```

A perfect harness is not a prompt layer.
It is a runtime control loop around an AI system.

## Core Thesis

The best current research points to one conclusion:

```text
Model quality is no longer enough.
The harness around the model determines what the AI can see, what it may do, how it is judged, how it recovers, and how future behavior improves.
```

Cambrian should therefore treat harness engineering as a first-class product category, not a setup wizard.

## Must-Read Sources

### 1. Meta-Harness

Source:

- https://arxiv.org/abs/2603.28052
- https://github.com/stanford-iris-lab/meta-harness

Key idea:

Harnesses are the code around a fixed model that decides what to store, retrieve, and show while the model works. Meta-Harness searches over harness code using prior scores and execution traces.

Implication for Cambrian:

- Harness files must be editable, testable, and comparable.
- The target is not "generate one good harness" but "search for better harnesses over time."
- Cambrian should preserve every failed/successful harness candidate with outcome evidence.

### 2. Agentic Harness Engineering

Source:

- https://arxiv.org/abs/2604.25850

Key idea:

Harness evolution needs observability at three levels:

- component observability: every editable harness component is represented as a file.
- experience observability: traces become a layered evidence corpus.
- decision observability: every edit declares a prediction and is later checked against outcomes.

Implication for Cambrian:

- Every Cambrian harness edit must carry a falsifiable prediction.
- `job complete` must not just record outcome; it must update evidence for or against the harness decision.
- Evolution without trace/evidence is noise.

### 3. Harness-Native Software Engineering

Source:

- https://research.chaitanya.science/papers/harness-native-software-engineering

Key idea:

The agent harness control plane has eight functions:

- context ingress
- action mediation
- execution substrate
- state persistence
- verification and review
- recovery and debugging
- delegation and coordination
- governance and audit

Implication for Cambrian:

Cambrian's harness contract should cover all eight functions. If one is missing, the harness is partial.

### 4. Anthropic Agent Evals

Source:

- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://docs.anthropic.com/en/docs/build-with-claude/develop-tests

Key idea:

Agent evals must measure multi-turn behavior, tool use, environment changes, and final outcomes. Evals should be built before the agent can pass them.

Implication for Cambrian:

- Cambrian needs eval-driven harness development.
- Gold path should include regression tasks, trajectory checks, static analysis, and browser/tool tests when applicable.
- Evaluation is not an afterthought; it defines the product requirement.

### 5. Affordance Agent Harness

Source:

- https://arxiv.org/abs/2605.00663

Key idea:

A closed-loop runtime selects skills through a Router, checks evidence sufficiency with a Verifier, retries targeted parts, and controls cost.

Implication for Cambrian:

- Skill selection must be evidence-gated.
- "Search and fuse skills" is weak unless the selected skill has evidence, cost, and verification contracts.
- Cambrian should retry targeted weak steps instead of blindly restarting the whole job.

### 6. Symbolic Guardrails

Source:

- https://huggingface.co/papers/2604.15579

Key idea:

Some safety/security requirements need deterministic symbolic policy checks, not neural or prompt-only guardrails.

Implication for Cambrian:

- Permissions, forbidden paths, secret access, network use, git operations, and deployment must be hard policy gates.
- Korean/English natural language policy can be accepted, but it must compile into deterministic enforcement.

### 7. Guardrails As Infrastructure

Source:

- https://huggingface.co/papers/2603.18059

Key idea:

Guardrails should be infrastructure: policy-first control around tool-orchestrated workflows, with runtime enforcement and actionable fix hints.

Implication for Cambrian:

- A warning is not enough.
- The harness should block unsafe action and tell the AI what evidence or authority is missing.

### 8. Copilot Evaluation Harness

Source:

- https://arxiv.org/abs/2402.14261

Key idea:

LLM-guided development must be evaluated across real IDE workflows: generation, docs, tests, bug fixing, and workspace understanding, using static and execution-based metrics.

Implication for Cambrian:

- Cambrian's agent quality cannot be judged by one "did it answer?" metric.
- We need task-type metrics: fix, test, explain, refactor, workspace-understanding, release-readiness.

### 9. OpenAI Evals

Source:

- https://github.com/openai/evals
- https://cookbook.openai.com/examples/evaluation/getting_started_with_openai_evals

Key idea:

High-quality evals are one of the most impactful things for teams building LLM systems. A good eval framework gives custom tests, datasets, and benchmark registries.

Implication for Cambrian:

- Cambrian should own a project-local eval registry.
- Every harness should ship with at least one local eval suite.

### 10. LangSmith / LangChain Evals

Source:

- https://www.langchain.com/langsmith/evaluation
- https://docs.langchain.com/oss/python/langchain/evals
- https://docs.langchain.com/langsmith/evaluation-concepts

Key idea:

Agent quality requires traces, datasets, offline evals, online evals, human review, experiment comparison, and production monitoring.

Implication for Cambrian:

- `.cambrian/jobs/*` should become a trace/eval dataset, not just history.
- Compare harness versions side-by-side on the same task bank.

### 11. DeepEval

Source:

- https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd

Key idea:

LLM evals should fit CI/CD. DeepEval treats evals like tests and runs them through a pytest-compatible workflow.

Implication for Cambrian:

- Cambrian should expose `cambrian harness eval` and make it CI-friendly.
- The gold path must fail in CI when the harness regresses.

## Video / Talk Watchlist

Priority watch:

- OpenAI Academy: Evals, the key to production-ready AI apps  
  https://academy.openai.com/public/videos/evals-the-key-to-production-ready-ai-apps-2025-06-24

- AI Engineer World's Fair: Architecting and testing controllable agents  
  https://www.ai.engineer/worldsfair/2024/schedule/architecting-and-testing-controllable-agents

Secondary watch:

- Anthropic Engineering articles that function like talks:
  - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
  - https://www.anthropic.com/engineering/building-effective-agents
  - https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - https://www.anthropic.com/engineering/writing-tools-for-agents

## Perfect Harness Architecture

Cambrian's perfect harness should have nine planes.

### 1. Intent Plane

Captures:

- user goal
- product goal
- task type
- success criteria
- non-goals

Failure if missing:

- AI optimizes for plausible activity instead of desired outcome.

### 2. Boundary Plane

Captures:

- allowed paths
- forbidden paths
- authority mode
- network policy
- secret policy
- git/deploy/payment policy

Failure if missing:

- AI acts outside the user's intended risk boundary.

### 3. Context Plane

Captures:

- project identity evidence
- source-code evidence
- docs evidence
- prior mistakes
- relevant jobs
- current working state

Failure if missing:

- AI hallucinates the project domain or repeats old mistakes.

### 4. Routing Plane

Captures:

- agent selection
- skill selection
- tool selection
- support roles
- confidence and reason codes

Failure if missing:

- The wrong agent/skill is installed or dispatched because of keyword noise.

### 5. Execution Plane

Captures:

- task packet
- sandbox/runtime
- timeout
- command strategy
- write scope
- rollback hint

Failure if missing:

- AI output is not reproducible and cannot be safely retried.

### 6. Verification Plane

Captures:

- test commands
- static checks
- trace checks
- browser checks
- LLM judge rubrics
- human review gates

Failure if missing:

- The product looks improved but is not proven improved.

### 7. Recovery Plane

Captures:

- failure category
- last error
- retry strategy
- escalation path
- missing evidence request

Failure if missing:

- AI loops, guesses, or hides uncertainty.

### 8. Learning Plane

Captures:

- outcome evidence
- mistakes
- win patterns
- skill fitness
- agent fitness
- harness candidate fitness

Failure if missing:

- Every run starts from zero and quality remains random.

### 9. Governance Plane

Captures:

- audit log
- authority changes
- policy decisions
- promotion/rollback decisions
- marketplace/export boundary

Failure if missing:

- A harness cannot be trusted by an external user or another machine.

## Cambrian Design Law

Every core feature must answer this:

```text
Which harness plane does this strengthen?
Which gate does it enforce?
Which evidence does it produce?
Which future behavior does it improve?
```

If the answer is unclear, it is probably not core harness work.

## Research-Based Roadmap

### Phase 1: Harness Truth

Goal:

- Installed harness state is truthful and complete.

Build:

- status maturity score
- partial/broken harness detection
- active harness summary
- installed gate map

### Phase 2: Blocking Gates

Goal:

- Cambrian blocks weak harness behavior instead of warning only.

Build:

- install gate
- job start gate
- validate gate
- complete gate
- evolve gate

### Phase 3: Trace And Eval Corpus

Goal:

- Every job becomes reusable evaluation data.

Build:

- trace schema
- outcome schema
- eval dataset export
- repeatable eval command

### Phase 4: Harness Evolution

Goal:

- Harness candidates improve from evidence.

Build:

- candidate lineage
- prediction contract
- canary eval
- rollback
- promotion criteria

### Phase 5: MCP Attachment

Goal:

- External AIs can use Cambrian as a real harness control plane.

Expose:

- `scan_project`
- `fit_harness`
- `show_harness_status`
- `start_job`
- `validate_job`
- `complete_job`
- `review_evolution`

MCP should expose the control loop, not a harness description generator.

