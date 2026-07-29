"""Every command that takes a node path must reject one that does not resolve.

This test discovers its own cases: it walks the handler registry, finds each
command with a path-like parameter, and calls it with a path that cannot exist. A
command added tomorrow is covered tomorrow, without anyone remembering to add a
table entry -- which is the failure mode that let six false-success bugs ship
behind 188/188 command coverage.

The property is narrow and absolute. Given a path that does not resolve, a handler
must not report success, and its message must name the path. Both halves matter:

* not reporting success is what stops a caller building on a result that describes
  nothing -- get_top_network_info returned "top_node_count: 0, cook_state:
  unknown" for a box SOP, which reads as an empty TOP network;
* naming the path is what turns a retry into a fix. "Node not found" alone leaves
  a caller guessing which of the four paths it passed was wrong.

Bespoke wrong-input cases (unknown enum values, missing files, bad ranges) live in
test_failure_paths_live.py. This file is only about path resolution, because that
is the one failure every one of these commands shares.
"""

from __future__ import annotations

# Built-in
import inspect
import sys
import tempfile
from pathlib import Path

# Third-party
import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, "houdini/scripts/python")

import fxhoudinimcp_server.dispatcher as dispatcher  # noqa: E402

# Parameter names that take a path to something that must already exist.
PATH_PARAMS = (
    "node_path",
    "parent_path",
    "root_path",
    "chop_path",
    "network_path",
    "target_node_path",
    "source_path",
    "path",
    # The sim setups and material assignment take the geometry they operate on
    # under these names. Their defaults point at /obj/geo1/sphere1, which usually
    # does not exist either -- so a caller who forgets the argument gets whatever
    # this handler does with a missing node.
    "geo_path",
    "source_geo",
)

# A path no scene can contain.
GONE = "/obj/definitely_not_a_node_12345"

# Every OTHER argument has to be valid, or the handler rejects it first and this
# test learns nothing about path validation. import_file checks its file before its
# parent, and capture_network_editor checks its output directory before its node --
# both correct orderings, so the fixture data has to be real.
_SCRATCH = Path(tempfile.mkdtemp(prefix="fxh_pathcheck_"))
_REAL_FILE = _SCRATCH / "stand_in.obj"
_REAL_FILE.write_text("v 0 0 0\n", encoding="utf-8")

# Stand-ins for the other required arguments. The values only have to be
# well-formed: the path is what is under test, and it must be rejected before any
# of these is looked at. A handler that validates these FIRST and the path second
# still passes, as long as it does not claim success.
STAND_INS: dict[str, object] = {
    "parm_name": "tx",
    "parm_type": "float",
    "attrib_name": "P",
    "attr_name": "xformOp:translate",
    "group_name": "group1",
    "label": "Label",
    "type_name": "fxh::test::1.0",
    "new_name": "renamed",
    "name": "thing",
    "frame": 1.0,
    "value": 0,
    "x": 0.0,
    "y": 0.0,
    "r": 0.0,
    "g": 0.0,
    "b": 0.0,
    "start": 1.0,
    "end": 2.0,
    "position": [0.0, 0.0, 0.0],
    "new_order": [0],
    "keyframes": [],
    "nodes": [],
    "params": {},
    "parameters": {},
    "properties": {},
    "connections": [],
    "settings": {},
    "locked": True,
    "pattern": "*",
    "prim_path": "/root",
    "expression": "1",
    "vex_code": "@P.y += 1;",
    "chop_type": "null",
    "lop_type": "null",
    "cop_type": "null",
    "node_type": "null",
    "context": "/obj",
    "dest_path": "/obj",
    "dest_parent": "/obj",
    "dest_parm": "tx",
    "source_parm": "tx",
    "work_item_index": 0,
    "channel_name": "chan1",
    "target_parm_name": "tx",
    "field_name": "density",
    "data_path": "Geometry",
    "object_name": "obj1",
    "section_name": "PythonModule",
    "content": "x",
    "file_path": str(_REAL_FILE).replace("\\", "/"),
    "hda_file": str(_SCRATCH / "thing.hda").replace("\\", "/"),
    "output_path": str(_SCRATCH / "thing.png").replace("\\", "/"),
    "target_node_path": "/obj",
    "tool_name": "sop_box",
    "steps": [{"node_type": "box"}],
    "message": "hello",
    "geo_path": GONE,
    "material_path": GONE,
    "renderer": "Karma",
    "layer_index": 0,
    "output_index": 0,
}

# Optional arguments that must nevertheless be supplied, because the handler
# validates them BEFORE the path and would otherwise never reach the path check.
EXTRAS: dict[str, dict] = {
    # steps has a default of None but is rejected first when empty.
    "workflow.build_sop_chain": {"steps": [{"type": "box"}]},
}

# Commands this property does not apply to, each for a stated reason.
NOT_A_LOOKUP: frozenset[str] = frozenset(
    {
        # "path" here is a help page path ("nodes/sop/scatter"), not a node path.
        # Its own rejection message is already excellent, and is covered by
        # test_help_live.py.
        "help.get_help_page",
        # These cannot reach path validation in hython: they need a UI, and the
        # require_ui guard fires first, which is the correct order. Their headless
        # failure is asserted in test_failure_paths_live.py instead.
        "rendering.render_node_network",
        "rendering.render_viewport",
        "rendering.render_quad_view",
        "viewport.capture_network_editor",
        "viewport.set_current_network",
        "viewport.set_viewport_camera",
        # These build a complete network and reference the source geometry through
        # an Object Merge parameter, which is legitimately fixable afterwards -- so
        # a missing source is a warning, not a failure. What they owe the caller is
        # source_geo_found and a description saying the sim will produce nothing
        # until it is fixed, which test_sim_setups_warn_about_a_missing_source
        # asserts instead.
        "workflow.setup_flip_sim",
        "workflow.setup_pyro_sim",
        "workflow.setup_rbd_sim",
        "workflow.setup_vellum_sim",
    }
)

# Python internals that mean the handler never checked what it was given.
_LEAKS = (
    "nonetype",
    "has no attribute",
    "not subscriptable",
    "the attempted operation failed",
    "traceback",
)


def _cases() -> list[tuple[str, str, dict]]:
    """(command, path_param, params) for every command taking an existing path."""
    found: list[tuple[str, str, dict]] = []
    for command in dispatcher.list_commands():
        if command in NOT_A_LOOKUP:
            continue
        handler = dispatcher._handler_registry[command]
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            continue
        params = {
            name: param
            for name, param in signature.parameters.items()
            if param.kind not in (param.VAR_KEYWORD, param.VAR_POSITIONAL)
        }
        path_param = next((name for name in params if name in PATH_PARAMS), None)
        if path_param is None:
            continue
        call_params: dict = {path_param: GONE}
        missing = []
        for name, param in params.items():
            if name == path_param or param.default is not param.empty:
                continue
            if name in STAND_INS:
                call_params[name] = STAND_INS[name]
            else:
                missing.append(name)
        if missing:
            # Better to fail loudly than to silently skip a command: an unknown
            # required argument means this test has drifted from the handlers.
            found.append((command, path_param, {"__missing__": missing}))
            continue
        call_params.update(EXTRAS.get(command, {}))
        found.append((command, path_param, call_params))
    return found


CASES = _cases()


def test_the_registry_was_actually_walked():
    """Guard against the discovery silently finding nothing."""
    assert len(CASES) > 80, f"expected most commands to take a path, found {len(CASES)}"


@pytest.mark.parametrize(
    ("command", "path_param", "params"),
    CASES,
    ids=[f"{command}" for command, _, _ in CASES],
)
def test_unresolvable_path_is_rejected_and_named(call, command, path_param, params):
    missing = params.get("__missing__")
    assert not missing, (
        f"{command} has required arguments this test does not know how to fill: "
        f"{missing}. Add them to STAND_INS."
    )

    answer = call(command, assert_failure=True, **params)
    # Handlers report either a single message or a list of errors; build_network
    # collects several because it validates a whole graph at once.
    message = str(answer.get("message") or "") or "; ".join(
        str(e) for e in (answer.get("errors") or [])
    )
    low = message.lower()

    for leak in _LEAKS:
        assert leak not in low, (
            f"{command} leaked a Python internal for a bad {path_param} "
            f"instead of explaining itself: {message!r}"
        )
    assert GONE in message, (
        f"{command} rejected a bad {path_param} without naming it, so a caller "
        f"cannot tell which argument was wrong: {message!r}"
    )


class TestSimSetupsWarnRatherThanFail:
    """A placeholder source is allowed. Saying nothing about it is not.

    All four sim setups point an Object Merge at the source geometry, which is a
    parameter the caller can fix later -- so building the network is a real success
    even when the path is wrong. But setup_pyro_sim was the only one that said so.
    The other three reported success: True and nothing else, leaving a caller with a
    sim that will never produce a single voxel and no reason to look at it.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "workflow.setup_flip_sim",
            "workflow.setup_pyro_sim",
            "workflow.setup_rbd_sim",
            "workflow.setup_vellum_sim",
        ],
    )
    def test_sim_setups_warn_about_a_missing_source(self, call, command):
        argument = (
            "source_geo"
            if command
            in {
                "workflow.setup_flip_sim",
                "workflow.setup_pyro_sim",
            }
            else "geo_path"
        )
        data = call(command, **{argument: GONE})

        assert data["success"] is True, data
        assert data["source_geo_found"] is False, (
            f"{command} did not report that its source geometry is missing: {data}"
        )
        description = str(data.get("network_description", ""))
        assert "WARNING" in description, (
            f"{command} built a sim with a missing source and did not warn: {description!r}"
        )
        # Naming the parameter to fix is the difference between a warning and a
        # shrug.
        assert "objpath1" in description and GONE in description, description
