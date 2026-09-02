"""Credential resolution for the `/agent/ws` handshake — issue #15.

The token used to be a required query parameter, so it landed verbatim in every
access log on the path. The header replaced it, and the compatibility window
that kept `?token=...` alive for one release has closed: these tests pin what
resolution accepts now that the header is the only route in.
"""

from __future__ import annotations

import pytest

from gateway.app.core.agent_auth import resolve_executor_token


def test_the_header_is_the_credential() -> None:
    assert resolve_executor_token(header_token="t0ken") == "t0ken"


def test_surrounding_whitespace_is_not_part_of_the_credential() -> None:
    assert resolve_executor_token(header_token="  t0ken  ") == "t0ken"


def test_nothing_presented_is_absent() -> None:
    assert resolve_executor_token(header_token=None) is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_do_not_count_as_a_credential(blank: str) -> None:
    """A blank `X-Executor-Token:` is not a presented credential.

    Treating it as one hands `secure_compare` an empty string to check against
    the registry — a comparison that exists only to be rejected, and that a
    registry entry with an empty `machine_token` would accept.
    """
    assert resolve_executor_token(header_token=blank) is None
