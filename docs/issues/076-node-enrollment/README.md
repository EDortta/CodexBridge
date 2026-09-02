# Epic #76 — Node lifecycle: enrollment, credentials and revocation

Filed 2026-09-01. Nothing implemented yet: the four questions at the end of
`epic.md` are still open and answering them changes Stage 3.

Scope decision (2026-09-01, with the operator): a **narrow** epic covering only
whether a node is admitted to the fleet. Discovery, adoption and capability
authorization stay with #73, whose Stages 3 and 4 already own them. The
boundary: *#73 decides what an admitted node may do; this epic decides whether
it is admitted at all.*

Written after surveying every open and closed issue for prior art. What that
survey found:

- **Nothing anywhere covers enrollment.** No issue proposes token issuance,
  rotation, an invite flow, revocation, or adding an executor without a gateway
  restart. This epic exists because that gap is real, not assumed.
- #15 (closed, shipped) settled how the token *travels* on the handshake, not
  where it comes from.
- #55 names the need for a secrets/credential-broker model but specifies no
  mechanism; its executor-identity half belongs here.
- #45 (bootstrap new repositories) is adjacent but is about repositories, not
  machines.

## Bookkeeping found during the same survey, unrelated to this epic

- **#65 is OPEN but already implemented** — `store.resolve_project_reference`
  and the `start_development_task` MCP tool are both in the code. Candidate for
  closing.
- **#15 has an unfinished step.** It required removing the deprecated
  `?token=...` query form "in the release after" the header path shipped;
  `docs/protocol.md` still documents that form as accepted.
