# Worker Gateway admission service (not yet deployed)

`gateway/app/services/worker_admission.py` checks a separately provisioned,
enabled and non-revoked Worker credential against its stored hash. It defines
atomic project-scoped request deduplication using the database composite key
and rejects reuse of a request ID for changed content.

**Fail closed:** `record_admission` defaults to `project_allowed=False`.
The caller must obtain an independent Gateway-side project and time-limited
lease authorization before passing True. The current increment has **no
endpoint**, provisioning workflow, approved lease source or dispatch, and
therefore cannot admit real requests. No inference of trust from GitHub authors,
repository access, token possession or local Worker activation is permitted.

A following PR must define operator-approved centrally tracked activation
leases and project/repository bindings, supply the HTTP endpoint and explicit
authorization result, add real DB concurrency tests, and only then wire
read/validate → admission. Admission is not execution; the existing Gateway
Node/project authorization applies again before dispatch.
