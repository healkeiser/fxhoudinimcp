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
        info = await call("viewport.get_viewport_info", soft=True)
        if info is not None:
            # These two fields are why this check exists: nothing used to report
            # the active Hydra delegate or the path the viewport is really
            # looking through, so a viewport that had reverted to GL on a free
            # perspective looked identical to a framed Karma preview.
            record(
                "PASS",
                "get_viewport_info reports state",
                f"renderer={info.get('renderer')} camera_path={info.get('camera_path')}",
            )
        await call("viewport.set_viewport_display", display_mode="smooth", soft=True)
        await call("viewport.frame_all", soft=True)

        ###### Renderer and camera: the tools must report reality, not intent
        #
        # Both reported success without checking anything, and a session building
        # an ocean in Solaris paid for it: nine execute_python calls, and a
        # delivered shot with the wrong framing and no Karma shading.
        #
        # Semicolons rather than newlines in these snippets: the code travels as a
        # JSON string, and embedded newlines are one escaping layer too many.
        async def set_viewer_context(path: str, current: str | None = None) -> None:
            """Point the viewer at a network, using the tool that now exists.

            This used to need execute_python, which is what the tool was added
            for; using it here means the gate also covers it.
            """
            params = {"network_path": path}
            if current:
                params["current_node"] = current
            await call("viewport.set_viewer_context", soft=True, **params)

        # Hydra delegates only exist for a scene graph view, so an object-level
        # viewport must refuse the request rather than call it unverifiable.
        await set_viewer_context("/obj")
        obj_renderer = await call("viewport.set_viewport_renderer", renderer="Karma CPU", soft=True)
        if obj_renderer is None:
            record("PASS", "set_viewport_renderer refuses a non-Solaris viewport")
        else:
            record(
                "FAIL", "set_viewport_renderer claimed a delegate in /obj", str(obj_renderer)[:90]
            )

        # OBJ camera, verified against viewport.camera(), which returns the node.
        obj_cam = await call(
            "nodes.create_node", parent_path="/obj", node_type="cam", name="mcp_gui_cam"
        )
        bound = await call(
            "viewport.set_viewport_camera", camera_path=obj_cam["node_path"], soft=True
        )
        if bound is not None and bound.get("camera_path") == obj_cam["node_path"]:
            record("PASS", "set_viewport_camera (OBJ) verified", bound["camera_path"])
        else:
            record("FAIL", "set_viewport_camera (OBJ)", str(bound)[:100])

        ###### Solaris: the case that could not be done at all before
        stage_built = await call(
            "graph.build_network",
            parent_path="/stage",
            nodes=[
                {"type": "sphere", "name": "mcp_gui_geo"},
                {
                    "type": "camera",
                    "name": "mcp_gui_lopcam",
                    "inputs": ["mcp_gui_geo"],
                    "flags": {"display": True},
                },
            ],
            soft=True,
        )
        if stage_built is not None and stage_built.get("valid"):
            await set_viewer_context("/stage", "/stage/mcp_gui_lopcam")

            solaris = await call("viewport.set_viewport_renderer", renderer="Storm", soft=True)
            after = await call("viewport.get_viewport_info", soft=True) or {}
            if (
                solaris is not None
                and solaris.get("verified")
                and after.get("renderer") == solaris.get("renderer")
            ):
                record(
                    "PASS",
                    "set_viewport_renderer verified in Solaris",
                    f"{solaris.get('previous_renderer')} -> {solaris['renderer']}",
                )
            else:
                record("FAIL", "set_viewport_renderer in Solaris", str(solaris)[:110])

            # A USD camera prim is not a hou.node, so this was impossible before.
            prim_bound = await call(
                "viewport.set_viewport_camera", camera_path="/cameras/mcp_gui_lopcam", soft=True
            )
            if prim_bound is not None and prim_bound.get("prim_type") == "Camera":
                record("PASS", "set_viewport_camera (USD prim) verified", prim_bound["camera_path"])
            else:
                record("FAIL", "set_viewport_camera (USD prim)", str(prim_bound)[:110])

            # cameraPath() echoes whatever it is given, so a nonexistent prim has
            # to be caught by a stage lookup, not by comparing the echo.
            for bad, label in (
                ("/cameras/does_not_exist", "missing prim"),
                ("/mcp_gui_geo", "non-camera prim"),
            ):
                rejected = await call("viewport.set_viewport_camera", camera_path=bad, soft=True)
                if rejected is None:
                    record("PASS", f"set_viewport_camera rejects a {label}")
                else:
                    record("FAIL", f"set_viewport_camera accepted a {label}", str(rejected)[:80])

            for path in ("/stage/mcp_gui_lopcam", "/stage/mcp_gui_geo"):
                await call("nodes.delete_node", node_path=path, soft=True)
            await set_viewer_context("/obj")

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
