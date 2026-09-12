# :material-wrench:{.scale-in-center} Tools

## Overview

fxhoudinimcp exposes **198 tools** across **23 categories**, covering every major Houdini context.

Once connected, your AI assistant can:

``` text
"Create a procedural rock generator with mountain displacement"
"Set up a Pyro simulation with a sphere source"
"Build a USD scene with a camera, dome light, and ground plane"
"Create an HDA from the selected subnet"
"Debug why my scene has cooking errors"
"Undo that last change"
```

Every tool call is one undo step, however many nodes it touched. A bad
`build_network` is one `undo` away rather than a node-by-node clean-up.

## Categories

### Graph Intelligence (6 tools)

Senior-artist tooling: `build_network` builds whole validated networks
atomically (with `dry_run=True` plan checking and did-you-mean corrections),
`verify_network` inspects every node's errors and cooked geometry,
`get_node_card` serves version-exact node documentation from the running
Houdini, `find_expensive_nodes` profiles cook costs, `cook_frame_range` cooks
a range and reports per-frame evidence, and `get_cook_status` reports where a
cook stands.

### Documentation (2 tools)

`search_help` runs full-text search over the documentation Houdini ships in
`$HFS/houdini/help`: node reference, VEX, expressions, HOM, and SideFX's own
workflow manuals (Pyro look-dev, Vellum tips, destruction constraints, Solaris,
TOPs, Copernicus and the rest). Always version-exact, no network needed.
`get_help_page` fetches a full page. On builds without local help, both degrade
into a clear error pointing at `get_node_card` and the online docs.

### Scene Management (10 tools)

Open, save, import/export, query scene information, inspect the Houdini
connection status, and `undo` / `redo`. When `FXHOUDINIMCP_PROJECT_ROOT` is
set, the file operations here are confined to that directory tree (see
[Configuration](configuration.md#project-root-sandbox)).

### Node Operations (20 tools)

Create, delete, copy, rename, connect and disconnect nodes, reorder inputs,
manage flags, colours and positions. `create_network_box` and
`create_sticky_note` let a built graph document itself, and
`set_object_transform` sets translate, rotate, scale and parent on an object
in one call.

### Parameters (12 tools)

Get/set values one at a time or in bulk, expressions, channel references
between parameters, keyframes, locking, reverting to defaults, and spare
parameters.

### Geometry / SOPs (14 tools)

Read points, primitives, attributes and their statistics, volumes, groups and
group membership, bounding boxes, intrinsics. Sample geometry and run
nearest-point searches.

### LOPs/USD (18 tools)

Stage inspection, USD prims and attributes, layers, composition arcs, variants,
materials, lights and light rigs.

### DOPs (8 tools)

Query simulation info, DOP objects, fields and relationships, step/reset
simulations, and check memory usage.

### PDG/TOPs (12 tools)

Cook tasks, generate static items, inspect work items and their states,
`get_failed_work_items` with the tail of each log, `get_top_logs` for a node
or one work item, schedulers and dependency graphs.

### COPs / Copernicus (7 tools)

Image nodes, layers, and VDB data access.

### HDAs (11 tools)

Create, install, uninstall, reload and update Houdini Digital Assets, list
every installed version of an asset's type, and read or write their sections.

### Animation (9 tools)

Set keyframes, control the playbar, and manage frame and playback ranges.

### Rendering (9 tools)

Viewport and quad-view capture, network editor rendering, render node
management, render settings, launching and monitoring renders.

### VEX (5 tools)

Create/edit wrangle nodes, read wrangle code, build VEX expressions, and
validate VEX code before it cooks.

### Code Execution (6 tools)

Execute Python and HScript, evaluate expressions, read environment variables,
list every file the scene references (and which are missing), and switch the
cook update mode to `manual` for the duration of a heavy edit.

### Viewport/UI (14 tools)

Pane management, viewer context, verified camera and renderer state,
screenshots, and error detection.

### Scene Context (8 tools)

Network overview, cook chains, selection state, scene summaries, and error
analysis.

### Workflows (8 tools)

One-call Pyro, RBD, FLIP, and Vellum simulation setup. SOP chains, render
configuration, material creation and assignment.

### Materials (4 tools)

List, inspect, and create materials and shader networks.

### CHOPs (4 tools)

Channel data access, CHOP node management, and channel-to-parameter export.

### Cache (4 tools)

List, inspect, clear, and write file caches.

### Takes (4 tools)

List, create, and switch takes with parameter overrides.

### Shelf Tools (3 tools)

Find, read and run Houdini's own shelf tools, for the setups `build_network`
cannot produce because SideFX builds them from a script (the ocean procedural,
for one).
