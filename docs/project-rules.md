# Project-Specific Rules

Rules, conventions and constraints that apply to **this project only**.

## Why this file exists

`AGENTS.md` is the first file every agent reads, which makes it the most tempting
place to write a project rule. It is also **kit-owned**: `install-agents --upgrade`
replaces it. Rules written there used to disappear on the next upgrade, silently.

This file is **project-owned**. The installer creates it once and never touches it
again — not on `--upgrade`, not on `--force`. Write project rules here.

If a rule already lives in your `AGENTS.md`, move it here. The upgrade will now
refuse to overwrite a modified `AGENTS.md` and leave `AGENTS.md.kit-new` beside it,
but that is a safety net, not a filing system.

## What belongs here

- Repository layout and architecture specific to this project
- Named maintainers/reviewers, approval rules, protected paths
- Access rules for this project's servers and environments
- Integrations, credentials *locations* (never the credentials themselves)
- Anything an agent must know that the kit cannot know

## What does not belong here

- Secrets, tokens, passwords, private keys — see `.docs/agents/security.md`
- Product/stack description — that is `.docs/software-overview.md`
- Agent boundaries and prohibitions — that is `.docs/limits.md`
- Universal agent governance — that is `AGENTS.md`, and it is kit-owned

## Rules

- (none yet)
