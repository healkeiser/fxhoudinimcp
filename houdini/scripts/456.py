"""Auto-start FXHoudini-MCP server on scene load.

This script runs every time a scene is loaded in Houdini.
Set FXHOUDINIMCP_AUTOSTART=0 to disable auto-start.
"""

# Built-in
import os

if os.environ.get("FXHOUDINIMCP_AUTOSTART", "1") == "1":
    try:
        import fxhoudinimcp_server.startup

        fxhoudinimcp_server.startup.ensure_running()
    except Exception as e:
        print(f"[fxhoudinimcp] Auto-start failed: {e}")
