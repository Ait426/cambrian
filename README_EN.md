# Cambrian

**A self-evolving skill engine for AI agents.**

Every AI framework today runs the same tools the same way, forever. Cambrian is different: it treats AI capabilities as *skills that evolve*. When a skill fails, Cambrian runs an autopsy, searches for better alternatives, absorbs them, and retries — without human intervention. When you give feedback, it mutates the skill instructions, benchmarks the variant against the original, and keeps the winner.

Use it 100 times, and it gets better 100 times.

```
$ cambrian run -d analytics -t summarize -i '{"csv_data": "Month,Revenue\nJan,12500\nFeb,15800"}'
[FAIL] No skill for domain 'analytics'
[AUTOPSY] skill_missing — No skill available to handle this task
[SEARCH] Found 'csv_to_chart' in external/
[SECURITY] AST scan: no violations
[ABSORB] Copied to skill_pool/
[RETRY] Executing with 'csv_to_chart'
[OK] Task completed (142ms) | Fitness: 0.1000
```

---

## Why Cambrian?

| What exists today | What Cambrian does differently |
|---|---|
| Frameworks pick from a fixed set of tools | Skills are absorbed, mutated, and evolved at runtime |
| Run a tool 100 times → same quality | Run a skill 100 times → it gets better |
| Failure = error log | Failure = autopsy → search → absorb → retry |
| Human decides which tool to use | Engine benchmarks candidates and picks the best |
| Tools are static code | Skills are LLM instruction documents that evolve |

---

## Core Concepts

**Skill** — An LLM instruction document (`SKILL.md`) that tells a model how to perform a task. Not a code snippet. Not a prompt template. A complete, typed, versionable unit of AI capability.

**Mode A / Mode B** — Mode A: the LLM reads `SKILL.md` and generates output each time (exploration). Mode B: verified code runs directly via subprocess (crystallized). Skills start in Mode A and graduate to Mode B when patterns stabilize.

**Evolution** — Users give feedback (1–5 rating + comment). The engine feeds the current `SKILL.md` + feedback to an LLM, which produces a mutated version. The original and variant are benchmarked head-to-head. Winner stays, loser is discarded.

**Fitness** — `(successes / total) × min(total / 10, 1.0)`. A skill that succeeded 3/3 times scores lower than one that succeeded 8/10, because confidence requires volume.

---

## Quick Start

```bash
# Clone
git clone https://github.com/your-username/cambrian.git
cd cambrian

# Install
pip install -e ".[dev]"

# Run a skill
cambrian run -d data_visualization -t csv chart \
  -i '{"csv_data": "Month,Revenue\nJan,100\nFeb,150\nMar,120", "chart_type": "bar"}'

# List registered skills
cambrian skills

# View skill details
cambrian skill csv_to_chart
```

### Prerequisites

- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable (for Mode A skills and evolution)

---

## Evolution Loop

```bash
# 1. Run a skill and see the output
cambrian run -d data_visualization -t csv chart \
  -i '{"csv_data": "Q,Sales\nQ1,200\nQ2,350", "chart_type": "line"}'

# 2. Give feedback
cambrian feedback csv_to_chart 3 "Chart looks good but axis labels are too small"

# 3. Evolve the skill (mutate → benchmark → adopt or discard)
cambrian evolve csv_to_chart \
  --input '{"csv_data": "Q,Sales\nQ1,200\nQ2,350", "chart_type": "line"}'
# [OK] Evolution complete — variant adopted
#   Skill: csv_to_chart
#   Parent fitness: 0.3000
#   Child fitness:  0.5000

# 4. Check evolution history
cambrian history csv_to_chart

# 5. Rollback if needed
cambrian rollback csv_to_chart 1
```

---

## Benchmark (Harness)

Compare multiple skills head-to-head on the same input:

```bash
cambrian benchmark -d data_visualization -t csv chart \
  -i '{"csv_data": "A,B\n1,2\n3,4", "chart_type": "bar"}'
# RANK  SKILL_ID             OK     TIME(ms)   FITNESS
# 1     csv_to_chart         [OK]   142        0.3000
# 2     old_chart_v1         [OK]   580        0.1000
# 3     broken_chart         [FAIL] 23         0.0000
# Best: csv_to_chart | 2/3 succeeded
```

---

## Architecture

```
┌──────────────────────────────────────────┐
│               Cambrian Engine            │
├──────────┬───────────┬───────────────────┤
│ Executor │ Benchmark │    Evolution      │
│ Mode A/B │ rank+pick │ mutate→bench→adopt│
├──────────┴───────────┴───────────────────┤
│ Registry (SQLite)  │  Autopsy (rules)    │
│ skills + feedback  │  failure → diagnosis│
│ + evolution history│                     │
├────────────────────┼─────────────────────┤
│ Absorber           │  Security Scanner   │
│ validate → copy    │  AST-based scan     │
├────────────────────┴─────────────────────┤
│ Loader + Validator (JSON Schema)         │
└──────────────────────────────────────────┘
         ↕
┌──────────────────┐    ┌──────────────────┐
│  skills/         │    │  skill_pool/     │
│  (seed skills)   │    │  (absorbed)      │
└──────────────────┘    └──────────────────┘
```

## Project Structure

```
cambrian/
├── engine/
│   ├── executor.py       # Skill execution (Mode A: LLM, Mode B: subprocess)
│   ├── benchmark.py      # Head-to-head skill comparison + ranking
│   ├── evolution.py      # Mutation via LLM + benchmark-based adoption
│   ├── registry.py       # SQLite: skills, feedback, evolution history
│   ├── autopsy.py        # Rule-based failure analysis
│   ├── security.py       # AST-based malicious code detection
│   ├── absorber.py       # External skill ingestion pipeline
│   ├── loader.py         # Skill directory → Skill object
│   ├── validator.py      # JSON Schema validation
│   ├── loop.py           # Main engine orchestration
│   ├── cli.py            # CLI interface
│   ├── models.py         # Domain objects (dataclasses)
│   └── exceptions.py     # Custom exceptions
├── schemas/              # JSON Schema definitions (do not modify)
├── skills/               # Seed skills (csv_to_chart, json_to_dashboard, landing_page)
├── skill_pool/           # Runtime-absorbed skills
├── tests/                # 110+ tests
└── pyproject.toml
```

---

## Skill Format

Every skill is a directory with three required files:

```
my_skill/
├── meta.yaml          # ID, domain, tags, mode, runtime config
├── interface.yaml     # Input/output JSON Schema
├── SKILL.md           # LLM instructions (this is what evolves)
└── execute/           # (Mode B only)
    └── main.py        # stdin JSON → stdout JSON
```

### meta.yaml

```yaml
id: "csv_to_chart"
version: "1.0.0"
name: "CSV to Chart"
description: "Converts CSV data to Chart.js HTML"
domain: "data_visualization"
tags: ["csv", "chart", "html"]
mode: "a"                    # "a" = LLM generates, "b" = code executes
runtime:
  language: "python"
  timeout_seconds: 60
```

### SKILL.md

The heart of a skill. This is the system prompt that the LLM reads to produce output. When a skill evolves, this file is what changes.

---

## How Evolution Works

```
User feedback ──→ Collect ratings + comments
                        │
                        ▼
              ┌─────────────────┐
              │  LLM Mutation   │
              │                 │
              │ Current SKILL.md│
              │ + feedback      │──→ New SKILL.md (variant)
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   Benchmark     │
              │                 │
              │ Original skill  │
              │ vs Variant      │──→ Head-to-head comparison
              └────────┬────────┘
                       │
              ┌────────┴────────┐
              │                 │
          Variant wins      Original wins
              │                 │
              ▼                 ▼
         ADOPT variant     DISCARD variant
         (overwrite         (keep original
          SKILL.md)          unchanged)
              │                 │
              └────────┬────────┘
                       │
                       ▼
              Save EvolutionRecord
              (rollback available)
```

---

## Tests

```bash
# Run all tests (Mode A tests skipped without API key)
pytest tests/ -v

# Run only unit tests (no API key needed)
pytest tests/ -v -k "not requires_api_key and not Api"

# Run evolution E2E with mock LLM
pytest tests/test_e2e_evolution.py -v -k "Mock"

# Run with real API
ANTHROPIC_API_KEY=sk-... pytest tests/ -v
```

Current: **110 passed, 12 skipped, 0 failed**

---

## Built-in Skills

| Skill | Domain | Mode | Description |
|-------|--------|------|-------------|
| `csv_to_chart` | data_visualization | A | CSV → Chart.js interactive chart |
| `json_to_dashboard` | data_visualization | A | JSON metrics → dashboard HTML |
| `landing_page` | design | A | Product info → Tailwind landing page |
| `hello_world` | testing | B | Minimal test skill |

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `cambrian run -d DOMAIN -t TAGS -i INPUT` | Execute a task |
| `cambrian skills` | List all registered skills |
| `cambrian skill SKILL_ID` | Show skill details |
| `cambrian benchmark -d DOMAIN -t TAGS -i INPUT` | Compare skills head-to-head |
| `cambrian feedback SKILL_ID RATING COMMENT` | Submit feedback |
| `cambrian evolve SKILL_ID --input TEST_INPUT` | Evolve a skill |
| `cambrian history SKILL_ID` | View evolution history |
| `cambrian rollback SKILL_ID RECORD_ID` | Rollback to pre-evolution state |
| `cambrian absorb PATH` | Absorb an external skill |
| `cambrian remove SKILL_ID` | Remove an absorbed skill |
| `cambrian stats` | Engine statistics |

---

## Tech Stack

- **Python 3.11+** — no exotic dependencies
- **SQLite** — registry, feedback, evolution history (no ORM)
- **subprocess + timeout** — sandboxed skill execution
- **AST analysis** — security scanning (no eval, no network abuse)
- **Anthropic API** — Mode A execution and skill mutation
- **pytest** — 110+ tests with mock and real API coverage

---

## What Cambrian Is Not

- **Not an LLM.** It uses LLMs (currently Claude) but doesn't train or fine-tune them.
- **Not an agent framework.** It's an engine that makes agents better. Agents are chefs; Cambrian is the evolving recipe book.
- **Not a prompt marketplace.** Skills evolve through use, not through curation.

---

## Roadmap

- [ ] Skill fusion (merge knowledge from multiple skills into a new SKILL.md)
- [ ] Mode A → Mode B auto-crystallization (repeated identical patterns → code)
- [ ] MCP server integration (plug Cambrian into any agent via Model Context Protocol)
- [ ] Multi-model support (OpenAI, Gemini, local models)
- [ ] Skill decay and programmed extinction (unused skills → dormant → fossil)
- [ ] Cross-domain evolution (marketing skill + data skill → new hybrid)

---

## License

MIT

---

*Cambrian: because AI skills should evolve, not just execute.*
