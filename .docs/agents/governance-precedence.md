# Governance: Role Precedence and Conflict Rounds

Cross-cutting rules for situations where specialized roles disagree.
Global/common rules remain canonical in `/AGENTS.md`.

## When This File Applies

Use this when two or more roles provide conflicting recommendations for the same decision.
Examples:
- delivery speed vs security hardening
- privacy/compliance constraints (for example GDPR/LGPD) vs observability depth
- architecture purity vs operational simplicity

Baseline prohibitions from `/AGENTS.md` remain in force (for example, no secrets in logs, no silent auth broadening) unless a human explicitly accepts a documented exception.

## Resolution Flow

### Round 1 (automatic)

- Prefer the option that keeps security and correctness intact.
- Minimize scope and blast radius.
- Record trade-offs, residual risk, and mitigations.

### Round 2+ (human required)

If conflict persists after round 1:
- stop automatic resolution
- escalate for explicit human arbitration
- present both options, impacts, and recommendation

## Documentation Requirements

Any conflict decision must include:
- conflict summary (what vs what)
- chosen direction
- rejected alternative and reason
- residual risk
- compensating controls

## Precedence vs `/AGENTS.md`

If anything in this file conflicts with `/AGENTS.md`, `/AGENTS.md` wins.
