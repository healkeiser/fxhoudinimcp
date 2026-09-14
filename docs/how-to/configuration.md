# :material-cog: Configuration

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOUDINI_HOST` | `localhost` | Houdini host address |
| `HOUDINI_PORT` | `8100` | Houdini hwebserver port |
| `HOUDINI_TIMEOUT` | `FXHOUDINIMCP_TIMEOUT` + 15 | Seconds the MCP client waits for one command before reporting a timeout. Keep it above the plugin's deadline, and raise it alongside any `FXHOUDINIMCP_TIMEOUT_<COMMAND>` you set |
| `FXHOUDINIMCP_PORT` | `8100` | Port for the Houdini plugin to listen on |
| `FXHOUDINIMCP_AUTOSTART` | `1` | Set to `0` to disable auto-start |
| `FXHOUDINIMCP_BIND` | `127.0.0.1` | Address the Houdini plugin binds. Loopback by default; see [Security](#security) before widening it |
| `FXHOUDINIMCP_AUTO_LAYOUT` | `0` | Off: tools never re-arrange existing nodes, new nodes are still placed. Set to `1` to have handlers lay out the parent network after each change |
| `FXHOUDINIMCP_PROJECT_ROOT` | unset | Confine hip, import, export and HDA file operations to this directory tree |
| `FXHOUDINIMCP_TIMEOUT` | `120` | Seconds a command may run before the plugin reports a timeout |
| `FXHOUDINIMCP_TIMEOUT_<COMMAND>` | unset | Per-command override, e.g. `FXHOUDINIMCP_TIMEOUT_TOPS_COOK_TOP_NODE=900` |
| `FXHOUDINIMCP_OUTPUT_GRACE` | `2` | Seconds a clean render or cache write may take to show its file before the tool reports that nothing was written. Raise it when output lands on a slow network share |
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

## Node Placement and Auto-Layout

Two separate things happen to node positions, and one flag controls only one
of them.

**Placement of new nodes always happens.** Every handler that creates a node
gives it a sensible position before returning: a node with inputs lands under
them, a node without inputs takes a free column beside the network, and a
container created at `/obj` is placed next to its siblings. Nothing that
already existed moves. An explicit `position=[x, y]` passed to a create tool
always wins, including `[0, 0]`. Without this, a session run with auto-layout
off used to leave every new node in one unreadable pile at the origin.

**Auto-layout re-arranges the whole network**, and is what
`FXHOUDINIMCP_AUTO_LAYOUT` controls. It is off by default. When on,
node-creation handlers and workflow tools call `layoutChildren()` on the
parent network after they work, and the `layout_children` tool is available
on demand. That moves *all* nodes in the affected network, including ones you
placed by hand, which is why it is opt-in.

To turn it on:

``` shell
export FXHOUDINIMCP_AUTO_LAYOUT=1
```

Set it both in the MCP client environment (where `python -m fxhoudinimcp`
runs) and in the Houdini environment (`houdini.env`, or an entry you add to
the package file's `env` list), since each process reads it independently.
Inside a running Houdini session you can also toggle it without restarting:

``` python
hou.putenv("FXHOUDINIMCP_AUTO_LAYOUT", "1")
```

When off (the default), the server instructions tell assistants never to move nodes,
`layout_children` becomes a no-op, the Houdini-side handlers skip every
automatic `layoutChildren()` call, and only freshly created nodes are placed.
Tools that create nothing (`connect_nodes`, `connect_nodes_batch`,
`set_node_flags`) never move anything in either mode.

## Timeouts

Each command is marshalled onto Houdini's main thread and given a deadline. The
default is 120 seconds. Raise it for everything with `FXHOUDINIMCP_TIMEOUT`, or
for one command with `FXHOUDINIMCP_TIMEOUT_<COMMAND>`, where `<COMMAND>` is the
dotted command name uppercased with dots as underscores:

``` shell
export FXHOUDINIMCP_TIMEOUT_TOPS_COOK_TOP_NODE=900
export FXHOUDINIMCP_TIMEOUT_RENDERING_START_RENDER=1800
```

A command that hits its deadline returns a `TIMEOUT` error naming the exact
variable to raise. These are read by the Houdini process, so they belong in
`houdini.env` or a package-file `env` entry, not the MCP client config.

## Project Root Sandbox

With `FXHOUDINIMCP_PROJECT_ROOT` set, the paths the handlers themselves open,
save, load or install must resolve under that directory: hip files (save, load,
merge), imports, exports, and HDA libraries (install, uninstall, reload,
create). Anything outside is refused with an error that names the root.

``` shell
export FXHOUDINIMCP_PROJECT_ROOT=/projects/showA
```

What it does **not** cover: a file path written into a parameter with
`set_parameter` (a File SOP's `file`, a ROP's output) is evaluated later by the
node, not by the plugin. Checking it would mean inspecting every string
parameter on every set, so the gap is left open and stated rather than
half-closed. `execute_python` and `execute_hscript` are not sandboxed at all.

## Security

Treat a connection to this server as a shell inside your Houdini session.
`execute_python` runs arbitrary code, and there is no authentication,
authorization, per-tool permission model or audit log. The threat model is a
single artist's workstation and an MCP client they trust.

What the plugin does on its own:

- **Binds to loopback.** Nothing on the network reaches the port unless you set
  `FXHOUDINIMCP_BIND` wider on purpose.
- **Refuses browsers.** A web page you have open is also on loopback, and it
  can POST a form-encoded body to `127.0.0.1` without any CORS preflight. Any
  request carrying an `Origin` header is refused with HTTP 403, and so is any
  `Host` that is not a loopback name (DNS rebinding) while the bind is loopback.
- **Confines file operations when asked**, via the project root sandbox above.

What it does not do: inspect parameter values, sandbox code execution, or ask
for confirmation before a change. One undo step per tool call is the recovery
path. If those limits do not fit your situation, run the plugin only on
disposable scenes, or do not run it.

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
