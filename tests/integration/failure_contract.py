"""What a failure message owes its reader, in one place.

Both failure suites assert against this: the table-driven wrong-input cases in
test_failure_paths_live.py and the self-discovering path cases in
test_path_validation_live.py. Keeping the definition here means the standard cannot
drift between them.
"""

from __future__ import annotations

# A path no scene can contain.
GONE = "/obj/definitely_not_a_node_12345"

# Text that means the handler never looked at what it was given. Each of these was
# a real answer from this server before the failure suites existed.
INTERNAL_LEAKS = (
    # A node lookup returned None and the handler used it anyway.
    "nonetype",
    "has no attribute",
    "not subscriptable",
    "unhashable",
    # Signature mismatches, which are a bug in the tool definition, not user error.
    "unexpected keyword argument",
    "positional argument",
    # Houdini's generic OperationFailed text. Technically a message, but it names
    # nothing and leaves no next step, so a handler that passes it through
    # unwrapped has explained nothing.
    "the attempted operation failed",
    "traceback",
)


def message_of(answer: dict) -> str:
    """The human-readable part of a failure, whichever shape it arrived in.

    Handlers report a single ``message``, or an ``errors`` list when they validate
    several things at once (build_network checks a whole graph), or an ``error``
    string. A caller should not have to know which, and neither should a test.
    """
    if not isinstance(answer, dict):
        return str(answer)
    single = answer.get("message") or answer.get("error")
    if single:
        return str(single)
    errors = answer.get("errors") or []
    return "; ".join(str(error) for error in errors)


def assert_useful(command: str, message: str, must_mention: tuple[str, ...] = ()) -> None:
    """Assert a failure message is worth reading.

    Args:
        command: For the assertion text.
        message: What the handler said.
        must_mention: Any one of these substrings must appear. Deliberately loose:
            the point is that the message names the problem, not that it uses
            particular wording.
    """
    assert message.strip(), f"{command} failed with an empty message"
    low = message.lower()
    for leak in INTERNAL_LEAKS:
        assert leak not in low, (
            f"{command} leaked a Python internal instead of explaining itself: {message!r}"
        )
    if must_mention:
        assert any(hint in low for hint in must_mention), (
            f"{command} did not say what was wrong. Expected one of {must_mention}, "
            f"got: {message!r}"
        )


# Commands with no argument that can be wrong, each with the reason. Recorded as a
# fact about the command rather than left looking like an oversight, and checked by
# test_the_no_failure_input_list_is_still_true so it cannot become a permanent
# exemption when one of them grows a parameter.
NO_FAILURE_INPUT: dict[str, str] = {
    "animation.get_frame": "takes nothing; the current frame always exists",
    "animation.set_frame": "any float is a frame; Houdini clamps to the range",
    "code.get_env_variable": "an unset variable is a valid answer, not a failure",
    "code.execute_hscript": (
        "hscript reports an unknown command in its output rather than by failing, "
        "so there is no input that makes the call itself fail"
    ),
    "context.compare_snapshots": "defaults to taking a snapshot; nothing to get wrong",
    "context.get_scene_summary": "takes nothing; summarises whatever is loaded",
    "context.get_selection": "takes nothing; an empty selection is a valid answer",
    "cops.list_cop_node_types": "only an optional filter; matching nothing is valid",
    "hda.list_installed_hdas": "only an optional filter; matching nothing is valid",
    "materials.create_material_network": "any name is valid; Houdini uniquifies collisions",
    "materials.list_material_types": "only an optional filter; matching nothing is valid",
    "nodes.find_nodes": "all arguments optional; finding nothing is a valid answer",
    "rendering.list_render_nodes": "takes nothing; an empty /out is a valid answer",
    "scene.get_scene_info": "takes nothing; always describes the current scene",
    "scene.new_scene": "only an optional save flag",
    "shelf.list_shelf_tools": "only an optional filter; matching nothing is valid",
    "takes.create_take": "any name is valid; Houdini uniquifies collisions",
    "takes.get_current_take": "takes nothing; there is always a current take",
    "takes.list_takes": "takes nothing; the main take always exists",
    "viewport.log_status": "any string is a valid status message",
    "workflow.create_material": "every argument has a working default",
    "workflow.setup_render": "every argument has a working default",
    # The sim setups reference their source geometry through an Object Merge
    # parameter, so a missing source is fixable afterwards and is reported as a
    # warning by design. TestSimSetupsWarnRatherThanFail asserts the warning.
    "workflow.setup_flip_sim": "a missing source is a warning, not a failure; see the warning test",
    "workflow.setup_pyro_sim": "a missing source is a warning, not a failure; see the warning test",
    "workflow.setup_rbd_sim": "a missing source is a warning, not a failure; see the warning test",
    "workflow.setup_vellum_sim": (
        "a missing source is a warning, not a failure; see the warning test"
    ),
}

# Arguments that exist but cannot be wrong: free text that is echoed back, or a
# lookup whose empty answer is legitimate.
HARMLESS_ARGUMENTS: dict[str, set[str]] = {
    "animation.set_frame": {"frame"},
    "code.execute_hscript": {"command"},
    "code.get_env_variable": {"var_name"},
    "materials.create_material_network": {"name"},
    "takes.create_take": {"name"},
    "viewport.log_status": {"message"},
}
