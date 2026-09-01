"""The capability vocabulary issue #73's authorization plane is built on.

#73 requires authorization to be "capability-oriented rather than assuming
blanket filesystem access", and requires the vocabulary to come from "existing
security contracts" rather than being invented alongside them. These tests pin
the two properties that make that true: capabilities are a VIEW of `TaskMode`
(so `allowed_modes` stays the single enforcement point), and no capability that
grants writing can ever be obtained by a node announcing a directory.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.protocol import (
    AUTO_AUTHORIZABLE_CAPABILITIES,
    CAPABILITY_MODES,
    Capability,
    DiscoveredState,
    DiscoveryRoot,
    TaskMode,
    capabilities_to_modes,
)


def test_every_task_mode_is_reachable_through_some_capability() -> None:
    """A mode no capability grants is a mode no authorization can ever permit.

    Written as a total check rather than five separate assertions because the
    failure it guards against is additive: someone adds a sixth `TaskMode` and
    the authorization plane silently cannot express it, which surfaces much
    later as "why can this project never run that".
    """
    granted = set().union(*CAPABILITY_MODES.values())
    assert granted == set(TaskMode)


def test_read_grants_no_mode_that_can_modify_a_file() -> None:
    """The load-bearing claim of the whole read-only tier.

    If `edit` or `implement` ever appears under `READ`, every "announced
    projects are read-only" guarantee in this codebase becomes false at once,
    on both the gateway and the executor, because both derive their check from
    this one mapping.
    """
    read_modes = capabilities_to_modes([Capability.READ])
    assert TaskMode.EDIT not in read_modes
    assert TaskMode.IMPLEMENT not in read_modes
    assert read_modes == frozenset({TaskMode.ANALYZE, TaskMode.REVIEW})


def test_deliver_grants_no_mode() -> None:
    """Delivery is not a mode, and must not become one by accident.

    Pushing is `SubmitTaskRequest.delivery`, gated by
    `PUSHABLE_BRANCH_PATTERN` and the approval scope. `Capability.DELIVER`
    exists so an authorization can WITHHOLD it -- if it started granting a
    mode, it would quietly widen what a task may do on top of that.
    """
    assert capabilities_to_modes([Capability.DELIVER]) == frozenset()


def test_an_unknown_capability_grants_nothing() -> None:
    """Forward compatibility must narrow, never widen.

    A newer gateway naming a capability an older executor has never heard of
    must leave the executor stricter, not crash its dispatch loop and not
    grant something it cannot reason about.
    """
    assert capabilities_to_modes(["telepathy"]) == frozenset()
    assert capabilities_to_modes(["read", "telepathy"]) == capabilities_to_modes(["read"])


def test_a_discovery_root_cannot_grant_write_capabilities() -> None:
    """#73: "A node cannot grant itself project authorization merely by

    reporting a discovery." The operator configures a root once and that is a
    real, auditable grant -- but only of the capabilities that cannot change a
    repository. `modify` and `deliver` require a per-project decision that
    names a person, so they are refused at the point the root is parsed,
    before any node has connected.
    """
    for capability in (Capability.MODIFY, Capability.DELIVER):
        with pytest.raises(ValidationError) as excinfo:
            DiscoveryRoot(path="/home/esteban/Sync/Projects/AI", auto_authorize=[capability])
        assert "explicit per-project grant" in str(excinfo.value)


def test_auto_authorizable_capabilities_never_reach_a_file() -> None:
    """Guards the constant itself, not just the validator that reads it.

    The validator would keep passing if someone widened
    `AUTO_AUTHORIZABLE_CAPABILITIES`; this is the assertion that notices.
    """
    assert not (capabilities_to_modes(AUTO_AUTHORIZABLE_CAPABILITIES) & {TaskMode.EDIT, TaskMode.IMPLEMENT})


def test_a_root_grants_nothing_unless_it_says_so() -> None:
    """Scanning a tree and authorizing it are different acts.

    The default must be the strict one: a root with no `auto_authorize`
    produces adoption candidates and no access at all.
    """
    assert DiscoveryRoot(path="/home/esteban/Sync/Projects").auto_authorize == []


def test_the_five_discovered_states_are_all_distinct_values() -> None:
    """#73: "Do not collapse these into a single `enabled` boolean."

    Pinned as a test because the pressure to collapse is real and arrives as a
    refactor: `denied` merged into `discovered` makes a refused candidate
    reappear in the adoption queue on every reconnect, and `stale` merged into
    absence loses a project's history when its directory moves.
    """
    assert len({state.value for state in DiscoveredState}) == 5
