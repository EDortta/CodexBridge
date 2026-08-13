# Privacy and Compliance Guide (GDPR/LGPD)

Privacy/compliance guidance for any agent handling personal data.
Global/common rules remain canonical in `/AGENTS.md`.

## Scope

Apply this guide when changes involve:
- personal data collection, storage, transfer, or deletion
- user identity, profile, contact, behavioral, or sensitive data
- logs/telemetry that may contain personal data
- exports, reports, analytics, and integrations with third parties

## Core Principles

- Data minimization: collect/process only what is necessary.
- Purpose limitation: use data only for declared purposes.
- Storage limitation: define retention windows and deletion/anonymization strategy.
- Transparency: ensure user-facing disclosures remain accurate.
- Access control: least privilege for personal data access.

## Required Privacy Review

Evaluate at minimum:
- lawful basis or legal justification exists and is documented
- data categories involved and sensitivity level
- retention/deletion behavior and evidence path
- subject-right impact (access, rectification, deletion, portability, objection)
- third-party/subprocessor impact
- cross-border transfer risk (if applicable)

## Mandatory Output Expectations

If a change touches personal data, include:
- privacy impact: low/medium/high
- data categories affected
- retention/deletion impact
- user-rights impact
- residual compliance risk and mitigation

## Prohibitions

- Never introduce personal data collection without explicit purpose.
- Never keep personal data indefinitely by default.
- Never expose personal data in logs/errors/debug outputs.
- Never broaden data sharing with third parties without explicit approval.

## Conflict Handling

When privacy/compliance constraints conflict with security or delivery constraints, use `./governance-precedence.md`.

## Canonical References

Use `/AGENTS.md` as source of truth, especially:
- `## 3. Hard Rules` and `## 3b. Untrusted Content and External Actions`
- `../workflows/delivery-loop.md` `## 5. Quality Gates` and `## 9. Security Decision`
  (they left `/AGENTS.md` when the contract was sliced; the section numbers did not change)

If this file conflicts with `AGENTS.md`, follow `AGENTS.md`.
