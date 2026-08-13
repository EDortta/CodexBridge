# How AI Agents Work in IDE Chat (VSCodium Example)

AI agents in an IDE are assistants that can read your project files, suggest code, edit files, run commands, and explain decisions through chat.

In tools like VSCodium (with an AI extension), the chat panel is your command center.
You describe what you want, and the agent performs steps inside your project.

## 1. What The Agent Can Do

Typical capabilities:
- read your codebase and summarize architecture
- propose and apply code changes
- run tests and lint commands
- explain errors and fix them
- create docs, templates, and checklists

The agent is strongest when you give it clear scope and constraints.

## 2. How To Talk To The Agent (Beginner-Friendly)

Use this simple prompt structure:
1. Goal: what you want built/fixed
2. Context: files/modules involved
3. Constraints: rules, boundaries, style
4. Done criteria: how success is validated

Example:

```text
Goal: Add password reset endpoint.
Context: backend auth module and user email service.
Constraints: keep API backward compatible, do not change DB schema.
Done: tests pass and endpoint is documented.
```

## 3. Good Chat Workflow

Use a short loop:
1. Ask the agent to inspect and summarize first.
2. Ask for a step-by-step plan.
3. Ask it to implement one scoped change.
4. Ask it to run checks/tests.
5. Ask for a concise change summary with file list.

This keeps control with you while still moving fast.

## 4. Files You Should Always Reference

In this kit, the programmer should always align with:
- `docs/software-overview.md`: what the software is and why it exists (mandatory file the programmer must edit for each project)
- `docs/limits.md`: hard boundaries (what can/cannot be done) (mandatory file the programmer must edit for each project)
- `AGENTS.md`: execution contract and quality/security expectations

Before implementation, ask the agent to confirm these files were read.

Example:

```text
Before coding, read AGENTS.md, docs/software-overview.md, and docs/limits.md.
Confirm constraints, then propose a plan.
```

## 5. How To Avoid Common Mistakes

- Do not ask for broad “refactor everything” prompts.
- Do not skip constraints (security, privacy, scope limits).
- Do not accept changes without tests/check output.
- Do not allow hidden assumptions; ask the agent to state them.

## 6. Privacy and Security for Novices

When your feature touches personal data, explicitly ask for:
- privacy impact (GDPR/LGPD-style)
- retention/deletion behavior
- logging safety (no sensitive data leaks)

Who should use these files:
- Programmer: use them as a checklist and include these requirements in the chat prompt.
- AI agent: follow these files during implementation and review.

Files to reference:
- `.docs/agents/privacy-compliance.md`
- `.docs/agents/security.md`

## 7. Practical Prompt Starters

- "Analyze this bug and show root cause before editing code."
- "Propose 2 solutions with trade-offs, then implement the safest one."
- "Apply minimal scoped fix and run only impacted tests."
- "List files changed and why each file was necessary."
- "If request exceeds docs/limits.md, stop and ask for approval."

## 8. Final Rule

Think of AI chat as pair-programming:
- you set intent and constraints
- the agent executes with speed
- you approve quality and direction

Better prompts produce better code.
