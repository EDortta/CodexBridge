# Domains and Capabilities

Normative policy for modeling a governed project before implementation begins.
Global/common rules remain canonical in `/AGENTS.md`.

Use this file when a project is being adopted, initialized, or materially
reorganized, or when a change request introduces a new area of responsibility.

## 1. Purpose

- A **domain** is a stable business or technical area that owns a slice of the
  system's behavior, vocabulary, and invariants.
- A **capability** is an executable responsibility delivered inside a domain.
- Domains exist to stop "misc" architectures. Capabilities exist to stop vague
  promises such as "improve the backend" from becoming unreviewable work.

## 2. Mandatory Rules

- [MANDATORY] Before implementing structural work, record the project's active
  domains and capabilities in a shareable artifact.
- [MANDATORY] Every capability belongs to exactly one primary domain.
- [MANDATORY] A domain name is stable, singular in meaning, and based on the
  project's own vocabulary. Prefer `billing`, `catalog`, `identity`,
  `messaging`; avoid `misc`, `general`, `helpers`, `core` unless the project
  already uses that term as a real bounded context.
- [MANDATORY] A capability name states observable responsibility, not a team or
  technology choice. Prefer `invoice-generation`, `lead-routing`,
  `receipt-reconciliation`; avoid `python-stuff`, `new-module`, `feature-x`.
- [MANDATORY] A capability that crosses domains declares the primary domain and
  names its dependent domains explicitly.
- [MANDATORY] A new domain or capability is additive first. Reusing an existing
  name for a new meaning is a contract change and must be classified as such.
- [MANDATORY] A capability that handles secrets, approvals, money, or personal
  data must say so in its metadata or issue context before implementation.

## 3. Review Heuristics

- [DEFAULT] Prefer the smallest domain set that keeps invariants local.
- [DEFAULT] Prefer capabilities that can be validated independently.
- [DEFAULT] Split a capability when its success criteria or failure modes differ
  materially from the rest of the domain.

## 4. Prohibitions

- [PROHIBITED] Starting a structural implementation with no declared domain.
- [PROHIBITED] Dumping unrelated behaviors into a catch-all domain to "decide
  later".
- [PROHIBITED] Using capability names that merely repeat an issue number, branch
  name, or internal nickname.
- [PROHIBITED] Treating infrastructure mechanics (`docker`, `redis`, `postgres`)
  as business domains unless the project truly exposes them as operator-facing
  governed areas.

## 5. Minimum Artifact

Before structural implementation, the project must be able to answer:

- which domains currently exist;
- which capabilities are active in each domain;
- which domain owns each new request;
- whether the request introduces a new domain/capability or changes an existing
  one.

The storage format may vary by project/runtime, but the answers above must be
shareable, reviewable, and versioned.
