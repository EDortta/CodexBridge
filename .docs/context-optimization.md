# Context Optimization Contract

`.docs/context-manifest.yaml` is the canonical, installed policy for task context.
AI-Agents owns the contract; AI-GovernanceKit owns executable interpretation.

The manifest distinguishes mandatory base contracts, task contracts, risk contracts,
project context, active work, retrieved evidence, and reserve. A required source that
does not fit is a hard error. Optional sources may be omitted only with an explicit
warning. Similar content is reported, never removed automatically.

Reading modes:

- `full`: the whole file;
- `sections`: only exact declared Markdown headings;
- `retrieve`: deterministic lexical ranking over Markdown sections.

The structured `context-state.json` beside an active epic is additive. Existing
`RESUME.md` and `handoff.md` remain authoritative and supported. A future migration
may generate their Markdown views from structured state only after consumers have
adopted the schema; this release performs no conversion.

Token counts identify their mode and tokenizer. A tokenizer-specific count is an
estimate unless a target model with that exact tokenizer is explicitly known.

The declared `reserve` is subtracted from usable input budget. Task, risk, project,
active-work, and retrieved-evidence categories are accounted independently.

Telemetry is opt-in (`context build --telemetry`), local JSONL, metadata-only, and
requires a `work_id`. It records paths and counts, never source content. Operators
should delete entries older than the manifest's `retention_days` (30 by default).
`governancekit context telemetry prune` performs that retention operation.

```bash
governancekit context inspect
governancekit context inspect --json
governancekit context build --task implementation
governancekit context build --task implementation --risk runtime \
  --issue docs/issues/006-context-optimization-[finished]/epic.md --telemetry
```
