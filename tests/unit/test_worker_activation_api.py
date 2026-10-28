"""Operator Worker activation must require a real admin and bound project."""
from unittest.mock import AsyncMock
import pytest

from gateway.app.api.routes.worker_activations import (
    ActivateWorkerProject, activate, _REPO, _BRANCH,
)


def test_reject_untrusted_repository_values():
    assert _REPO.fullmatch("EDortta/CodexBridge")
    assert not _REPO.fullmatch("https://github.com/EDortta/CodexBridge")
    assert not _REPO.fullmatch("../bad")
    assert _BRANCH.fullmatch("codexbridge-control")


@pytest.mark.asyncio
async def test_scope_only_cannot_activate_worker():
    principal = type("Principal", (), {"roles": ["viewer"], "user_id": "viewer"})()
    with pytest.raises(Exception) as raised:
        await activate("worker", ActivateWorkerProject(
            projectId="codexbridge", repository="EDortta/CodexBridge"
        ), principal=principal, session=AsyncMock())
    assert raised.value.status_code == 403
