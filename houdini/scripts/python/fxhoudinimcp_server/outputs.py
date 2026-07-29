"""Proving that a node that writes to disk actually wrote to disk.

Every tool here exists because a call returning without raising is not evidence
that anything happened. Three separate tools shipped claiming success they never
checked:

* ``start_render`` reported ``success: True`` in 0.5 seconds for a Karma render
  that wrote nothing. ``usdrender_rop`` shells out to ``husk``, and when husk
  exits non-zero -- no license, bad scene, missing camera -- the ROP records the
  error while ``render()`` returns normally.
* ``export_file`` returned the hardcoded string ``"Render complete."`` after the
  same ``render()`` call, reading no errors and checking no file.
* ``write_cache`` set ``status = "success"`` after ``pressButton()``, which is
  fire-and-forget: a File Cache SOP that fails to write raises nothing at all.

So the rule this module encodes is that a write is verified by reading the node's
own errors and by comparing the output paths before and after -- never by the
absence of an exception. Existence alone is not evidence either: re-rendering over
yesterday's frame would look like success even if nothing ran, so the comparison
is against a snapshot taken beforehand.
"""

from __future__ import annotations

# Built-in
import contextlib
import os
from typing import Any

# Third-party
import hou

# Where different node types keep their output path. A render that reports success
# and writes nowhere is indistinguishable from one that worked, which is why a
# recorded session resorted to PowerShell to stat the output directory.
OUTPUT_PARMS = (
    "sopoutput",
    "lopoutput",
    "picture",
    "outputimage",
    "file",
    "dopoutput",
    "copoutput",
)

# Output values that are not files. "__render__.usd" is the in-memory stage a LOP
# ROP feeds to husk, and ip/md are MPlay targets, so reporting them as missing
# files would be noise that trains a caller to ignore this field.
NON_FILE_OUTPUTS = frozenset({"__render__.usd", "ip", "md"})


def reported_outputs(node: hou.Node) -> list[dict[str, Any]]:
    """The node's output path(s) and whether anything is on disk there."""
    found: list[dict[str, Any]] = []
    for name in OUTPUT_PARMS:
        parm = node.parm(name)
        if parm is None:
            continue
        try:
            path = parm.eval()
        except hou.OperationFailed:
            continue
        if not path:
            # An empty output path is the quiet failure worth naming: the node
            # ran and wrote nothing.
            found.append({"parm": name, "path": None, "exists": False, "empty": True})
            continue
        if path in NON_FILE_OUTPUTS:
            found.append({"parm": name, "path": path, "is_file_output": False})
            continue
        entry: dict[str, Any] = {"parm": name, "path": path}
        with contextlib.suppress(Exception):
            entry["exists"] = os.path.exists(path)
            if entry["exists"]:
                entry["size_bytes"] = os.path.getsize(path)
                entry["mtime"] = os.path.getmtime(path)
        found.append(entry)
    return found


def wrote_anything(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    """Whether any file output appeared or changed between two snapshots.

    Existence alone is not evidence: re-rendering over yesterday's frame would
    look like success even if nothing ran.
    """
    prior = {entry.get("path"): entry for entry in before}
    for entry in after:
        if not entry.get("exists") or entry.get("is_file_output") is False:
            continue
        was = prior.get(entry.get("path"))
        if was is None or not was.get("exists"):
            return True
        if entry.get("mtime") and was.get("mtime") and entry["mtime"] > was["mtime"]:
            return True
        if entry.get("size_bytes") != was.get("size_bytes"):
            return True
    return False


# A node that delegates its write can hold no errors at all while the node doing
# the work holds every one of them, so a bounded walk inside is necessary.
_MAX_DESCENDANTS_SCANNED = 400
_MAX_MESSAGES = 12


def node_messages(node: hou.Node) -> tuple[list[str], list[str]]:
    """A node's errors and warnings, including those of whatever it delegates to.

    Verified on Houdini 22.0: a filecache SOP whose Save to Disk fails reports
    ``errors() == ()`` on itself, while its internal ``render`` rop_geometry holds
    "Failed to save output to file ..." ten times over. A filecache is an HDA that
    presses an embedded ROP, so reading only the top node's errors misses the
    whole failure -- which is exactly how write_cache came to report success for a
    cache that was never written.
    """
    errors: list[str] = []
    warnings: list[str] = []
    with contextlib.suppress(Exception):
        errors = [e.strip()[:400] for e in node.errors()]
    with contextlib.suppress(Exception):
        warnings = [w.strip()[:400] for w in node.warnings()]

    if errors:
        return errors[:_MAX_MESSAGES], warnings[:_MAX_MESSAGES]

    # Nothing on the node itself: look inside. Only worth doing when the node is
    # silent, and bounded so a deep HDA cannot turn this into a scene walk.
    with contextlib.suppress(Exception):
        for index, child in enumerate(node.allSubChildren()):
            if index >= _MAX_DESCENDANTS_SCANNED:
                break
            with contextlib.suppress(Exception):
                for message in child.errors():
                    # Name the node, because "/render" inside a filecache is not
                    # somewhere the caller knows to look.
                    errors.append(f"{child.path()}: {message.strip()[:360]}")
                    if len(errors) >= _MAX_MESSAGES:
                        break
            if len(errors) >= _MAX_MESSAGES:
                break
    return errors[:_MAX_MESSAGES], warnings[:_MAX_MESSAGES]


def write_verdict(
    node: hou.Node,
    before: list[dict[str, Any]],
    *,
    action: str = "Render",
) -> dict[str, Any]:
    """What actually happened, for a node whose execution has just returned.

    Returns the ``success`` / ``errors`` / ``warnings`` / ``wrote_files`` /
    ``outputs`` / ``message`` block that every write tool reports, so all of them
    answer "did this work" the same way and a caller never has to learn a second
    convention.

    Args:
        node: The node that was just executed.
        before: The ``reported_outputs`` snapshot taken before executing it.
        action: How to name the operation in the message ("Render", "Export",
            "Cache write").
    """
    errors, warnings = node_messages(node)
    after = reported_outputs(node)
    wrote = wrote_anything(before, after)
    # Did the node name a real file to write? An empty output path counts: it was
    # asked to write somewhere and had nowhere to write, which is a failure, not a
    # node that legitimately targets MPlay.
    named_a_file = any(entry.get("is_file_output") is not False for entry in after)

    verdict: dict[str, Any] = {
        "success": not errors and (wrote or not named_a_file),
        "wrote_files": wrote,
        "outputs": after,
    }
    if errors:
        verdict["errors"] = errors
        verdict["message"] = f"{action} reported {len(errors)} error(s); nothing was verified."
    elif named_a_file and not wrote:
        # Silence is not success. A node that was told to write a file, reported no
        # error and produced nothing did not do its job, and saying otherwise is
        # the whole failure this module exists to prevent.
        verdict["message"] = (
            f"{action} reported no errors, but no output file appeared or changed. "
            f"Nothing was written."
        )
    elif not named_a_file:
        # No recognised file target: an MPlay render, or an output parameter this
        # server does not know about. Do not claim to have verified either way.
        verdict["message"] = (
            f"{action} reported no errors. No file output was found to check, so "
            f"whether anything was written is unverified -- this is normal for a "
            f"render to MPlay."
        )
        verdict["output_verified"] = False
    else:
        verdict["message"] = f"{action} completed and wrote output."
    if warnings:
        verdict["warnings"] = warnings
    return verdict


def failure_verdict(
    node: hou.Node,
    before: list[dict[str, Any]],
    error: BaseException | str,
    *,
    action: str = "Render",
) -> dict[str, Any]:
    """The same shape as :func:`write_verdict`, for an execution that raised.

    Keeping the shape identical means a caller never has to branch on which kind
    of failure it was to find out whether anything was written.
    """
    after = reported_outputs(node)
    return {
        "success": False,
        "error": str(error),
        "errors": [str(error)[:400]],
        "wrote_files": wrote_anything(before, after),
        "outputs": after,
        "message": f"{action} raised before completing; nothing was verified.",
    }
