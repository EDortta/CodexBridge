# Delivery Loop

The chain from "start implementing" to "this is done": how the work runs, which gates it
passes, how its security impact is classified, and what `done` means.

`./session-close.md` covers *how to close the session*; this file covers *what must be
true about the work* before a session is worth closing.

Load this file when implementing, reviewing, or declaring a delivery ready.
If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

## 4. Execution Loop

For implementation work:
1. Restore active work context if one exists.
2. State issue understanding, scope, risks, impacted files, and contract notes.
3. Create/switch branch only after explicit human permission.
4. Implement the smallest durable safe fix.
5. Run impacted lint/typecheck/tests.
6. Review diff for scope, duplication, clarity, contracts, and secrets.
7. Close the session with handoff/resume updates.

Never start implementation on `main` or `master`.

---

## 5. Quality Gates

For impacted modules only, unless shared tooling/contracts changed:
- lint passes
- typecheck/compilation passes
- tests pass
- no exposed secrets

Tests are required for behavior, API, auth, persistence, shared-interface, or regression-prone changes.
Tests may be N/A only for docs/comments/metadata with no runtime effect; justify N/A explicitly.

A bug fix ships with a test that **fails without the fix** — if it passes on the
unfixed code, it is not testing the fix. Design rules that keep a change from
breaking the last one: `../agents/design-standards.md`.

When changing public contracts, report:
- backward compatible: yes/no
- contract changed: yes/no
- migration required: yes/no
- downstream consumers affected: yes/no

If no persistence change, report: `No model/migration changes`.

---

## 9. Security Decision

For every delivery, classify security impact as:
- `no security impact`
- `mitigated security impact`
- `known temporary risk requiring explicit human acceptance`

If not `no security impact`, document affected surface, abuse path, mitigation, and residual risk.

---

## 10. Done

Done means:
- scope respected
- root cause handled or limitation documented
- contracts preserved or declared changed
- impacted checks/tests executed or justified
- security impact classified
- session handoff/resume updated
- review-ready summary produced
