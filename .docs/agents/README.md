# Agent Role Specs

Core role contracts:
- [programmer-agent](./programmer.md)
- [reviewer-agent](./reviewer.md)
- [issue-automation-agent](./issue-automation.md)
- [security guide](./security.md)
- [privacy-compliance guide (GDPR/LGPD)](./privacy-compliance.md)

Standards — what must be true in the delivered code (read alongside the role
contracts, not instead of them):
- [design standards](./design-standards.md) — seams, invariant placement, additive
  contracts, fail direction; why SOLID alone does not stop regressions
- [security standards](./security-standards.md)
- [domains and capabilities](./domains-and-capabilities.md) — model the governed
  project before structural work
- [architecture classification](./architecture-classification.md) — classify
  structural changes before implementation
- [credentials operations](./credentials-operations.md) — configure providers
  without exposing secrets

Shared references:
- [shared references](./_shared.md)
- [governance: role precedence for conflict rounds](./governance-precedence.md) —
  when roles **disagree**: precedence, then human arbitration
- [council: adversarial review of approved work](./council.md) — when **nobody**
  disagrees and the artifact is wrong anyway: findings, never decisions.
  Runs at the **delivery commit** (`../workflows/git-delivery.md` §7), gated by
  `governancekit council`

Common/global rules remain canonical in `/AGENTS.md`.
