"""Admin boundary and request schema for independent preauthorization."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from gateway.app.api.routes.worker_execution_grants import (
    ExecutionGrantRequest, _human_admin, authorize_worker_execution,
)


def test_request_rejects_arbitrary_fields():
    with pytest.raises(ValidationError):
        ExecutionGrantRequest(workerId="w1", projectId="p", nodeId="n",
                              repository="owner/repo", modes=["test"],
                              executeShell="echo hello")


def test_request_rejects_unsupported_task_mode():
    with pytest.raises(ValidationError):
        ExecutionGrantRequest(workerId="w1", projectId="p", nodeId="n",
                              repository="owner/repo", modes=["build"])


def test_human_admin_required():
    with pytest.raises(Exception) as error:
        _human_admin(type("Principal", (), {"roles": ["viewer"]})())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_denial_precedes_any_db_lookup():
    payload = ExecutionGrantRequest(workerId="w1", projectId="p",
                                    nodeId="n", repository="owner/repo",
                                    modes=["test"])
    db = AsyncMock()
    with pytest.raises(Exception) as error:
        await authorize_worker_execution(
            payload,
            principal=type("Principal", (), {"roles": ["viewer"], "user_id": "u"})(),
            session=db)
    assert error.value.status_code == 403
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_modes_rejected_before_db_lookup():
    payload = ExecutionGrantRequest(workerId="w1", projectId="p",
                                    nodeId="n", repository="owner/repo",
                                    modes=["test", "test"])
    db = AsyncMock()
    with pytest.raises(Exception) as error:
        await authorize_worker_execution(
            payload,
            principal=type("Principal", (), {"roles": ["admin"], "user_id": "u"})(),
            session=db)
    assert error.value.status_code == 422
    db.get.assert_not_awaited()
