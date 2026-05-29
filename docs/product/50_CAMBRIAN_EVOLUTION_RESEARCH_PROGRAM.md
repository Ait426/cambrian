# Cambrian Evolution Research Program

Research date: 2026-05-20

## Problem Redefined

The question is not:

```text
Should Cambrian copy Meta-Harness or not?
```

The real research question is:

```text
What is the best way for a project-local AI company to become better over time without drifting, overfitting, or losing human trust?
```

Meta-Harness is one answer:

```text
search over harness code using traces and scores.
```

Cambrian should study a wider design space.

The goal is not to reproduce the newest paper.
The goal is to discover the smallest, safest, most product-useful evolution loop for real projects.

## Core Thesis

Cambrian should not start with open-ended self-modification.

Cambrian should start with:

```text
audited project-local improvement
```

That means:

1. every failure becomes structured evidence,
2. every improvement has a hypothesis,
3. every candidate is tested against project-local tasks,
4. every promotion is reversible,
5. every learned behavior is inspectable by the user.

The strongest Cambrian evolution primitive is not:

```text
harness mutation
```

It is:

```text
governed work improvement.
```

## Research Map: Evolution Methods Beyond Meta-Harness

### 1. Reflective Memory Evolution

Sources:

- MARS: https://arxiv.org/abs/2503.19271
- SAGE: https://arxiv.org/abs/2409.00872
- Experiential Reflective Learning: https://arxiv.org/abs/2603.24639
- Memento-II: https://arxiv.org/abs/2512.22716

Core idea:

Agents improve by storing past attempts, reflecting on failures, extracting reusable lessons, and retrieving them in later tasks.

Why this may beat Meta-Harness for Cambrian:

- It is cheaper than broad candidate search.
- It fits real project continuity.
- It can improve without mutating code every time.
- It is easier for users to inspect.

Risk:

- Bad memories can poison future work.
- Reflections can become vague slogans.
- Retrieval can bring irrelevant context.

Cambrian research hypothesis:

```text
Project-local reflective memory improves repeated job quality more safely than automatic harness-code mutation in early product stages.
```

Minimum experiment:

1. Record failed job traces.
2. Extract one concrete lesson per failure.
3. Re-run similar tasks with and without memory injection.
4. Measure fewer repeated mistakes, fewer changed files, and higher validation pass rate.

### 2. Audited Skill-Graph Evolution

Sources:

- Audited Skill-Graph Self-Improvement: https://arxiv.org/abs/2512.23760
- Voyager: https://arxiv.org/abs/2305.16291
- EvoSkill: https://arxiv.org/abs/2603.02766
- SkillRL: https://arxiv.org/abs/2602.08234

Core idea:

Successful trajectories are compiled into reusable skills with explicit interfaces, verifier-backed rewards, audit logs, and promotion gates.

Why this may beat Meta-Harness for Cambrian:

- Skills are product assets.
- Skill promotion is easier to audit than hidden model or prompt drift.
- Skill marketplace becomes possible only if skills have proof.

Risk:

- Too many narrow skills create clutter.
- Skills can encode brittle assumptions.
- Skill reuse can bypass fresh reasoning.

Cambrian research hypothesis:

```text
Cambrian should evolve reusable verified skills before evolving the whole harness.
```

Minimum experiment:

1. Detect repeated successful task patterns.
2. Compile a proposed skill contract.
3. Replay it against two or more tasks.
4. Promote only if it improves reliability without increasing unsafe scope.

### 3. Tree Search For Work Plans

Sources:

- SWE-Search: https://arxiv.org/abs/2410.20285
- I-MCTS: https://huggingface.co/papers/2502.14693
- ToolTree: https://arxiv.org/abs/2603.12740
- SELA / tree-search AutoML: https://arxiv.org/abs/2410.17238

Core idea:

Instead of committing to one linear plan, the agent explores a tree of possible actions, evaluates branches, backtracks, and refines.

Why this may beat Meta-Harness for Cambrian:

- Most project failures come from bad plans, not bad harnesses.
- Planning search can improve a single job without changing global defaults.
- It naturally supports rollback and alternative paths.

Risk:

- Expensive.
- Needs good value functions.
- Can waste time exploring low-value branches.

Cambrian research hypothesis:

```text
For coding and release tasks, plan-tree search improves outcome quality more directly than harness mutation.
```

Minimum experiment:

1. Generate three work plans for a task.
2. Score each plan against scope, risk, validation, and likely blast radius.
3. Execute the best plan.
4. Compare with a single linear baseline.

### 4. Process Supervision And Verifiable Rewards

Sources:

- Reflect, Retry, Reward: https://huggingface.co/papers/2505.24726
- AgentPro: https://aclanthology.org/2025.emnlp-main.506.pdf
- Verifiable Process Rewards: https://papers.cool/arxiv/2605.10325
- Agent Lightning: https://arxiv.org/abs/2508.03680

Core idea:

Do not reward only final success.
Reward verifiable intermediate reasoning, tool use, tests, and recovery decisions.

Why this may beat Meta-Harness for Cambrian:

- Product work fails in the middle, not only at the end.
- Cambrian can verify intermediate process evidence locally.
- It creates training/evolution signals without broad benchmark search.

Risk:

- Process rewards can be gamed.
- Over-instrumentation can slow work.
- Some valuable work is hard to verify step by step.

Cambrian research hypothesis:

```text
Cambrian should evolve process gates before evolving agent prompts.
```

Minimum experiment:

1. Score job traces on process quality.
2. Penalize missing evidence, skipped tests, excessive scope, and unsupported claims.
3. Reward small verified progress.
4. Use scores to alter future job-start packets.

### 5. Causal Experimentation Instead Of Blind Optimization

Core idea:

Do not just ask "which candidate scored higher?"
Ask "which specific change caused the improvement?"

Why this may beat Meta-Harness for Cambrian:

- Real projects are noisy.
- Many changes happen together.
- If Cambrian cannot explain why an improvement worked, it should not generalize it.

Risk:

- Causal experiments need controlled comparisons.
- Slow for small projects.
- Requires disciplined artifact versioning.

Cambrian research hypothesis:

```text
Cambrian needs ablation and paired replay before broad evolution.
```

Minimum experiment:

1. Create one candidate with exactly one changed variable.
2. Replay a task pair.
3. Compare only the changed behavior.
4. Promote only if improvement survives a paired comparison.

### 6. Bandit-Style Routing Evolution

Core idea:

Treat agents, skills, validators, and planning strategies as arms.
Route work to the option with the best evidence under budget and risk constraints.

Why this may beat Meta-Harness for Cambrian:

- It improves everyday routing without rewriting harnesses.
- It is cheap and incremental.
- It fits project-local evidence accumulation.

Risk:

- Early wins can dominate too strongly.
- Rare but important tasks need exploration.
- Bad metrics cause bad routing.

Cambrian research hypothesis:

```text
Cambrian should learn which agent/skill/rubric works for which project context before attempting global self-improvement.
```

Minimum experiment:

1. Track task type, chosen skill, outcome, cost, and validation result.
2. Prefer strategies with stronger local evidence.
3. Preserve controlled exploration.
4. Detect when a strategy stops working.

### 7. Human-Governed Evolution

Core idea:

Evolution should sometimes stop and ask the human.

Why this may beat Meta-Harness for Cambrian:

- Cambrian works on real projects with owner intent.
- The best technical improvement may violate business, legal, or product direction.
- Trust is a product feature.

Risk:

- Too many approval prompts kill flow.
- Human feedback can be inconsistent.

Cambrian research hypothesis:

```text
The strongest early Cambrian evolution loop is human-governed, not fully autonomous.
```

Minimum experiment:

1. Generate evolution proposals.
2. Ask for approval only when authority, product direction, or irreversible change is affected.
3. Learn from approval/rejection reasons.
4. Reduce future proposals that match rejected patterns.

## Candidate Cambrian Evolution Models

### Model A. Meta-Harness Style

```text
candidate harness -> eval -> score -> select
```

Good for:

- benchmark-like tasks
- optimizer research
- measurable narrow domains

Bad for:

- messy project work
- human governance
- broad product judgment

### Model B. Memory-First Evolution

```text
trace -> failure lesson -> memory -> future task improvement
```

Good for:

- repeated mistakes
- local project continuity
- low-cost early release

Bad for:

- novel tasks
- noisy memory
- hidden contradictions

### Model C. Skill-Graph Evolution

```text
successful trajectory -> skill candidate -> replay -> contract -> promote
```

Good for:

- marketplace future
- reusable project capabilities
- auditability

Bad for:

- one-off tasks
- over-fragmented skill libraries

### Model D. Plan-Search Evolution

```text
multiple plans -> risk/value scoring -> execute -> learn strategy
```

Good for:

- coding tasks
- release tasks
- high-uncertainty work

Bad for:

- very small tasks
- high-cost model calls

### Model E. Causal Governance Evolution

```text
single-variable candidate -> paired replay -> evidence -> gated promotion
```

Good for:

- trustworthy evolution
- product safety
- enterprise readiness

Bad for:

- fast experimentation
- hard-to-replay tasks

## Cambrian's Research Bet

Cambrian should not choose one method.
It should define an evolution ladder.

```text
L1 Memory learning
L2 Routing learning
L3 Skill promotion
L4 Plan-search improvement
L5 Harness candidate evolution
L6 Model training / RL from verified traces
```

This is stronger than copying Meta-Harness because it asks:

```text
What is the safest improvement method available at this maturity level?
```

instead of:

```text
How do we automatically mutate the harness?
```

## Near-Term Research Plan

### Experiment 1. Repeated Mistake Reduction

Question:

```text
Can Cambrian reduce repeated mistakes using structured reflective memory?
```

Metric:

- repeated warning count
- repeated failed validation count
- number of files touched unnecessarily
- user correction frequency

### Experiment 2. Skill Promotion

Question:

```text
Can Cambrian convert a successful job into a reusable verified skill?
```

Metric:

- replay pass rate
- scope safety
- time saved
- false reuse rate

### Experiment 3. Plan Search

Question:

```text
Does multi-plan scoring produce safer code changes than one linear plan?
```

Metric:

- test pass rate
- diff size
- rollback frequency
- review findings

### Experiment 4. Paired Replay

Question:

```text
Can Cambrian prove that one evolution candidate caused improvement?
```

Metric:

- paired replay delta
- regression count
- promotion confidence

## Product Judgment

Meta-Harness is impressive, but it is not the whole answer.

It optimizes a harness.
Cambrian must improve a project-working organization.

The better Cambrian research direction is:

```text
from harness optimization
to governed organizational learning.
```

This is the distinction:

```text
Meta-Harness asks:
"What harness produces a better score?"

Cambrian should ask:
"What should this project's AI company learn, and is it safe to let that learning change future work?"
```

## Next Implementation Target

The first implementation should not be full Meta-Harness search.

It should be:

```text
cambrian evolution propose --from-latest-job
```

Minimum output:

```yaml
candidate_id:
source_job:
failure_or_success_signal:
proposed_learning_type: memory | routing | skill | gate | harness
hypothesis:
evidence:
affected_surface:
eval_plan:
promotion_gate:
rollback_plan:
```

This lets Cambrian research evolution without pretending it has solved open-ended self-improvement.

## Strong Opinion

Cambrian should not chase "self-improving AI" as a slogan.

The winning product category is:

```text
governed AI organizational learning for real projects.
```

That is meaningfully different from Meta-Harness.

