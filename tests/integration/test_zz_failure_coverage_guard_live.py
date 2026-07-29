"""The guard that keeps the failure-coverage number honest.

Named to sort last, because it reads what every other suite did. An earlier version
lived in test_bad_values_live.py, which pytest collects alphabetically -- so it ran
before the suites it measures and saw almost nothing. A coverage guard that cannot
see the coverage is worse than none, since it reports success.
"""

from __future__ import annotations

# Built-in
import inspect
import itertools
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


# Values chosen to be wrong in as many ways as possible: empty, unknown, a path that
# cannot resolve, out-of-range numbers, wrong types, and a traversal attempt.
NASTY = (
    "",
    "notavalue",
    "/obj/definitely_not_a_node_12345",
    -1,
    0,
    10**12,
    float("nan"),
    None,
    [],
    {},
    True,
    "../../etc/passwd",
    "*",
    "[",
)

# Combinations to skip because the call would have a side effect on disk rather than
# tell us anything: saving the current scene writes untitled.hip.
_SKIP = {("scene.new_scene", "save_current")}


def test_declared_failure_free_really_cannot_fail(call):
    """Attack every command claimed unbreakable, on every argument, with every value.

    This is the part that was missing when the list was written from reasoning: it
    had convinced its author once, so re-reading it proved nothing. Probing it found
    8 of 26 entries wrong on semantic values and 6 more on types.

    Now the claim is checked on every run. A command that starts rejecting something
    fails here, and the fix is to move it out of NO_FAILURE_INPUT and give it a real
    failure test -- not to widen this test's tolerance.
    """
    broke: dict[str, list[str]] = {}
    for command in sorted(NO_FAILURE_INPUT):
        handler = dispatcher._handler_registry[command]
        arguments = [
            name
            for name, parameter in inspect.signature(handler).parameters.items()
            if parameter.kind not in (parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL)
        ]
        for argument, value in itertools.product(arguments, NASTY):
            if (command, argument) in _SKIP:
                continue
            result = dispatcher.dispatch(command, {argument: value})
            if result["status"] == "error":
                broke.setdefault(command, []).append(
                    f"{argument}={value!r} -> {result['error']['message'][:80]}"
                )
                continue
            data = result.get("data") or {}
            if isinstance(data, dict) and data.get("success") is False:
                broke.setdefault(command, []).append(
                    f"{argument}={value!r} -> reported success: False"
                )

    detail = "; ".join(f"{command}: {cases[:3]}" for command, cases in sorted(broke.items()))
    assert not broke, (
        f"These commands are declared failure-free but can be made to fail. Move each "
        f"out of NO_FAILURE_INPUT and give it a real failure test -- {detail}"
    )
