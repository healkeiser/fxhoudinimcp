#!/usr/bin/env python3
"""GUI-session checks against a RUNNING graphical Houdini.

    python tests/integration/gui_session_check.py [--keep]

Connects to the MCP plugin in a live graphical Houdini (HOUDINI_PORT,
default 8100) through the production HTTP transport — which exercises
the hdefereval main-thread dispatch path that headless tests cannot
reach — and verifies the GUI-only surface: status bar, viewport
control, real screenshots, network-editor capture, OpenGL rendering,
and the runtime auto-layout toggle.

Non-destructive: everything happens inside /obj/__mcp_gui_check, which
is deleted at the end unless --keep is passed. The open scene is never
cleared or saved.
"""

from __future__ import annotations

# Built-in
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

CONTAINER = "__mcp_gui_check"
RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from fxhoudinimcp.bridge import HoudiniBridge
    from fxhoudinimcp.errors import FXHoudiniError

    keep = "--keep" in sys.argv
    port = int(os.environ.get("HOUDINI_PORT", "8100"))
    bridge = HoudiniBridge(host="127.0.0.1", port=port)
    out_dir = Path(tempfile.mkdtemp(prefix="fxh_gui_"))
    timings: list[tuple[str, float]] = []

    async def call(command: str, soft: bool = False, **params):
        start = time.perf_counter()
        try:
            data = await bridge.execute(command, params or None)
        except FXHoudiniError as exc:
            if soft:
                record("SOFT", command, str(exc)[:90])
                return None
            record("FAIL", command, str(exc)[:120])
            raise
        timings.append((command, (time.perf_counter() - start) * 1000))
        return data

    try:
        health = await bridge.health_check()
    except Exception as exc:
        print(
            f"Cannot reach Houdini on port {port}: {exc}\n"
            "Start the MCP server in your session (MCP Server shelf tool) "
            "or set HOUDINI_PORT."
        )
        return 2
    record("PASS", "health", f"Houdini {health.get('houdini_version')} pid {health.get('pid')}")

    ui = await call(
        "code.execute_python",
        code="result = hou.isUIAvailable()",
        return_expression="result",
    )
    if "True" not in str(ui):
        print("This session is not graphical — aborting (use the integration suite for headless).")
        return 2
    record("PASS", "graphical session confirmed (hdefereval dispatch path active)")

    try:
        ###### Status bar (visible to you right now)
        await call(
            "viewport.log_status",
            message="FXHoudini MCP GUI checks running...",
            severity="important",
        )
        record("PASS", "log_status in real status bar")

        ###### Build a small network inside the sandbox container
        container = (
            await call("nodes.create_node", parent_path="/obj", node_type="geo", name=CONTAINER)
        )["node_path"]
        chain = await call(
            "workflow.build_sop_chain",
            parent_path=container,
            steps=[
                {"type": "testgeometry_pighead"},
                {"type": "polybevel"},
                {"type": "color", "params": {"colorr": 0.9, "colorg": 0.4, "colorb": 0.1}},
            ],
        )
        record("PASS", "build_sop_chain via hdefereval", f"{len(chain['nodes'])} nodes")

        await call("viewport.set_current_network", network_path=container)
        await call("nodes.layout_children", parent_path=container)
        record("PASS", "set_current_network + layout_children")

        ###### Viewport control
        panes = await call("viewport.list_panes")
        record("PASS", "list_panes", str(panes)[:90])
        await call("viewport.get_viewport_info", soft=True)
        await call("viewport.set_viewport_display", display_mode="smooth", soft=True)
        await call("viewport.frame_all", soft=True)

        ###### Real captures
        viewport_png = str(out_dir / "viewport.png").replace("\\", "/")
        result = await call("viewport.capture_screenshot", output_path=viewport_png, soft=True)
        if result is not None:
            size = os.path.getsize(viewport_png) if os.path.isfile(viewport_png) else 0
            if size > 1024:
                record("PASS", "capture_screenshot", f"{viewport_png} ({size // 1024} KB)")
            else:
                record("FAIL", "capture_screenshot", f"claimed success, file size {size}")

        network_png = str(out_dir / "network.png").replace("\\", "/")
        result = await call(
            "viewport.capture_network_editor",
            output_path=network_png,
            node_path=container,
            soft=True,
        )
        if result is not None:
            size = os.path.getsize(network_png) if os.path.isfile(network_png) else 0
            if size > 1024:
                record("PASS", "capture_network_editor", f"{network_png} ({size // 1024} KB)")
            else:
                record("FAIL", "capture_network_editor", f"claimed success, file size {size}")

        ###### OpenGL viewport render
        flip_png = str(out_dir / "opengl.$F4.png").replace("\\", "/")
        result = await call(
            "rendering.render_viewport", output_path=flip_png, resolution=[320, 240], soft=True
        )
        if result is not None:
            written = list(out_dir.glob("opengl.*.png"))
            if written:
                record("PASS", "render_viewport (OpenGL)", str(written[0]))
            else:
                record("FAIL", "render_viewport", "claimed success, no image written")

        ###### Runtime auto-layout toggle (v1.1.0 feature) in a live session
        await call(
            "code.execute_python",
            code='hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")',
        )
        toggled = await call("nodes.layout_children", parent_path=container)
        await call(
            "code.execute_python",
            code='hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "1")',
        )
        if toggled.get("skipped") is True:
            record("PASS", "auto-layout toggle honored at runtime (hou.putenv)")
        else:
            record("FAIL", "auto-layout toggle", f"expected skip, got {toggled}")

    finally:
        if not keep:
            try:
                await bridge.execute("nodes.delete_node", {"node_path": f"/obj/{CONTAINER}"})
                record("PASS", "cleanup", f"/obj/{CONTAINER} removed")
            except Exception as exc:
                record("SOFT", "cleanup", str(exc)[:80])
        import contextlib

        with contextlib.suppress(Exception):
            await bridge.execute(
                "viewport.log_status",
                {"message": "FXHoudini MCP GUI checks finished."},
            )
        await bridge.close()

    print()
    print(f"{'command':<44} {'ms':>8}")
    for command, ms in sorted(timings, key=lambda t: -t[1]):
        print(f"{command:<44} {ms:>8.1f}")
    print()
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    soft = [r for r in RESULTS if r[0] == "SOFT"]
    print(
        f"GUI checks: {len(RESULTS) - len(failed) - len(soft)} passed, "
        f"{len(soft)} soft-failed, {len(failed)} failed"
    )
    print(f"captures in: {out_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
