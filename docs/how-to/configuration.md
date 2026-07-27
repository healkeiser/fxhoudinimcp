# :material-cog:{.scale-in-center} Configuration

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOUDINI_HOST` | `localhost` | Houdini host address |
| `HOUDINI_PORT` | `8100` | Houdini hwebserver port |
| `FXHOUDINIMCP_PORT` | `8100` | Port for the Houdini plugin to listen on |
| `FXHOUDINIMCP_AUTOSTART` | `1` | Set to `0` to disable auto-start |
| `FXHOUDINIMCP_AUTO_LAYOUT` | `1` | Set to `0` to disable automatic node layout |
| `MCP_TRANSPORT` | `stdio` | MCP transport (`stdio` or `streamable-http`) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Auto-Start

The Houdini plugin auto-starts when the UI is ready via `uiready.py`, which
stacks cleanly with other Houdini packages. Startup registers the MCP endpoints,
starts Houdini's `hwebserver` when needed, and verifies that `mcp.health`
answers from the current Houdini process before reporting readiness. Disable
auto-start by setting:

``` shell
export FXHOUDINIMCP_AUTOSTART=0
```

You can still control the server manually from Houdini's **MCP** menu, which
provides Start Server, Stop Server and Server Status.

If an assistant cannot reach Houdini, use `get_houdini_connection_status` to
return structured diagnostics without raising a tool error. If port `8100` is
owned by a different Houdini process, either close that process or set both
`FXHOUDINIMCP_PORT` and `HOUDINI_PORT` to a matching free port.

## Auto-Layout

By default, tools tidy the network editor as they work: node-creation handlers
and workflow tools call `layoutChildren()` on the parent network, and the
server instructions tell assistants to call `layout_children` frequently. This
re-arranges *all* nodes in the affected network — including ones you placed by
hand.

To preserve your manual layouts, disable auto-layout:

``` shell
export FXHOUDINIMCP_AUTO_LAYOUT=0
```

Set it both in the MCP client environment (where `python -m fxhoudinimcp`
runs) and in the Houdini environment (e.g. `houdini.env`), since each process
reads it independently. Inside a running Houdini session you can also toggle
it without restarting:

``` python
hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "0")
```

When disabled, the server instructions tell assistants never to move nodes,
the `layout_children` tool becomes a no-op, and the Houdini-side handlers skip
every automatic `layoutChildren()` call. Newly created nodes keep the position
Houdini assigns at creation time.

## Transport Modes

### stdio (Default)

The AI client spawns the MCP server as a child process. Communication happens over stdin/stdout. This is the simplest setup, no ports or networking required on the MCP side.

### streamable-http

Runs the MCP server as an HTTP endpoint. Useful for remote or shared setups:

``` shell
export MCP_TRANSPORT=streamable-http
python -m fxhoudinimcp
```

## Custom Port

If Houdini's hwebserver is already bound to port 8100, configure a different port:

1. Set `FXHOUDINIMCP_PORT` in your Houdini environment
2. Set `HOUDINI_PORT` in your MCP client config to match
