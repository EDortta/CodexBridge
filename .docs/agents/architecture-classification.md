# Architecture Classification

Mandatory policy for classifying structural changes before implementation.
Global/common rules remain canonical in `/AGENTS.md`.

Use this file when a request changes architecture, boundaries, integration
contracts, runtime topology, persistence model, security posture, or ownership.

## 1. Classification Is Required

- [MANDATORY] A request that changes architecture is classified **before** code,
  migration, deploy, or release work starts.
- [MANDATORY] The classification artifact records:
  - summary of the requested change
  - classification label
  - why the label applies
  - affected domains/capabilities
  - compatibility expectation
  - required approvals
  - residual risk
- [MANDATORY] If the operator has not classified the change, the agent proposes a
  classification but does not silently treat the proposal as approval.

## 2. Minimum Labels

Projects may refine the taxonomy, but these labels are the floor:

- `additive`
  When the change introduces a new optional path, field, module, adapter, or
  capability while preserving existing behavior and deploy order.
- `behavioral-change`
  When observable behavior changes for existing callers or users, even if no
  schema changes.
- `contract-change`
  When an API, event, file format, CLI contract, or integration expectation is
  removed, renamed, narrowed, or reinterpreted.
- `migration`
  When data, persisted state, filesystem layout, or runtime ownership must move
  or be rewritten.
- `security-sensitive`
  When the change affects auth, secrets, approvals, exposure, logging of PII, or
  any other security/privacy control.

Multiple labels may apply. Omitting a relevant label is a review defect.

## 3. Approval Rules

- [MANDATORY] `additive` changes may proceed with normal issue approval unless a
  project-specific limit says otherwise.
- [MANDATORY] `behavioral-change`, `contract-change`, `migration`, and
  `security-sensitive` changes require explicit human review of impact and
  rollback/containment strategy before application.
- [MANDATORY] If deploy order is not safe in any order, that fact must appear in
  the classification.

## 4. Prohibitions

- [PROHIBITED] Reframing a migration as a "small refactor" to skip review.
- [PROHIBITED] Claiming `additive` when an old caller can break, drift, or be
  forced onto new semantics.
- [PROHIBITED] Executing a structural override merely because the operator said
  "faz" if the required approval bundle for the chosen label is still missing.

## 5. Deliverable

Every structural issue or implementation plan must make it obvious:

- what changed;
- which label(s) apply;
- whether the change is safe by deploy order;
- whether rollback exists;
- what approval is still needed.
