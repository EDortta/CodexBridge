# Worker → Gateway integration gate

This increment introduces `scripts/worker_request.py`, a **pure structural
validator** for an untrusted GitHub control-branch request. It accepts only
the versioned envelope defined by the approved control-branch contract:
`analyze`, `test`, `verify` and `build` as transport vocabulary, an exact
activated Project ID, immutable 40-digit SHA, and bounded Node selection.

**No executable dispatch exists in this increment.** The existing
`scripts/worker_watch.py` remains read-only. In particular a valid envelope
is **not** authorization; there is no command or shell parameter, no Gateway
credential, and no implicit approval. The Gateway must independently
authenticate the Worker and the operator, validate activation freshness,
project/repository binding, fixed SHA, permitted operation, Node capability,
workspace binding, and idempotent request identity before dispatch.

Next implementation gate: a dedicated authenticated Gateway admission endpoint,
durable request ID deduplication scoped by Project, and Worker-to-Gateway
transport, followed by result projection to the control branch. No host service
installation, Gateway restart, merge or deploy is performed by this PR.
