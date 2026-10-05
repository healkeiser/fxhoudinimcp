# :material-cog: Configuration

## Environment Variables

--8<-- "README.md:environment"

## Auto-Start

The plugin starts when Houdini's UI is ready (through `uiready.py`, which stacks with other packages) and reports ready once `mcp.health` answers from that Houdini process. `FXHOUDINIMCP_AUTOSTART=0` turns this off; the **MCP** menu still starts and stops the server.

## Node Placement and Auto-Layout

New nodes are always placed: under their inputs, or in a free column when they have none. Nothing that already exists moves, and an explicit `position=[x, y]` always wins.

`FXHOUDINIMCP_AUTO_LAYOUT=1` also re-lays-out the whole network after each change, moving nodes you placed by hand, which is why it is off by default. Both processes read it, so set it in the MCP client's environment and in the package file. In a running Houdini, `hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "1")` toggles it without a restart.

## Timeouts

A command gets 120 seconds (`FXHOUDINIMCP_TIMEOUT`). Override one command with `FXHOUDINIMCP_TIMEOUT_<COMMAND>`, the dotted name uppercased with dots as underscores:

``` shell
FXHOUDINIMCP_TIMEOUT_TOPS_COOK_TOP_NODE=900
FXHOUDINIMCP_TIMEOUT_RENDERING_START_RENDER=1800
```

`write_cache`, `start_render` and `press_button` have no deadline: they show Houdini's progress dialog and are cancelled from there. `FXHOUDINIMCP_TIMEOUT` does not reach them; their own variable puts one back.

Houdini reads these, so they go in the package file. A command that times out names the variable to raise. The client waits for the plugin's deadline plus 15 seconds, unless `HOUDINI_TIMEOUT` says otherwise. Raise it to match a longer per-command override.

## Ports and Several Sessions

The plugin takes port 8100, or the next free one when another Houdini holds it. The client scans 8100-8115 and connects to the lowest that answers. `get_houdini_connection_status` lists every session and `connect_houdini(port)` switches. Setting `HOUDINI_PORT` pins one port and switches the scan off. If you change `FXHOUDINIMCP_PORT`, set `HOUDINI_PORT` to match.

## Transport

`stdio` (the default): the AI client starts the server as a child process. `MCP_TRANSPORT=streamable-http` runs it as an HTTP endpoint instead, for remote or shared setups.

## Security

--8<-- "README.md:security"
