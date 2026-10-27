"""Fail-closed Worker admission boundary tests."""
import pytest
from gateway.app.services.worker_admission import canonical_digest, record_admission, authenticated_worker, WorkerAdmissionError


def envelope():
    return {"project": "codexbridge", "requestId": "req-1",
            "source": {"commit": "a" * 40}, "operation": "analyze"}


def test_canonical_digest_order_independent():
    assert canonical_digest({"b": 1, "a": 2}) == canonical_digest({"a": 2, "b": 1})
    assert canonical_digest({"a": 2}) != canonical_digest({"a": 3})


@pytest.mark.asyncio
async def test_transport_identity_alone_cannot_admit():
    class Worker:
        id = "worker-1"

    with pytest.raises(WorkerAdmissionError, match="authorization required"):
        await record_admission(None, worker=Worker(), envelope=envelope())


@pytest.mark.asyncio
async def test_missing_credentials_do_not_query_database():
    assert await authenticated_worker(None, None) is None
    assert await authenticated_worker(None, "short") is None
