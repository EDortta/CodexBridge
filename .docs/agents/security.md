# Security Guide

Security-specific guidance for any agent working in this repository.
Global/common rules remain canonical in `/AGENTS.md`.

## Scope

Use this guide for runtime-impacting changes, issue implementation, and PR review.

This guide covers *how to review*. The concrete, verifiable rules the delivered
code must satisfy (secrets, network exposure, CORS, supply chain, agent
commit-only, …) live in `./security-standards.md` — read it alongside this file.

## Mandatory Security Review

Evaluate at minimum:
- input validation
- injection risks
- authorization
- authentication
- data exposure
- logs and error handling
- business logic abuse
- privilege escalation
- tenant/isolation boundaries (if applicable)

## Security Decision Classification

Every delivery must be classified as one of:
- `no security impact`
- `mitigated security impact`
- `known temporary risk requiring explicit human acceptance`

If not `no security impact`, document:
- affected surface
- abuse path
- mitigation
- residual risk

## Security Prohibitions

- Never log secrets/tokens/credentials/sensitive raw payloads.
- Never weaken validation without explicit requirement.
- Never broaden authorization silently.
- Never hide failures with broad catch-all handling without justification.
- Never approve high-risk changes without mitigation and tests.

## Required Output Expectations

Security analysis should be explicit in implementation/review outputs:
- risk level
- exploitation path
- mitigation
- residual risk or acceptance requirement

## Compliance and Policy Tensions

When a security recommendation conflicts with legal/compliance policy or product governance constraints, use `./governance-precedence.md`:
- document the conflict explicitly
- document residual risk and compatible mitigations
- require explicit human arbitration when conflict remains unresolved

When personal data handling is involved, apply `./privacy-compliance.md` alongside this guide.

## Canonical References

Use `/AGENTS.md` as source of truth, especially:
- `## 3. Hard Rules` and `## 3b. Untrusted Content and External Actions`
- `../workflows/delivery-loop.md` `## 5. Quality Gates` and `## 9. Security Decision`
  (they left `/AGENTS.md` when the contract was sliced; the section numbers did not change)

If this file conflicts with `AGENTS.md`, follow `AGENTS.md`.
