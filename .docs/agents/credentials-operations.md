# Credentials Operations

Operational policy for configuring providers and handling `.credentials` without
leaking secrets. Global/common rules remain canonical in `/AGENTS.md`.

Use this file when a project configures LLM providers, service credentials,
approval tokens, or any operator-supplied secret reference.

## 1. Storage Model

- [MANDATORY] Secrets live only in `.credentials/`, `.env`, or an explicit
  operator-local reference outside the repository.
- [MANDATORY] Shareable project configuration stores only a **reference** to a
  credential (`credential_ref`, env var name, local path hint), never the secret
  value.
- [MANDATORY] A provider entry declares whether it is `manual`, `env`,
  `file-ref`, or another explicit mode. Missing mode is a configuration defect.
- [MANDATORY] Configuration can be versioned only if replaying it does not expose
  the secret.

## 2. Provider Configuration

- [MANDATORY] Adding a provider records:
  - provider name
  - mode
  - expected credential reference
  - validation method, if any
  - whether the provider is optional, primary, or fallback
- [MANDATORY] A project remains operable in manual mode even when no provider is
  configured yet.
- [MANDATORY] Connectivity validation is opt-in and must never print the secret.
- [MANDATORY] Provider selection defaults are explicit per project or domain when
  multiple providers exist.

## 3. Read/Display Rules

- [PROHIBITED] Echoing credential contents in logs, diffs, previews, issue text,
  screenshots, or chat output.
- [PROHIBITED] Copying a secret from `.credentials` into a shareable state file,
  fixture, example, or test.
- [PROHIBITED] Treating a missing secret as permission to inject a dummy default
  in tracked files.

## 4. Approval and Rotation

- [MANDATORY] Any change that rotates, transmits, or invalidates credentials is a
  human-approved operational task, not an autonomous agent action.
- [MANDATORY] A detected leak or accidental tracking becomes an explicit operator
  follow-up item with containment and rotation called out.

## 5. Minimum Deliverable

Before a provider configuration is considered complete, the project can answer:

- where the provider is declared;
- how the secret is referenced without exposing it;
- how the provider is validated;
- what happens when the credential is absent or invalid;
- which operator step is still required, if any.
