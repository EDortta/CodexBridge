"""issue #17 council round 1, "the second caller": `cancel_replay_max_age_seconds`
had no upper bound, so `CODEX_BRIDGE_CANCEL_REPLAY_MAX_AGE_SECONDS=99999999999`
parsed cleanly and only blew up later, inside `AgentHub.register()`, as an
`OverflowError` from `datetime.now(tz) - timedelta(seconds=...)` — after
`websocket.accept()` and after the connection was already recorded in
`hub.connections`, so the dead socket stayed "connected" forever and no
executor could ever finish registering.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.app.core.config import Settings
from shared.protocol import MAX_REPLAY_MAX_AGE_SECONDS


@pytest.mark.parametrize("field", ["cancel_replay_max_age_seconds", "control_replay_max_age_seconds"])
def test_a_replay_window_far_past_the_overflow_point_is_rejected_at_startup(field) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 99999999999})


@pytest.mark.parametrize("field", ["cancel_replay_max_age_seconds", "control_replay_max_age_seconds"])
def test_a_replay_window_at_the_documented_ceiling_is_accepted(field) -> None:
    settings = Settings(_env_file=None, **{field: MAX_REPLAY_MAX_AGE_SECONDS})
    assert getattr(settings, field) == MAX_REPLAY_MAX_AGE_SECONDS


@pytest.mark.parametrize("field", ["cancel_replay_max_age_seconds", "control_replay_max_age_seconds"])
def test_a_negative_replay_window_is_rejected(field) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: -1})
