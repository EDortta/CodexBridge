"""Database model invariants for the Worker transport ledger."""
from gateway.app.models.entities import WorkerIdentityModel, WorkerRequestModel


def test_worker_identity_is_disabled_by_default():
    column = WorkerIdentityModel.__table__.c.enabled
    assert column.default.arg is False
    assert WorkerIdentityModel.__tablename__ != "executors"
    assert WorkerIdentityModel.__table__.c.token_hash.unique


def test_request_id_scoped_to_project():
    pk = {column.name for column in WorkerRequestModel.__table__.primary_key.columns}
    assert pk == {"project_id", "request_id"}
    assert WorkerRequestModel.__table__.c.payload_sha256.type.length == 64
    assert WorkerRequestModel.__table__.c.source_commit.type.length == 40


def test_worker_is_not_an_executor():
    target = next(iter(WorkerRequestModel.__table__.c.worker_id.foreign_keys))
    assert target.target_fullname == "worker_identities.id"
