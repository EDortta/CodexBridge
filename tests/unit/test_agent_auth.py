"""Credential resolution for the `/agent/ws` handshake — issue #15.

The token used to be a required query parameter, so it landed verbatim in every
access log on the path. These tests pin the resolution rules that let the header
replace it without breaking a fleet that is mid-upgrade.
"""

from __future__ import annotations

import pytest

from gateway.app.core.agent_auth import TokenSource, resolve_executor_token


def test_header_is_the_new_path() -> None:
    presented, source = resolve_executor_token(header_token="t0ken", query_token=None)
    assert presented == "t0ken"
    assert source is TokenSource.HEADER


def test_query_still_authenticates_during_the_transition() -> None:
    """Gateway and agent deploy independently, so the old form must keep working."""
    presented, source = resolve_executor_token(header_token=None, query_token="t0ken")
    assert presented == "t0ken"
    assert source is TokenSource.QUERY


def test_header_wins_when_both_are_present() -> None:
    """An agent already on the header must not be downgraded by a stale query.

    A proxy that rewrites the URL, or a leftover parameter in an old unit file,
    would otherwise decide which credential authenticates — and would keep the
    deprecation warning firing for an agent that was already fixed.
    """
    presented, source = resolve_executor_token(header_token="new", query_token="old")
    assert presented == "new"
    assert source is TokenSource.HEADER


def test_nothing_presented_is_absent_not_empty_string() -> None:
    presented, source = resolve_executor_token(header_token=None, query_token=None)
    assert presented is None
    assert source is TokenSource.ABSENT


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_do_not_count_as_a_credential(blank: str) -> None:
    """`?token=` is not a presented credential.

    Treating it as one hands `secure_compare` an empty string to check against
    the registry — a comparison that exists only to be rejected, and that a
    registry entry with an empty `machine_token` would accept.
    """
    presented, source = resolve_executor_token(header_token=blank, query_token=blank)
    assert presented is None
    assert source is TokenSource.ABSENT


def test_a_blank_header_falls_through_to_the_query() -> None:
    """Proxies that inject empty headers must not break the transition path."""
    presented, source = resolve_executor_token(header_token="", query_token="t0ken")
    assert presented == "t0ken"
    assert source is TokenSource.QUERY
