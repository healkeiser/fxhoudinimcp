# :material-home: Home

## fxhoudinimcp

The most comprehensive [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server for [SideFX Houdini](https://www.sidefx.com/).

**198 tools**, **8 resources**, and **9 prompts** serving **31 written workflow guides** out of the box.

Connects AI assistants like Claude directly to Houdini's Python API, enabling natural language control over scene building, simulation setup, rendering, and more.

## Features

| Category | Tools | Description |
|----------|-------|-------------|
| **Graph Intelligence** | 6 | Atomic validated network building, network verification, node doc cards, cook profiling, frame-range cooking with per-frame evidence, cook status |
| **Documentation** | 2 | Full-text search + page retrieval over Houdini's own shipped manual (version-exact) |
| **Scene Management** | 10 | Open, save, import/export, scene info, connection status, undo/redo |
| **Node Operations** | 20 | Create, delete, copy, connect, layout, flags, network boxes, sticky notes, object transforms |
| **Parameters** | 12 | Get/set values in bulk, expressions, keyframes, spare parameters |
| **Geometry (SOPs)** | 14 | Points, prims, attributes, attribute statistics, volume inspection, groups, sampling, nearest-point search |
| **LOPs/USD** | 18 | Stage inspection, prims, layers, composition, variants, lighting |
| **DOPs** | 8 | Simulation info, DOP objects, step/reset, memory usage |
| **PDG/TOPs** | 12 | Cook, work items, failed items and logs, schedulers, dependency graphs |
| **COPs (Copernicus)** | 7 | Image nodes, layers, VDB data |
| **HDAs** | 11 | Create, install, manage Digital Assets, their versions and sections |
| **Animation** | 9 | Keyframes, playbar control, frame range |
| **Rendering** | 9 | Viewport capture, render nodes, settings, render launch |
| **VEX** | 5 | Create/edit wrangles, validate VEX code |
| **Code Execution** | 6 | Python, HScript, expressions, env variables, file references, update mode |
| **Viewport/UI** | 14 | Pane management, viewer context, verified camera and renderer state, screenshots, error detection |
| **Scene Context** | 8 | Network overview, cook chain, selection, scene summary, error analysis |
| **Workflows** | 8 | One-call Pyro/RBD/FLIP/Vellum setup, SOP chains, render config |
| **Materials** | 4 | List, inspect, create materials and shader networks |
| **CHOPs** | 4 | Channel data, CHOP nodes, export channels to parameters |
| **Cache** | 4 | List, inspect, clear, write file caches |
| **Takes** | 4 | List, create, switch takes with parameter overrides |
| **Shelf Tools** | 3 | Find, read and run Houdini's own shelf tools (setups build_network cannot produce) |

## Architecture

```mermaid
flowchart LR
    subgraph Client[" 🤖 AI Client "]
        direction TB
        A1("Claude Desktop")
        A2("Cursor / VS Code")
        A3("Claude Code")
    end

    subgraph MCP[" ⚡ FXHoudini MCP Server "]
        direction TB
        B1("🔧 198 tools")
        B2("📦 8 Resources")
        B3("💬 9 Prompts")
    end

    subgraph Houdini[" 🔶 SideFX Houdini "]
        direction TB
        C1("🌐 hwebserver")
        C2("📡 Dispatcher")
        C3("🎛️ hou.* Handlers")
        C1 --> C2 --> C3
    end

    Client -. "MCP Protocol · stdio" .-> MCP
    MCP -. "HTTP / JSON · port 8100" .-> Houdini

    classDef clientNode fill:transparent,stroke:#6b8cce,stroke-width:1.5px,rx:8,ry:8
    classDef mcpNode fill:transparent,stroke:#5ba67a,stroke-width:1.5px,rx:8,ry:8
    classDef houdiniNode fill:transparent,stroke:#e07840,stroke-width:1.5px,rx:8,ry:8

    class A1,A2,A3 clientNode
    class B1,B2,B3 mcpNode
    class C1,C2,C3 houdiniNode
```

Uses Houdini's built-in `hwebserver`. No custom socket servers, no rpyc. Uses `hdefereval.executeInMainThreadWithResult()` to safely run `hou.*` calls on the main thread.

## How It Works

1. **Houdini Plugin** (`houdini/`): Runs inside Houdini's Python environment. Registers `@hwebserver.apiFunction` endpoints that receive JSON commands. Uses `hdefereval.executeInMainThreadWithResult()` to safely execute `hou.*` calls on the main thread.

2. **MCP Server** (`python/fxhoudinimcp/`): A standalone Python process using FastMCP. Exposes 198 tools, 8 resources, and 9 prompts via the MCP protocol. Forwards tool calls to Houdini over HTTP.

3. **Bridge** (`python/fxhoudinimcp/bridge.py`): Async HTTP client that sends commands to Houdini's hwebserver and deserializes responses. Handles connection errors and timeouts.
