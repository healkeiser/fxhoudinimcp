"""Auto-start FXHoudini-MCP server when Houdini's UI is ready.

This script is sourced by Houdini once at startup, after the UI is
initialised.  Unlike scripts/456.py it stacks correctly with other
packages that also define a uiready.py.

Set FXHOUDINIMCP_AUTOSTART=0 to disable auto-start.
"""

import os

if os.environ.get("FXHOUDINIMCP_AUTOSTART", "1") == "1":
    try:
        import fxhoudinimcp_server.startup

        # wait=False: the readiness poll runs on a worker thread so
        # Houdini's UI is not blocked while the server comes up.
        fxhoudinimcp_server.startup.ensure_running(wait=False)
    except Exception as e:
        print(f"[fxhoudinimcp] Auto-start failed: {e}")
