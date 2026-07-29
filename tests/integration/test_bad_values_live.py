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


class TestTheDeclaredUnbreakableWereProbed:
    """The eight commands I wrongly claimed had no wrong input.

    Every entry in NO_FAILURE_INPUT was an argument, not a test -- and 8 of the
    original 26 were wrong. Each had a parameter with a default, and "has a default"
    was treated as "cannot be given a wrong value". An optional enum still has
    invalid values.

    All eight already validated correctly; what was missing was any test saying so,
    which is why the wrong reasoning survived. Three more were genuinely broken and
    are covered by TestSilentlyIgnoredArgumentsAreRejected below.
    """

    def test_set_frame_rejects_something_that_is_not_a_number(self, call):
        answer = call("animation.set_frame", assert_failure=True, frame="abc")
        message = message_of(answer)
        # It used to answer "in method 'setFrame', argument 1 of type 'double'" --
        # a SWIG binding message naming neither the argument nor this server.
        assert_useful("animation.set_frame", message, ("frame", "number", "numeric"))

    def test_compare_snapshots_rejects_an_unknown_action(self, call):
        answer = call("context.compare_snapshots", assert_failure=True, action="notanaction")
        assert_useful(
            "context.compare_snapshots",
            message_of(answer),
            ("action", "must be", "unknown", "take", "compare"),
        )

    def test_comparing_a_snapshot_never_taken_names_what_exists(self, call):
        answer = call(
            "context.compare_snapshots",
            assert_failure=True,
            action="compare",
            snapshot_name="never_taken_xyz",
        )
        message = message_of(answer)
        assert_useful("context.compare_snapshots", message, ("snapshot", "not"))
        assert "never_taken_xyz" in message, message

    @pytest.mark.parametrize("name", ["", "bad name w spaces"])
    def test_material_network_rejects_a_name_houdini_cannot_use(self, call, name):
        answer = call("materials.create_material_network", assert_failure=True, name=name)
        assert_useful(
            "materials.create_material_network",
            message_of(answer),
            ("name", "invalid", "failed"),
        )

    def test_material_network_rejects_an_unknown_shader_type(self, call):
        answer = call(
            "materials.create_material_network",
            assert_failure=True,
            name="m1",
            shader_type="notashader",
        )
        assert_useful(
            "materials.create_material_network",
            message_of(answer),
            ("notashader", "invalid", "type", "unknown"),
        )

    def test_find_nodes_rejects_a_search_root_that_does_not_exist(self, call):
        # "inside" is a path parameter, which is why the self-discovering path suite
        # now knows the name. It validated correctly all along.
        answer = call("nodes.find_nodes", assert_failure=True, inside=GONE)
        message = message_of(answer)
        assert_useful("nodes.find_nodes", message, ("not found", "does not exist"))
        assert GONE in message, message

    def test_create_take_rejects_a_parent_that_does_not_exist(self, call):
        answer = call(
            "takes.create_take",
            assert_failure=True,
            name="t1",
            parent_name="no_such_parent_xyz",
        )
        message = message_of(answer)
        assert_useful("takes.create_take", message, ("take", "not found", "parent"))
        assert "no_such_parent_xyz" in message, message

    def test_create_material_rejects_an_unknown_type(self, call):
        answer = call("workflow.create_material", assert_failure=True, mat_type="notatype")
        assert_useful(
            "workflow.create_material",
            message_of(answer),
            ("mat_type", "must be", "unknown", "principled", "materialx"),
        )

    def test_setup_render_rejects_an_unknown_renderer(self, call):
        answer = call("workflow.setup_render", assert_failure=True, renderer="notarenderer")
        assert_useful(
            "workflow.setup_render",
            message_of(answer),
            ("renderer", "must be", "unknown", "karma", "mantra"),
        )

    def test_setup_vellum_rejects_an_unknown_sim_type(self, call):
        answer = call("workflow.setup_vellum_sim", assert_failure=True, sim_type="notasimtype")
        assert_useful(
            "workflow.setup_vellum_sim",
            message_of(answer),
            ("sim_type", "must be", "invalid", "cloth"),
        )


class TestSilentlyIgnoredArgumentsAreRejected:
    """Three parameters were accepted, ignored, and reported as success.

    setup_rbd_sim only ever acted on pieces_type == "voronoi"; every other string
    skipped fracturing entirely and still returned success: True, so a typo gave
    back an unfractured sim that looks like a working one. Not fracturing is a real
    request, so it now has a name ("none") instead of being what happens when you
    misspell the other one.

    setup_flip_sim's "domain" and setup_pyro_sim's "container" were documented
    "reserved for future use" and consumed nowhere. A parameter that is accepted and
    ignored is worse than one that is missing, because it reads as functional: ask
    for a sphere domain, get a box, and be told it worked.
    """

    def test_rbd_rejects_an_unknown_pieces_type(self, call):
        answer = call("workflow.setup_rbd_sim", assert_failure=True, pieces_type="notapieces")
        assert_useful(
            "workflow.setup_rbd_sim",
            message_of(answer),
            ("pieces_type", "must be", "invalid", "voronoi"),
        )

    def test_rbd_accepts_none_as_a_deliberate_choice(self, call):
        data = call("workflow.setup_rbd_sim", pieces_type="none", geo_path="/obj")
        assert data["success"] is True, data
        assert not any("fracture" in path for path in data["all_nodes"]), (
            f"pieces_type='none' still fractured: {data['all_nodes']}"
        )

    def test_flip_rejects_an_unimplemented_domain(self, call):
        answer = call("workflow.setup_flip_sim", assert_failure=True, domain="sphere")
        assert_useful(
            "workflow.setup_flip_sim",
            message_of(answer),
            ("domain", "box", "not implemented", "unsupported"),
        )

    def test_pyro_rejects_an_unimplemented_container(self, call):
        answer = call("workflow.setup_pyro_sim", assert_failure=True, container="sphere")
        assert_useful(
            "workflow.setup_pyro_sim",
            message_of(answer),
            ("container", "box", "not implemented", "unsupported"),
        )


class TestWrongTypesAndMissingArgumentsAreExplained:
    """A second, wider probe: every parameter of every command declared unbreakable.

    The first probe used semantically wrong values and found 8. This one threw wrong
    TYPES at every argument and found 6 more, all leaking Python internals -- an int
    passed as a filter came back "'int' object has no attribute 'lower'", which
    names neither the argument nor this server.

    A compliant MCP client cannot send these, because the tool schema type-checks
    them. They are reachable through the HTTP bridge directly, and the contract this
    server states is that no answer leaks a Python internal, so the schema being a
    first line of defence is not a reason to have no second.
    """

    @pytest.mark.parametrize(
        ("command", "argument", "value"),
        [
            ("shelf.list_shelf_tools", "filter", 12345),
            ("shelf.list_shelf_tools", "limit", "many"),
            ("hda.list_installed_hdas", "filter", 12345),
            ("materials.list_material_types", "filter", []),
            ("code.execute_hscript", "command", 12345),
            ("code.get_env_variable", "var_name", 12345),
            ("animation.set_frame", "frame", "abc"),
        ],
    )
    def test_a_wrong_type_names_the_argument_and_its_type(self, call, command, argument, value):
        answer = call(command, assert_failure=True, **{argument: value})
        message = message_of(answer)
        # assert_useful bans the leaks; this also requires the argument be named.
        assert_useful(command, message)
        assert argument in message, (
            f"{command} rejected a bad {argument} without naming it: {message!r}"
        )
        assert type(value).__name__ in message, (
            f"{command} did not say what type it got: {message!r}"
        )

    def test_a_missing_required_argument_names_the_command_and_what_it_takes(self, call):
        # Python answers "log_status() missing 1 required positional argument", which
        # names an internal function rather than the command.
        answer = call("viewport.log_status", assert_failure=True, severity="message")
        message = message_of(answer)
        assert "viewport.log_status" in message, message
        assert "message" in message, message
        assert "Required" in message and "Optional" in message, (
            f"the answer did not say what the command accepts: {message!r}"
        )

    def test_an_unexpected_argument_is_explained_not_crashed(self, call):
        answer = call(
            "nodes.create_node",
            assert_failure=True,
            parent_path="/obj",
            node_type="geo",
            not_a_real_argument=1,
        )
        message = message_of(answer)
        assert "not_a_real_argument" in message, message
        assert "nodes.create_node" in message, message

    def test_an_inner_type_error_is_not_disguised_as_an_argument_error(self, call):
        """The rewrite must not swallow a genuine bug.

        A TypeError raised INSIDE a handler is a real defect, and relabelling it as
        "you called this wrong" would send someone to fix their arguments while the
        bug stays put. Only a mismatch naming the handler itself is rewritten.
        """
        answer = call(
            "code.execute_python",
            assert_failure=True,
            code="'string' + 1",
        )
        blob = message_of(answer) + str(answer)
        assert "TypeError" in blob, blob
        assert "was called with the wrong arguments" not in blob, (
            f"an error from inside the handler was mislabelled as an argument error: {blob}"
        )
