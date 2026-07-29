"""The guard that keeps the failure-coverage number honest.

Named to sort last, because it reads what every other suite did. An earlier version
lived in test_bad_values_live.py, which pytest collects alphabetically -- so it ran
before the suites it measures and saw almost nothing. A coverage guard that cannot
see the coverage is worse than none, since it reports success.
"""

from __future__ import annotations

# Built-in
import sys

# Third-party
import pytest

# Internal
from failure_contract import NO_FAILURE_INPUT

pytestmark = pytest.mark.integration

sys.path.insert(0, "houdini/scripts/python")

import fxhoudinimcp_server.dispatcher as dispatcher  # noqa: E402


def test_every_command_is_either_failure_tested_or_declared():
    """No command may sit in neither list.

    A command with no failure test and no entry in NO_FAILURE_INPUT is an untested
    failure path that the coverage number presents as a complete one. That gap is
    how six false-success bugs shipped behind 188/188 command coverage.
    """
    from conftest import _CALL_MODES

    registered = set(dispatcher.list_commands())
    exercised = len([c for c in registered if _CALL_MODES[c]])
    if exercised < len(registered) * 0.9:
        pytest.skip(
            f"partial run ({exercised}/{len(registered)} commands exercised); "
            f"this guard needs the whole suite"
        )

    tested = {c for c in registered if _CALL_MODES[c] & {"raises", "reports"}}
    orphans = sorted(registered - tested - set(NO_FAILURE_INPUT))
    assert not orphans, (
        f"{len(orphans)} command(s) have no failure test and are not declared "
        f"failure-free. Either give each a bad-input test or add it to "
        f"NO_FAILURE_INPUT with a reason: {orphans}"
    )
