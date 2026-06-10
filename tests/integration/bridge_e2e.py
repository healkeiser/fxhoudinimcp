#!/usr/bin/env python3
"""End-to-end transport test: real hwebserver in hython, real HoudiniBridge.

    python tests/integration/bridge_e2e.py

Spawns one hython process that runs the actual in-Houdini server
(fxhoudinimcp_server.startup), then drives it over HTTP with the MCP
server's own async HoudiniBridge — the exact production path. Exercises
success envelopes, structured errors, and scene mutation round-trips.
"""

from __future__ import annotations

# Built-in
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from run_integration import find_hython  # noqa: E402

_SERVER_SNIPPET = """
import sys
sys.path.insert(0, {scripts!r})
import fxhoudinimcp_server.startup as startup
startup.start()  # blocks in hython, serving requests
import time
time.sleep(3600)
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _exercise(port: int) -> None:
    from fxhoudinimcp.bridge import HoudiniBridge
    from fxhoudinimcp.errors import FXHoudiniError

    bridge = HoudiniBridge(host="127.0.0.1", port=port)
    try:
        health = await bridge.health_check()
        assert health.get("status") == "ok", health
        print(f"[e2e] health: Houdini {health.get('houdini_version')}")

        info = await bridge.execute("scene.get_scene_info")
        assert "houdini_version" in str(info), info
        print("[e2e] scene.get_scene_info over HTTP: ok")

        created = await bridge.execute(
            "nodes.create_node",
            {"parent_path": "/obj", "node_type": "geo", "name": "via_http"},
        )
        assert created["node_path"] == "/obj/via_http", created
        listed = await bridge.execute(
            "nodes.find_nodes", {"pattern": "via_http"}
        )
        assert listed["count"] == 1, listed
        print("[e2e] node created and found through the bridge: ok")

        big = await bridge.execute(
            "nodes.list_node_types", {"context": "Sop", "limit": 5000}
        )
        assert big["total_count"] > 200
        print(f"[e2e] large payload ({big['total_count']} types) serialized: ok")

        try:
            await bridge.execute("nodes.create_node", {
                "parent_path": "/obj", "node_type": "not_a_real_type",
            })
        except FXHoudiniError as exc:
            assert "not_a_real_type" in str(exc), exc
            print("[e2e] structured error surfaced through the bridge: ok")
        else:
            raise AssertionError("bad node type did not raise through bridge")

        try:
            await bridge.execute("no.such.command")
        except FXHoudiniError as exc:
            print(f"[e2e] unknown command rejected: ok ({type(exc).__name__})")
        else:
            raise AssertionError("unknown command did not raise")
    finally:
        await bridge.close()


def main() -> int:
    hython = find_hython()
    port = _free_port()
    scripts = str(REPO_ROOT / "houdini" / "scripts" / "python")

    env = os.environ.copy()
    env["FXHOUDINIMCP_PORT"] = str(port)
    server = subprocess.Popen(
        [str(hython), "-c", _SERVER_SNIPPET.format(scripts=scripts)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"[e2e] hython server starting on port {port} (pid {server.pid})")

    try:
        # Wait for the server to answer before testing. Any HTTP status
        # (even 4xx for a GET on the POST-only endpoint) means it is up.
        import urllib.error
        import urllib.request

        deadline = time.time() + 120
        while True:
            if server.poll() is not None:
                output = server.stdout.read() if server.stdout else ""
                raise RuntimeError(f"server exited early:\n{output}")
            if time.time() >= deadline:
                raise RuntimeError("server never became reachable")
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api", timeout=0.5
                )
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.5)

        asyncio.run(_exercise(port))
        print("[e2e] ALL TRANSPORT CHECKS PASSED")
        return 0
    finally:
        server.kill()


if __name__ == "__main__":
    sys.exit(main())
