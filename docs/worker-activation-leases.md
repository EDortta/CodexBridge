# Worker activation leases

Migration `0021` and the ORM model establish Gateway-owned leases. The pure `lease_is_active` checker fails closed on missing identity/repository/branch binding, revocation, time rewind, expiry and any duration other than eight hours.

**Not operational:** no issuance/revocation HTTP route, credential provisioning, central fleet-wide three-project admission transaction, Worker polling integration or dispatch is included. The database schema by itself does not enforce the project cap. A future operator-authorized endpoint must atomically enforce it, and the admission route must check a live lease on every new request. Do not infer authorization from a locally enabled `workerctl` project or from a GitHub commit. Applying the migration or deploying services requires separate approval.
