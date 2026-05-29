# AI Evolution Research

Research date: 2026-05-20

## Problem Redefined

The question is not "can AI improve itself?"

The product question is:

```text
How can Cambrian convert every AI run into evidence that safely improves future AI behavior?
```

AI evolution is not one technology.
It is a loop:

```text
trace -> diagnosis -> mutation -> sandbox -> evaluation -> selection -> promotion -> monitoring -> rollback
```

Without evaluation and rollback, "AI evolution" is just drift.
Without trace and diagnosis, it is random tweaking.
Without promotion criteria, it is unsafe automation.

## Core Thesis

The strongest research direction is not direct recursive self-modification first.

The practical path is:

1. freeze the base model,
2. evolve the harness, skills, prompts, workflows, tools, memory, and routing,
3. evaluate candidates on held-out tasks,
4. promote only evidence-backed improvements,
5. later use trace datasets for RL or fine-tuning.

For Cambrian, this means:

```text
Cambrian's first evolution target is the AI company around the model, not the model weights.
```

## Research Map

### 1. Open-Ended Agent Self-Improvement

#### Darwin Godel Machine

Sources:

- https://arxiv.org/abs/2505.22954
- https://github.com/jennyzzt/dgm

What matters:

- Maintains an archive of agent variants.
- Samples a parent agent.
- Uses a foundation model to modify the agent code.
- Evaluates the child on coding benchmarks.
- Keeps successful or interesting variants.

Cambrian application:

- Build a `.cambrian/evolution/archive/` of harness, skill, workflow, and agent candidates.
- Never overwrite the active harness directly.
- Every candidate needs lineage, mutation reason, benchmark result, and rollback path.

Do not copy blindly:

- DGM is expensive and benchmark-driven.
- Cambrian must start with project-local evals, not broad open-ended self-rewriting.

#### HyperAgents

Source:

- https://arxiv.org/abs/2603.19461
- https://hyperagents.agency/

What matters:

- Attempts to merge task agent and meta-agent into one self-modifiable system.
- Tries to improve not only the task solver but the improvement process itself.

Cambrian application:

- Long-term L5 target only.
- Useful concept: Cambrian should eventually evolve its own evolution policy.

Risk:

- Meta-self-improvement without governance can become opaque.
- Cambrian must require audit, sandbox, and human override.

### 2. Evolutionary Code And Program Search

#### AlphaEvolve

Sources:

- https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
- https://arxiv.org/abs/2506.13131

What matters:

- Uses LLMs to propose code.
- Automated evaluators verify candidates.
- Evolutionary selection keeps promising programs.
- Applied to math, data centers, chip design, and AI training infrastructure.

Cambrian application:

- Use evolutionary search only where evaluation is strong.
- Good targets:
  - test command selection
  - skill procedure improvement
  - harness routing rules
  - prompt templates
  - release gate heuristics

Bad target for now:

- arbitrary product code mutation without deterministic tests.

#### OpenEvolve / CodeEvolve / GigaEvo

Sources:

- https://github.com/algorithmicsuperintelligence/openevolve
- https://huggingface.co/blog/codelion/openevolve
- https://arxiv.org/abs/2510.14150
- https://arxiv.org/abs/2511.17592

What matters:

- Open-source attempts to reproduce AlphaEvolve-like program evolution.
- Program database plus mutation plus evaluation loop.

Cambrian application:

- Study architecture for candidate archive, mutation operators, and scoring.
- Do not embed immediately; extract the pattern.

### 3. Prompt And Textual Program Optimization

#### GEPA

Sources:

- https://arxiv.org/abs/2507.19457
- https://github.com/gepa-ai/gepa
- https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/GEPA/overview.md

What matters:

- Reflective prompt evolution.
- Uses textual feedback to evolve prompts and other textual components.
- Integrated into DSPy as an optimizer.

Cambrian application:

- Best near-term fit.
- Evolve:
  - agent role prompts
  - skill procedures
  - judge rubrics
  - context packet format
  - interview questions
  - scanner heuristics

Required gate:

- No prompt mutation gets promoted without held-out job replay.

#### DSPy

Source:

- https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md

What matters:

- Treats LM programs as optimizable systems.
- Optimizers can synthesize examples, improve instructions, and tune system behavior.

Cambrian application:

- Cambrian should treat harnesses as optimizable LM programs.
- Add `cambrian harness eval` before adding automatic prompt optimization.

#### TextGrad

Sources:

- https://arxiv.org/abs/2406.07496
- https://github.com/zou-group/textgrad

What matters:

- Uses LLM-generated textual gradients to improve prompts, code, and structured text.

Cambrian application:

- Use for offline review suggestions.
- Good for "why did this agent fail?" and "what textual change would improve it?"

Risk:

- Textual gradients are advisory, not proof.

### 4. Skill And Memory Evolution

#### Voyager

Sources:

- https://arxiv.org/abs/2305.16291
- https://voyager.minedojo.org/
- https://github.com/MineDojo/Voyager

What matters:

- Automatic curriculum.
- Growing skill library.
- Environment feedback and execution errors improve skills.
- Learned skills transfer to new worlds.

Cambrian application:

- This is one of the closest patterns to Cambrian.
- Jobs should produce reusable skills only when:
  - the task recurs,
  - the solution was validated,
  - the skill has clear invocation conditions,
  - failure modes are recorded.

#### EvoSkill

Sources:

- https://arxiv.org/abs/2603.02766
- https://github.com/sentient-agi/EvoSkill

What matters:

- Automatically discovers and improves reusable agent skills from failed trajectories.
- Evaluates skill variants on held-out data.
- Uses a Pareto frontier to keep useful agent programs.

Cambrian application:

- Very high relevance.
- Cambrian should build:
  - failure trajectory parser,
  - skill candidate generator,
  - held-out validation set,
  - skill promotion gate.

#### SkillRL

Sources:

- https://arxiv.org/abs/2602.08234
- https://github.com/aiming-lab/SkillRL

What matters:

- Distills raw experience into a hierarchical skill library.
- Skill library co-evolves with policy.

Cambrian application:

- Long-term pattern for skill bank.
- Short-term: distill lessons from jobs into structured skill candidates.

#### Letta / MemGPT

Sources:

- https://github.com/letta-ai/letta
- https://docs.letta.com/concepts/letta
- https://docs.letta.com/guides/agents/context-engineering

What matters:

- Stateful agents with advanced memory.
- Agentic context engineering.
- Self-editing memory blocks.

Cambrian application:

- Cambrian needs project-local memory that is editable, explainable, and governed.
- Do not rely on opaque vector memory only.

#### Mem0 and Zep

Sources:

- https://arxiv.org/abs/2504.19413
- https://docs.mem0.ai/features/contextual-add
- https://arxiv.org/abs/2501.13956
- https://help.getzep.com/v2/memory

What matters:

- Production memory layers for agents.
- Zep emphasizes temporal knowledge graphs.
- Mem0 emphasizes practical long-term memory APIs.

Cambrian application:

- Use as design reference.
- Cambrian should remain local-first for project memory by default.
- Memory writes must be reviewable because poisoned memory changes future behavior.

### 5. Self-Reflection And Learning From Feedback

#### Reflexion

Source:

- https://arxiv.org/abs/2303.11366

What matters:

- Converts scalar/free-form feedback into verbal lessons for future attempts.
- Demonstrates practical improvement across sequential decision-making, coding, and reasoning.

Cambrian application:

- `job complete` should produce reflection records.
- Reflections must be tied to evidence, not free-floating memory.

#### Self-Refine

Sources:

- https://arxiv.org/abs/2303.17651
- https://github.com/madaan/self-refine

What matters:

- Generate output, critique it, refine, repeat.

Cambrian application:

- Use inside one job as bounded retry.
- Must stop at a fixed iteration cap and require verification.

#### STaR

Sources:

- https://arxiv.org/abs/2203.14465
- https://research.google/pubs/star-self-taught-reasoner-bootstrapping-reasoning-with-reasoning/

What matters:

- Bootstraps reasoning traces from examples and correct answers.

Cambrian application:

- Use only after Cambrian has a clean dataset of validated job reasoning.
- Strong candidate for future "explainable skill training."

### 6. Automated Agent Design And Workflow Evolution

#### ADAS

Sources:

- https://arxiv.org/abs/2408.08435
- https://github.com/ShengranHu/ADAS

What matters:

- Frames automated design of agentic systems as a research area.
- A meta-agent invents or recombines agent designs.

Cambrian application:

- Long-term: evolve agent/workforce structures.
- Short-term: create candidate workforce variants and compare on evals.

#### MetaGPT / AFlow

Sources:

- https://github.com/FoundationAgents/MetaGPT
- https://arxiv.org/abs/2308.00352

What matters:

- Multi-agent "software company" pattern.
- AFlow direction: automated workflow generation.

Cambrian application:

- Cambrian already resembles an AI company OS.
- Important lesson: roles alone are not enough; SOPs, artifacts, review, and evaluation matter.

#### ChatDev

Sources:

- https://arxiv.org/abs/2307.07924
- https://github.com/OpenBMB/ChatDev

What matters:

- Communicative agents for software development.
- Uses structured stages and communication rules.

Cambrian application:

- Useful for boardroom/workforce conversation design.
- Must add stronger evidence gates than early ChatDev-like systems.

#### AutoGen / Magentic-One

Sources:

- https://arxiv.org/abs/2308.08155
- https://arxiv.org/abs/2411.04468
- https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/orchestrations/magentic

What matters:

- Multi-agent orchestration.
- Magentic-One adds a generalist multi-agent architecture and AutoGenBench for evaluation.

Cambrian application:

- Study orchestration patterns.
- Cambrian should expose orchestration as a controlled runtime, not freeform agent chatter.

### 7. Reinforcement Learning For Agents

#### Agent Lightning

Sources:

- https://arxiv.org/abs/2508.03680
- https://www.microsoft.com/en-us/research/blog/agent-lightning-adding-reinforcement-learning-to-ai-agents-without-code-rewrites/

What matters:

- Decouples agent execution from RL training.
- Uses traces to convert agent behavior into trainable transitions.
- Can integrate with existing agent frameworks with little code modification.

Cambrian application:

- Future high-value direction.
- Cambrian's trace format should be designed so it can later feed RL systems.

Do not build first:

- RL before trace quality is premature.

#### SEAL

Sources:

- https://arxiv.org/abs/2506.10943
- https://github.com/Continual-Intelligence/SEAL

What matters:

- Language models generate their own finetuning data and update directives.

Cambrian application:

- Future model-level adaptation.
- Not near-term unless Cambrian has enough verified project-local data.

### 8. Evaluation And Benchmarks

#### OpenAI Evals

Sources:

- https://github.com/openai/evals
- https://cookbook.openai.com/examples/evaluation/getting_started_with_openai_evals

Cambrian application:

- Build project-local eval registries.
- Treat evaluation as product infrastructure.

#### LangSmith / LangChain Evals

Sources:

- https://www.langchain.com/langsmith/evaluation
- https://docs.langchain.com/oss/python/langchain/evals

Cambrian application:

- Trace comparison, experiment comparison, human feedback, and production monitoring are mandatory for evolution.

#### DeepEval

Source:

- https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd

Cambrian application:

- Add CI-friendly `cambrian harness eval`.
- Failed evals block promotion.

#### Pydantic Evals

Source:

- https://pydantic.dev/docs/ai/evals/evals/

Cambrian application:

- Code-first eval definitions are a good match for project-local tests.

#### AgentBench, GAIA, OSWorld, SWE-bench

Sources:

- https://arxiv.org/abs/2308.03688
- https://github.com/THUDM/AgentBench
- https://arxiv.org/abs/2311.12983
- https://arxiv.org/abs/2404.07972
- https://os-world.github.io/
- https://arxiv.org/abs/2405.15793

Cambrian application:

- Use public benchmarks as inspiration, not as the only truth.
- Cambrian needs project-local benchmarks because external benchmarks can be gamed or misaligned.

### 9. Safety, Security, And Governance

#### OWASP LLM Top 10

Sources:

- https://owasp.org/www-project-top-10-for-large-language-model-applications/
- https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-security/owasp-top-ten.html

Cambrian application:

- Prompt injection, excessive agency, supply-chain risk, data leakage, and tool misuse must map to deterministic gates.

#### Agent Security Bench

Sources:

- https://arxiv.org/abs/2410.02644
- https://github.com/agiresearch/ASB

Cambrian application:

- Agent evolution must include security evals.
- A candidate that improves productivity but worsens safety must not promote.

#### LlamaFirewall

Source:

- https://ai.meta.com/research/publications/llamafirewall-an-open-source-guardrail-system-for-building-secure-ai-agents/

Cambrian application:

- Study final-layer guardrails for prompt injection, agent alignment, and insecure code.

#### NIST AI RMF

Sources:

- https://www.nist.gov/itl/ai-risk-management-framework
- https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf

Cambrian application:

- Governance layer for external users.
- Evolution cannot be trusted without risk records and audit trails.

## Existing Products And Repos To Track

| Area | Project | Why It Matters To Cambrian |
|---|---|---|
| Coding agent runtime | OpenHands | Sandbox, terminal, browser, software agent SDK |
| Coding agent interface | SWE-agent | Agent-computer interface for GitHub issue solving |
| Prompt/program optimization | DSPy | Treat prompts/workflows as optimizable programs |
| Reflective optimization | GEPA | Practical prompt/skill/rubric evolution baseline |
| Textual gradients | TextGrad | Critique-to-improvement machinery |
| Evolutionary program search | AlphaEvolve / OpenEvolve | Candidate archive + evaluator + selection |
| Self-improving agents | DGM / HyperAgents | Long-term self-modifying architecture |
| Skill evolution | EvoSkill / SkillRL | Automatic skill creation from failures |
| Lifelong skill library | Voyager | Skill library + environment feedback + automatic curriculum |
| Memory | Letta / Mem0 / Zep | Stateful agent memory patterns |
| Multi-agent orchestration | AutoGen / Magentic-One | Agent coordination and evaluation |
| Multi-agent company | MetaGPT / ChatDev | AI company metaphor and staged SOPs |
| Evals | OpenAI Evals / LangSmith / DeepEval / Pydantic Evals | Evaluation infrastructure |
| Agent benchmarks | AgentBench / GAIA / OSWorld / SWE-bench | Public task and trace evaluation |
| Security | OWASP / ASB / LlamaFirewall / NIST AI RMF | Safety and governance gates |

## Technologies Cambrian Should Apply

### Apply Now

1. Evolution ledger
   - stores every candidate, mutation, result, and rollback pointer.

2. Held-out project eval bank
   - built from validated jobs and manually curated release tasks.

3. Candidate archive
   - stores harness, skill, prompt, routing, and workflow variants.

4. Maturity and fitness scoring
   - score by quality, cost, safety, speed, reproducibility, and project fit.

5. Promotion gate
   - no active default changes without eval evidence.

6. Rollback gate
   - every promoted evolution must have a reversible diff.

7. Failure-to-skill pipeline
   - job failure -> diagnosis -> candidate skill -> eval -> promote.

8. Trace schema
   - capture request, context, tool calls, decisions, validation, and outcome.

9. Security regression eval
   - prompt injection, path scope, secret access, network, git, deploy.

10. Pareto selection
   - avoid promoting a variant that improves one metric while damaging safety or cost.

### Apply Later

1. RL training adapter
   - once traces are clean enough for Agent Lightning-style training.

2. Fine-tuning data generator
   - SEAL/STaR-like self-generated training data only after strong labels exist.

3. Open-ended harness search
   - DGM/HyperAgents style, after sandbox and governance are mature.

4. Multi-project transfer
   - promote skills/harnesses across projects only with privacy-preserving evidence.

5. Marketplace evolution proof
   - sell/share only candidates with lineage, evals, risk score, and rollback.

## Cambrian AI Evolution Loop

```text
1. Observe
   capture job trace, commands, tool calls, diffs, validation, user feedback

2. Diagnose
   classify failure or success into skill, routing, context, policy, test, or harness issue

3. Hypothesize
   state a falsifiable improvement prediction

4. Mutate
   create a candidate change to skill/prompt/harness/workflow/eval

5. Sandbox
   run candidate in isolated workspace or replay mode

6. Evaluate
   run held-out evals, regression tests, security checks, and cost checks

7. Select
   compare with active baseline using Pareto criteria

8. Promote
   apply only with evidence and rollback pointer

9. Monitor
   watch future jobs for regression or drift

10. Roll back or learn
   demote failed variants; distill durable lessons into memory and skill bank
```

## Cambrian Evolution Artifacts

Required files:

```text
.cambrian/evolution/ledger.yaml
.cambrian/evolution/candidates/{candidate_id}.yaml
.cambrian/evolution/evals/{eval_id}.yaml
.cambrian/evolution/results/{run_id}.yaml
.cambrian/evolution/promotions.yaml
.cambrian/evolution/rollbacks.yaml
.cambrian/evolution/security_regressions.yaml
.cambrian/evolution/skill_bank.yaml
.cambrian/evolution/harness_archive.yaml
```

Required fields:

```text
candidate_id
candidate_type
parent_id
mutation_reason
prediction
changed_files
eval_set
baseline_score
candidate_score
safety_score
cost_delta
latency_delta
promotion_decision
rollback_command
evidence_refs
```

## Product Judgment

Cambrian should not say "AI evolved" when it merely changed a prompt.

Cambrian can say "AI evolved" only when:

1. a candidate was created from evidence,
2. the candidate made a falsifiable prediction,
3. the candidate was tested against a held-out eval,
4. the candidate beat the active baseline without safety regression,
5. the promotion was recorded,
6. rollback is available,
7. future behavior actually uses the promoted change.

## Roadmap

### Phase A: Evolution Truth Layer

Build:

- `cambrian evolution status`
- evolution ledger
- candidate schema
- result schema
- promotion schema

### Phase B: Eval Bank

Build:

- `cambrian eval add`
- `cambrian eval run`
- replay previous jobs as evals
- held-out task bank

### Phase C: Skill Evolution

Build:

- failure-to-skill generator
- skill mutation preview
- skill eval runner
- skill promotion gate

### Phase D: Harness Evolution

Build:

- harness mutation candidate
- routing rule evolution
- judge rubric evolution
- validation command evolution
- project scanner evolution

### Phase E: Agent/Workforce Evolution

Build:

- agent role mutation
- support agent selection trials
- boardroom policy evolution
- Pareto selection across quality/cost/safety

### Phase F: MCP Evolution Surface

Expose:

- `list_evolution_candidates`
- `run_evolution_eval`
- `propose_skill_mutation`
- `propose_harness_mutation`
- `promote_candidate`
- `rollback_candidate`

MCP must expose governed evolution, not uncontrolled self-editing.

## Video / Talk Watchlist

Priority:

- OpenAI Academy: Evals, the key to production-ready AI apps  
  https://academy.openai.com/public/videos/evals-the-key-to-production-ready-ai-apps-2025-06-24

- AI Engineer World's Fair: Architecting and testing controllable agents  
  https://www.ai.engineer/worldsfair/2024/schedule/architecting-and-testing-controllable-agents

- Google DeepMind AlphaEvolve announcement and companion materials  
  https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/

Secondary:

- Anthropic engineering:
  - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
  - https://www.anthropic.com/engineering/building-effective-agents
  - https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - https://www.anthropic.com/engineering/writing-tools-for-agents

## Strong Opinion

The winning product is not the one that lets an AI edit itself the most.

The winning product is the one that can say:

```text
This AI changed because this evidence proved this variant works better,
under these boundaries,
on these held-out tasks,
with this rollback path.
```

That is the evolution Cambrian should own.

