# Software Overview

## Metadata
- work_id: WK-20260504-low-token-contract-v2
- date: 2026-05-04
- owner: <maintainer>
- project_context_ready: no

This repository provides a universal, reusable agent-governance bundle for software projects.

## Install-Time Role

In this source kit, this file documents the reusable bundle itself.
When copied into a target project, the programmer must replace this content with that project's actual context and set `project_context_ready: yes` only after the file is accurate.

If this file is missing or not ready in a target project, agents must stop implementation and ask the programmer to fill it.

## Purpose
- Provide a high-quality base `AGENTS.md`.
- Provide role-specific contracts under `.docs/agents/`.
- Provide deterministic issue-management structure under `docs/issues/`.

## Components
- `AGENTS.md`: global operating contract and precedence rules.
- `.docs/agents/`: role and specialized contracts (programmer, reviewer, issue automation, security, and optional domain add-ons).
- `.docs/context-manifest.yaml`: deterministic context selection and budget contract.
- `.docs/schemas/`: machine-readable manifest and active-work state contracts.
- `docs/issues/`: local issue artifacts grouped by epic folders, with templates.
- `handoff.md`: resumable handoff notes between sessions.
- `docs/napkin-lessons.md`: concise lessons learned log.
- `.docs/workflows/`: operational workflows such as session-close.

## Intended Use
- Copy/adapt this bundle into other repositories.
- Keep only relevant specialized contracts for the target project domain.
- Keep global sections stable across projects for predictable agent behavior.

## Target Project Checklist

Installed projects should describe:
- product purpose and users
- technology stack and major modules
- runtime/deployment model
- important business rules
- external services and data stores
- known risky areas or non-obvious behavior
