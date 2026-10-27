# Gateway Worker identity foundation (schema only)

This increment introduces Gateway-owned `worker_identities` and
`worker_requests` tables. It has **no API route, Worker registration,
credential issuing, branch polling integration, dispatch or deploy**.

Invariants:

- A Worker credential is distinct from an Executor credential and only its
  hash is stored. New identities start disabled. Revocation has a timestamp.
- Requests are unique on (`project_id`, `request_id`). A payload digest
  will let the admission handler reject reuse of an ID for different data.
- A persisted request is **not** a grant. Before dispatch the Gateway must
  authenticate the Worker, resolve a separately authenticated operator,
  verify active 8-hour project lease, GitHub project/repository binding,
  exact commit and target Node authorization. Neither a Git author nor
  possession of a Worker token alone proves operator consent.
- No arbitrary shell. Valid operations remain restricted to the catalog
  and separately checked against each Project/Node capability.

Follow-up implementation: provision and revoke Worker credentials through an
operator-gated workflow; durable centrally-authorized activation leases;
atomic idempotent admission; execution via existing Gateway→Executor routing;
result projection back through Worker. Migration `0020` must be reviewed and
applied only in the explicitly authorized deployment stage.
