"""Every command must fail usefully, not merely fail.

The session summary reports failure-path coverage next to command coverage, and
the gap between them was the whole problem: 188/188 commands were dispatched while
only 16 were ever made to go wrong. Six real bugs shipped in that gap, all of them
tools reporting success for work that never happened.

A caller cannot recover from a failure it cannot read. These are the three ways a
handler wastes a round trip:

* leaking a Python internal -- ``'NoneType' object has no attribute 'path'`` says
  a node lookup returned None, but not which node, nor that a path was wrong;
* leaking a missing-UI AttributeError -- ``module 'hou' has no attribute 'ui'``
  reads like the plugin is broken, when the real answer is "this needs a
  graphical Houdini";
* an empty message, which is worse than a crash because it looks handled.

So each case below feeds a command something wrong and asserts the answer names
the problem. The table is deliberately dumb and exhaustive: adding a command
without a failure case here is what let the last six through.
"""

from __future__ import annotations

# Built-in
import re

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration

# A path that cannot resolve, used wherever a handler takes a node path.
GONE = "/obj/definitely_not_a_node_12345"

# (command, params, expected substrings -- any one of them is enough)
#
# The expectation is intentionally loose: the point is not the exact wording but
# that the message names the thing that was wrong. Where a handler needs a UI, the
# expectation is that it says so.
NODE_LOOKUP_CASES: list[tuple[str, dict]] = [
    ("cache.clear_cache", {"node_path": GONE}),
    ("cache.get_cache_status", {"node_path": GONE}),
    ("cache.write_cache", {"node_path": GONE}),
    ("cops.get_cop_geometry", {"node_path": GONE}),
    ("cops.get_cop_info", {"node_path": GONE}),
    ("cops.get_cop_layer", {"node_path": GONE}),
    ("cops.get_cop_vdb", {"node_path": GONE}),
    ("cops.set_cop_flags", {"node_path": GONE, "display": True}),
    ("cops.create_cop_node", {"parent_path": GONE, "cop_type": "null"}),
    (
        "chops.export_chop_to_parm",
        {
            "chop_path": GONE,
            "channel_name": "chan1",
            "target_node_path": "/obj",
            "target_parm_name": "tx",
        },
    ),
    (
        "dops.get_dop_field",
        {
            "node_path": GONE,
            "object_name": "o",
            "data_path": "d",
            "field_name": "density",
        },
    ),
    ("dops.get_dop_object", {"node_path": GONE, "object_name": "o"}),
    ("hda.get_hda_section_content", {"node_path": GONE, "section_name": "PythonModule"}),
    ("hda.set_hda_section_content", {"node_path": GONE, "section_name": "s", "content": "x"}),
    ("hda.update_hda", {"node_path": GONE}),
    ("lops.inspect_usd_layer", {"node_path": GONE}),
    ("rendering.get_render_progress", {"node_path": GONE}),
    ("rendering.set_render_settings", {"node_path": GONE, "settings": {"trange": 1}}),
    ("tops.cancel_top_cook", {"node_path": GONE}),
    ("tops.get_pdg_graph", {"node_path": GONE}),
    ("tops.get_top_network_info", {"node_path": GONE}),
    ("tops.get_top_scheduler_info", {"node_path": GONE}),
    ("tops.get_work_item_info", {"node_path": GONE, "work_item_index": 0}),
    ("tops.pause_top_cook", {"node_path": GONE}),
    ("vex.create_vex_expression", {"node_path": GONE, "parm_name": "tx", "vex_code": "1;"}),
    ("viewport.find_error_nodes", {"root_path": GONE}),
    ("scene.export_file", {"node_path": GONE, "file_path": "/tmp/x.bgeo.sc"}),
]

# Handlers that need a graphical Houdini. In hython they must say so.
NEEDS_UI_CASES: list[tuple[str, dict]] = [
    ("rendering.render_viewport", {"output_path": "/tmp/vp.png"}),
    ("rendering.render_quad_view", {"output_path": "/tmp/quad.png"}),
    ("rendering.render_node_network", {"node_path": "/obj", "output_path": "/tmp/net.png"}),
    ("viewport.frame_all", {}),
    ("viewport.frame_selection", {}),
    ("viewport.get_viewport_info", {}),
    ("viewport.list_panes", {}),
    ("viewport.set_current_network", {"network_path": "/obj"}),
    ("viewport.set_viewport_camera", {"camera_path": "/obj/cam1"}),
    ("viewport.set_viewport_direction", {"direction": "perspective"}),
    ("viewport.set_viewport_display", {"display_mode": "smooth"}),
    ("viewport.set_viewport_renderer", {"renderer": "Houdini GL"}),
]

# Leaks that mean the handler never looked at what it was given.
_INTERNAL_LEAKS = (
    "nonetype",
    "has no attribute",
    "unhashable",
    "not subscriptable",
    "unexpected keyword argument",
    "positional argument",
    "traceback",
    # Houdini's generic OperationFailed text. Technically a message, but it names
    # nothing and leaves the caller with no next step, so a handler that lets it
    # through unwrapped has not explained anything.
    "the attempted operation failed",
)


def _assert_useful(command: str, message: str, must_mention: tuple[str, ...]) -> None:
    assert message.strip(), f"{command} failed with an empty message"
    low = message.lower()
    for leak in _INTERNAL_LEAKS:
        assert leak not in low, (
            f"{command} leaked a Python internal instead of explaining itself: {message!r}"
        )
    assert any(hint in low for hint in must_mention), (
        f"{command} did not say what was wrong. Expected one of {must_mention}, got: {message!r}"
    )


class TestBadNodePathsAreNamed:
    """A handler given a path that does not resolve must say so, and say which.

    Most of these had no node lookup at all: they called hou.node(path) and used
    the result, so the caller got 'NoneType' object has no attribute ... and no
    indication that the path was the problem.
    """

    @pytest.mark.parametrize(
        ("command", "params"),
        NODE_LOOKUP_CASES,
        ids=[case[0] for case in NODE_LOOKUP_CASES],
    )
    def test_missing_node_is_reported_clearly(self, call, command, params):
        # assert_failure accepts either route -- raising, or returning
        # success: False -- but not success. A table of bad inputs should not have
        # to know which convention each handler picked.
        answer = call(command, assert_failure=True, **params)
        message = str(answer.get("message", ""))
        _assert_useful(
            command,
            message,
            ("not found", "does not exist", "no node", "invalid", "could not", "nothing"),
        )
        # Naming the offending path is what turns a retry into a fix.
        assert GONE in message or "definitely_not_a_node" in message, (
            f"{command} did not name the path it could not find: {message!r}"
        )


class TestUiOnlyCommandsSayTheyNeedAUi:
    """In hython these cannot work. The message has to be the reason, not the crash.

    'module 'hou' has no attribute 'ui'' reads as a broken plugin and sends the
    caller debugging the server. What they need to know is that the operation
    requires a graphical Houdini -- and, where one exists, that a viewer must be
    open.
    """

    @pytest.mark.parametrize(
        ("command", "params"),
        NEEDS_UI_CASES,
        ids=[case[0] for case in NEEDS_UI_CASES],
    )
    def test_no_ui_is_explained(self, call, command, params):
        if hou.isUIAvailable():
            pytest.skip("graphical session: these succeed, see gui_session_check.py")
        error = call(command, expect_error=True, **params)
        message = str(error.get("message", ""))
        assert message.strip(), f"{command} failed with an empty message"
        low = message.lower()
        assert "has no attribute" not in low, (
            f"{command} leaked the missing hou.ui instead of explaining: {message!r}"
        )
        assert re.search(r"graphical|no ui|without a ui|headless|viewer|pane", low), (
            f"{command} did not explain that it needs a graphical Houdini: {message!r}"
        )


class TestWrongNodeTypeIsNamed:
    """Pointing a specialised tool at an ordinary node must explain the mismatch."""

    def test_cop_tools_reject_a_sop(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="notacop")
        box = call("nodes.create_node", parent_path=geo["node_path"], node_type="box")
        for command in ("cops.get_cop_info", "cops.get_cop_geometry", "cops.get_cop_layer"):
            answer = call(command, assert_failure=True, node_path=box["node_path"])
            _assert_useful(
                command,
                str(answer.get("message", "")),
                ("cop", "image", "not a", "unsupported", "no layer", "failed"),
            )

    def test_top_tools_reject_a_sop(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="notatop")
        box = call("nodes.create_node", parent_path=geo["node_path"], node_type="box")
        for command in ("tops.get_top_network_info", "tops.get_pdg_graph"):
            answer = call(command, assert_failure=True, node_path=box["node_path"])
            _assert_useful(
                command,
                str(answer.get("message", "")),
                ("top", "pdg", "not a", "no work", "unsupported"),
            )


class TestHdaFilePathsAreValidated:
    def test_installing_a_missing_file_names_it(self, call):
        error = call("hda.install_hda", expect_error=True, file_path="Q:/nope/missing.hda")
        message = str(error.get("message", ""))
        _assert_useful("hda.install_hda", message, ("not found", "does not exist", "no such"))
        assert "missing.hda" in message, message

    def test_reloading_a_missing_file_names_it(self, call):
        error = call("hda.reload_hda", expect_error=True, file_path="Q:/nope/missing.hda")
        _assert_useful(
            "hda.reload_hda",
            str(error.get("message", "")),
            ("not found", "does not exist", "no such"),
        )

    def test_uninstalling_something_never_installed_is_explained(self, call):
        answer = call("hda.uninstall_hda", assert_failure=True, file_path="Q:/nope/missing.hda")
        _assert_useful(
            "hda.uninstall_hda",
            str(answer.get("message", "")),
            ("not found", "does not exist", "not installed", "no such"),
        )


class TestBadArgumentsAreExplained:
    def test_playbar_control_rejects_an_unknown_action(self, call):
        error = call("animation.playbar_control", expect_error=True, action="disco")
        _assert_useful(
            "animation.playbar_control",
            str(error.get("message", "")),
            ("action", "unknown", "invalid", "must be", "one of"),
        )

    def test_create_render_node_rejects_an_unknown_renderer(self, call):
        error = call("rendering.create_render_node", expect_error=True, renderer="notarenderer")
        _assert_useful(
            "rendering.create_render_node",
            str(error.get("message", "")),
            ("renderer", "unknown", "invalid", "must be", "one of", "failed to create"),
        )

    def test_work_item_index_out_of_range_says_the_range(self, call):
        topnet = call("nodes.create_node", parent_path="/obj", node_type="topnet", name="tn1")
        answer = call(
            "tops.get_work_item_info",
            assert_failure=True,
            node_path=topnet["node_path"],
            work_item_index=9999,
        )
        _assert_useful(
            "tops.get_work_item_info",
            str(answer.get("message", "")),
            ("range", "index", "no work", "not cooked", "pdg"),
        )

    def test_vex_expression_on_a_missing_parm_names_it(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="vexgeo")
        error = call(
            "vex.create_vex_expression",
            expect_error=True,
            node_path=geo["node_path"],
            parm_name="no_such_parm",
            vex_code="1;",
        )
        message = str(error.get("message", ""))
        _assert_useful(
            "vex.create_vex_expression", message, ("parameter", "parm", "not found", "no such")
        )
        assert "no_such_parm" in message, message
