# Cambrian Skill Specification

Cambrian skill directories follow this layout:

```text
<skill>/
├── meta.yaml
├── interface.yaml
├── SKILL.md
└── execute/
    └── main.py
```

## Required files

- `meta.yaml`: skill metadata
- `interface.yaml`: input/output contract
- `SKILL.md`: human-readable skill documentation
- `execute/main.py`: required only when `meta.yaml` has `mode: "b"`

## meta.yaml

`meta.yaml` describes identity, runtime, and lifecycle fields for a skill.

### Important rules

- `id` must match `^[a-z][a-z0-9_]{1,63}$`
- `version` must follow semantic versioning like `1.0.0`
- `created_at` and `updated_at` use `YYYY-MM-DD`
- `mode` must be `a` or `b`
- when `mode` is `b`, `execute/main.py` must exist and define `run()`

## interface.yaml

`interface.yaml` defines two JSON-schema-like sections:

- `input`
- `output`

Each section must:

- have `type: object`
- define `properties`
- define `required`

Every property must include:

- `type`
- `description`

## Validation behavior

Validation runs in this order:

1. required file existence check
2. YAML parsing
3. JSON Schema validation
4. `mode`-specific execute file check
5. `execute/main.py` AST scan for `run()`

## Validation result

The validator returns:

- `valid`: overall pass/fail
- `skill_id`: parsed metadata id if available
- `errors`: blocking validation errors
- `warnings`: non-blocking warnings
