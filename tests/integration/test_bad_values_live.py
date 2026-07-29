"""Arguments that are not paths, but can still be wrong.

These are the commands the self-discovering path suite cannot reach, because what
they take is a frame range, an expression, a context name or a take. Each has an
obvious way to be wrong, and each one is asserted here.

Also declares, explicitly, the commands that have no wrong input at all -- and
asserts that claim is still true, so the list cannot become a way of excusing a
command from testing forever.
"""

from __future__ import annotations

# Built-in
import inspect
import sys

# Third-party
import pytest

# Internal
from failure_contract import (
    GONE,
    HARMLESS_ARGUMENTS,
    NO_FAILURE_INPUT,
    assert_useful,
    message_of,
)

pytestmark = pytest.mark.integration

sys.path.insert(0, "houdini/scripts/python")

import fxhoudinimcp_server.dispatcher as dispatcher  # noqa: E402


class TestBadValuesAreRejected:
    def test_frame_range_backwards_is_rejected(self, call):
        for command in ("animation.set_frame_range", "animation.set_playback_range"):
            answer = call(command, assert_failure=True, start=50.0, end=10.0)
            assert_useful(
                command,
                message_of(answer),
                ("range", "start", "end", "greater", "before", "after", "invalid"),
            )

    def test_a_broken_expression_is_reported(self, call):
        answer = call(
            "code.evaluate_expression",
            assert_failure=True,
            expression="ch(/obj/nope/tx",
        )
        assert_useful(
            "code.evaluate_expression",
            message_of(answer),
            ("expression", "syntax", "parse", "invalid", "error", "unmatched", "failed"),
        )

    def test_python_that_raises_is_reported_not_swallowed(self, call):
        answer = call(
            "code.execute_python",
            assert_failure=True,
            code="raise RuntimeError('deliberate test failure')",
        )
        assert "deliberate test failure" in message_of(answer) + str(answer), (
            f"execute_python hid the exception the code raised: {answer}"
        )

    def test_an_unknown_context_is_rejected(self, call):
        for command in ("scene.get_context_info", "nodes.list_node_types"):
            answer = call(command, assert_failure=True, context="/notacontext")
            assert_useful(
                command,
                message_of(answer),
                ("context", "not found", "unknown", "invalid", "must be", "one of"),
            )

    def test_switching_to_a_take_that_does_not_exist_is_rejected(self, call):
        answer = call("takes.set_current_take", assert_failure=True, name="no_such_take_xyz")
        message = message_of(answer)
        assert_useful(
            "takes.set_current_take",
            message,
            ("take", "not found", "does not exist", "unknown"),
        )
        assert "no_such_take_xyz" in message, message

    def test_loading_a_missing_scene_names_the_file(self, call):
        answer = call(
            "scene.load_scene",
            assert_failure=True,
            file_path="Q:/nonexistent-drive/nope.hip",
        )
        message = message_of(answer)
        assert_useful("scene.load_scene", message, ("not found", "does not exist", "no such"))
        assert "nope.hip" in message, message

    def test_saving_to_an_impossible_path_is_reported(self, call):
        answer = call(
            "scene.save_scene",
            assert_failure=True,
            file_path="Q:/nonexistent-drive/fxh/nope.hip",
        )
        assert_useful(
            "scene.save_scene",
            message_of(answer),
            (
                "save",
                "not found",
                "no such",
                "cannot",
                "could not",
                "creating",
                "permission",
                "invalid",
            ),
        )

    def test_batch_connect_reports_which_pair_failed(self, call):
        answer = call(
            "nodes.connect_nodes_batch",
            assert_failure=True,
            connections=[{"source_path": GONE, "dest_path": "/obj", "input_index": 0}],
        )
        assert GONE in message_of(answer) + str(answer), (
            f"connect_nodes_batch did not say which connection failed: {answer}"
        )

    def test_selecting_nodes_that_do_not_exist_is_reported(self, call):
        answer = call("context.set_selection", assert_failure=True, node_paths=[GONE])
        assert GONE in message_of(answer) + str(answer), (
            f"set_selection did not name the path it could not find: {answer}"
        )

    def test_hscript_nonsense_is_surfaced(self, call):
        # hscript reports unknown commands on its output rather than by failing, so
        # the requirement is that the output reaches the caller, not that it errors.
        result = call("code.execute_hscript", allow_error=True, command="notacommand_xyz")
        flat = str(result).lower()
        assert "notacommand_xyz" in flat or "unknown" in flat or "error" in flat, (
            f"execute_hscript swallowed an unknown command entirely: {result}"
        )


def test_the_no_failure_input_list_is_still_true():
    """Each command claimed to have no bad input must still take none.

    Without this the list becomes a permanent exemption. A command that grows a
    required argument can be given a wrong one, and this fails until someone
    writes that test.
    """
    grown: dict[str, list[str]] = {}
    for command in NO_FAILURE_INPUT:
        handler = dispatcher._handler_registry.get(command)
        assert handler is not None, f"{command} is no longer registered; remove it from the list"
        signature = inspect.signature(handler)
        required = [
            name
            for name, param in signature.parameters.items()
            if param.default is param.empty
            and param.kind not in (param.VAR_KEYWORD, param.VAR_POSITIONAL)
            and name not in HARMLESS_ARGUMENTS.get(command, set())
        ]
        if required:
            grown[command] = required
    assert not grown, (
        f"These commands gained required arguments and can now be given wrong ones, "
        f"so each needs a failure test: {grown}"
    )
