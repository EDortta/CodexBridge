"""HTTP intake remains fail-closed even with a valid-looking request."""
from unittest.mock import AsyncMock, patch

import pytest

from gateway.app.api.routes.worker_intake import IntakeRequest, intake_request


def request():
    return IntakeRequest(
        repository="EDortta/CodexBridge", controlBranch="codexbridge-control",
        envelope={
            "schemaVersion": 1, "requestId": "req-001", "project": "codexbridge",
            "operation": "analyze",
            "source": {"branch": "development", "commit": "a" * 40},
            "targets": {"mode": "selected", "nodes": ["devel3"]},
            "parameters": {},
        },
    )


@pytest.mark.asyncio
async def test_no_worker_credential_is_denied():
    with patch("gateway.app.api.routes.worker_intake.authenticated_worker", return_value=None):
        with pytest.raises(Exception) as err:
            await intake_request(request(), x_worker_token=None, session=AsyncMock())
    assert err.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_envelope_rejected_before_lease_lookup():
    body = request()
    body.envelope["parameters"] = {"shell": "whoami"}
    with patch("gateway.app.api.routes.worker_intake.authenticated_worker",
               return_value=type("Worker", (), {"id": "worker1"})()):
        with pytest.raises(Exception) as err:
            await intake_request(body, x_worker_token="x" * 48, session=AsyncMock())
    assert err.value.status_code == 422
