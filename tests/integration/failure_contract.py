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


# Commands with no argument that can carry a WRONG VALUE, each with the reason.
#
# Precisely: no semantically invalid value exists for what they accept. Wrong TYPES
# are a separate matter and are rejected by shared validators, asserted in
# TestWrongTypesAndMissingArgumentsAreExplained -- an earlier version of this list
# claimed "no input can be wrong", which a type probe disproved for 6 of them.
#
# This list was 26 entries and 8 of them were wrong. Every one of the 8 had an
# argument with a default, and "has a default" was quietly treated as "cannot be
# given a wrong value" -- but an optional enum still has invalid values, and
# find_nodes takes a path to search inside. They were found by probing all 26 with
# deliberately bad input rather than by re-reading the reasoning, which had already
# convinced its author once. Recorded as a
# fact about the command rather than left looking like an oversight, and checked by
# test_the_no_failure_input_list_is_still_true so it cannot become a permanent
# exemption when one of them grows a parameter.
NO_FAILURE_INPUT: dict[str, str] = {
    "animation.get_frame": "takes nothing; the current frame always exists",
    "context.get_scene_summary": "takes nothing; summarises whatever is loaded",
    "context.get_selection": "takes nothing; an empty selection is a valid answer",
    "cops.list_cop_node_types": "only an optional filter; matching nothing is valid",
    "rendering.list_render_nodes": "takes nothing; an empty /out is a valid answer",
    "scene.get_scene_info": "takes nothing; always describes the current scene",
    "scene.new_scene": "only an optional save flag",
    "takes.get_current_take": "takes nothing; there is always a current take",
    "takes.list_takes": "takes nothing; the main take always exists",
}

# Arguments that exist but cannot be wrong. Empty now: everything that once needed an
# exemption here turned out to be testable after all, which is the same lesson as the
# list above.
HARMLESS_ARGUMENTS: dict[str, set[str]] = {}
