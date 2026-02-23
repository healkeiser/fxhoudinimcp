"""MCP prompt templates for common Houdini workflows.

These prompts guide AI assistants through multi-step Houdini tasks.
"""

from __future__ import annotations

# Internal
from fxhoudinimcp.server import mcp

# Shared guidelines appended to every workflow prompt.
_NETWORK_HOUSEKEEPING = """
Network housekeeping (ALWAYS follow these):
- Call set_current_network on the parent network you are building in so the
  user can see your work in the network editor. Do this BEFORE you start
  creating nodes, and again whenever you move to a different network level.
- Call layout_children frequently — after every batch of 3-5 new nodes, not
  just at the end. A tidy graph lets the user follow along in real time.
"""


@mcp.prompt()
def procedural_modeling_workflow(
    description: str,
    output_context: str = "/obj",
) -> str:
    """Guide for building a procedural modeling network in SOPs.

    Args:
        description: What geometry to create (e.g. "a rocky terrain with scattered trees")
        output_context: Where to create the geo container
    """
    return f"""You are building procedural geometry in Houdini SOPs.

Goal: {description}
Output context: {output_context}

GOLDEN RULE — NODES OVER VEX (read this FIRST):
Your job is to build SOP *node chains*, NOT to write VEX code.
Think like a Houdini artist: every operation should be a visible node in the
network graph. VEX wrangles are a LAST RESORT for logic that literally no
built-in node can express (e.g. a custom math curve equation).

Before creating ANY node, plan the SOP chain on paper:
  "I need a Box → Bevel → Boolean (with a Circle) → Scatter → Copy to Points"
If your plan has more than one wrangle, STOP and rethink — you're probably
missing a built-in node. Call list_node_types with context="Sop" to check.

SOP nodes you MUST know (use these instead of VEX):
  Primitives:     Box, Sphere, Tube, Torus, Grid, Circle, Line, Curve, Add
  Modeling:       PolyExtrude, PolyBevel, Boolean, Clip, Mirror, Subdivide,
                  Sweep, Revolve, Loft, Skin, PolySplit, EdgeLoop
  Deformation:    Transform, Bend, Twist, Lattice, Peak, Mountain, Soft Transform
  Copy/Instance:  Copy to Points, Copy and Transform
  Scattering:     Scatter, Scatter and Align
  Groups/Filter:  Group Create, Group Expression, Group by Range, Blast, Split,
                  Delete, Dissolve
  Attributes:     Attribute Create, Attribute Randomize, Attribute Rename,
                  Attribute Transfer, Attribute Promote, Measure
  Topology:       Fuse, Clean, Resample, Reverse, Divide, Remesh, PolyReduce
  Utility:        Merge, Switch, Null, Object Merge, Sort, Pack, Unpack
  Loops:          For-Each (block_begin / block_end) — per-piece or per-point
  UV:             UV Unwrap, UV Flatten, UV Project, UV Layout

Anti-patterns (NEVER do these):
  BAD:  Detail wrangle with addpoint() loop → USE: Grid or Scatter SOP
  BAD:  Wrangle with removepoint()         → USE: Blast SOP + group expression
  BAD:  Wrangle setting random attribs     → USE: Attribute Randomize SOP
  BAD:  Wrangle building a box shape       → USE: Box SOP + Transform
  BAD:  Wrangle doing extrusion math       → USE: PolyExtrude SOP
  BAD:  Wrangle doing boolean operations   → USE: Boolean SOP
  BAD:  Wrangle creating copies            → USE: Copy to Points SOP
  BAD:  Hardcoded values in VEX            → USE: set_expression / HScript expr

Example SOP chains (NO VEX needed):
  AC unit:    Box → PolyBevel → Boolean (Circle cutout) → Scatter (vent points)
              → small Grid (vent shape) → Copy to Points
  Table:      Box (top) + Box (leg) → Copy to Points (4 corners) → Merge
  Terrain:    Grid → Mountain → Scatter (trees) → Copy to Points
  Pipe:       Circle → Sweep along Curve → Resample → Fuse
  Window:     Grid → PolyExtrude (inset) → Boolean (panes) → Transform

Workflow:
1. Use get_scene_info to understand the current scene state.
2. Create a Geometry container node in {output_context} using create_node.
3. Plan your SOP chain FIRST — list the nodes you'll use before creating any.
4. Inside the geo node, build the SOP chain:
   - Start with a base shape (box, grid, sphere, etc.)
   - Chain modifier SOPs (transform, bevel, boolean, scatter, copy, etc.)
   - If you catch yourself about to write VEX, STOP and search for a SOP
5. Set the display flag on the final node using set_node_flags.
6. Use get_geometry_info to verify the result.

VEX rules (ONLY when no SOP can do the job):
- After EVERY create_wrangle or set_wrangle_code call, IMMEDIATELY call
  validate_vex to catch compilation errors.
- Channel references: strongly prefer relative paths. Count the hierarchy
  depth from the wrangle to the target node: ../ = one level up, ../../ =
  two levels, etc. The create_wrangle response includes channel_ancestors
  showing what each ../ level resolves to — use it.
  Absolute paths break when nodes are renamed or moved — last resort only.
- Detail-mode wrangles can create geometry from scratch with addpoint() /
  addprim() — they do NOT need input geometry.
- VEX ch()/chi()/chf() return 0 silently when the path is wrong.

Debugging strategy — avoid loops:
- If something doesn't work after 2 attempts, STOP and change strategy:
  1. Call validate_vex to check for VEX compilation errors.
  2. Use execute_python to inspect live values.
  3. Check find_error_nodes for upstream errors.
- Do NOT keep re-running get_geometry_info hoping for different results.
- Do NOT add workarounds without diagnosing the root cause first.

Efficiency tips:
- Use create_spare_parameters (plural) to batch-create all spare parameters in
  one call, with an optional folder_name to group them in a tab.
- Use connect_nodes_batch to wire multiple node pairs in one call.
- Use set_viewport_direction to switch to front/top/perspective views.

General tips:
- Check node cooking errors with get_node_info after creating nodes
- Use list_node_types with context="Sop" to discover available node types
- Paginate point data with get_points (start/count) for large geometry
- Use get_parameter_schema to understand node parameters before setting them
{_NETWORK_HOUSEKEEPING}"""


@mcp.prompt()
def usd_scene_assembly(
    scene_description: str,
) -> str:
    """Guide for building a USD scene in Houdini's LOPs/Solaris.

    Args:
        scene_description: Description of the USD scene to build
    """
    return f"""You are building a USD scene in Houdini's Solaris (LOPs).

Goal: {scene_description}

Viewport-first lookdev (IMPORTANT — read before rendering):
- During lookdev and testing, NEVER render to disk. Instead, switch the
  viewport's Hydra delegate to preview materials and lighting in real time.
- Call set_viewport_renderer("Karma CPU") or set_viewport_renderer("Storm")
  to enable a live Hydra render in the viewport. Use "GL" for fast wireframe.
- Only use start_render / create_render_node for final production renders
  that the user explicitly requests to write to disk.
- Use capture_screenshot to grab what the viewport currently shows — this is
  how you check your work during lookdev, not by writing full renders.

Workflow:
1. Use get_scene_info to check the current state.
2. Navigate to the /stage context using set_current_network.
3. Set up the viewport for lookdev:
   - Call set_viewport_renderer("Karma CPU") for material/lighting preview
   - Call set_viewport_camera if a camera exists
4. Build the LOP network:
   - Use create_lop_node for common operations (Camera, Light, Xform)
   - For geometry references, use "Reference" or "Sublayer" LOP nodes
   - For materials: create a "materiallibrary" LOP, build shaders inside
     it (karmamaterialbuilder, mtlxstandard_surface, etc.), then assign
     with an "assignmaterial" LOP (see Material setup section below)
5. Connect nodes in a linear chain (LOPs are typically top-to-bottom).
   Use connect_nodes_batch to wire multiple node pairs at once.
6. Check your work visually with capture_screenshot (viewport preview).
7. Use get_stage_info to inspect the resulting USD stage.
8. Use list_usd_prims to verify the prim hierarchy.
9. Use get_usd_materials to verify material bindings.

Material setup in LOPs (CRITICAL — materials live in proper containers):
- Do NOT create materials in /mat for LOPs workflows. Materials must be
  created inside USD-native container LOP nodes in the /stage network.
- Use create_lop_node to create a "materiallibrary" LOP node in /stage.
  This is the Material Library node — the proper USD container for materials.
- Inside the materiallibrary node, create the shader using the appropriate
  builder for your renderer:
    - Karma: create a "karmamaterialbuilder" node inside the materiallibrary
    - MaterialX: create a "mtlxstandard_surface" inside a material builder
    - USD Preview Surface: use "usdpreviewsurface" for portable materials
- To assign materials to geometry, create an "assignmaterial" LOP node
  downstream in the /stage network. Set the geometry prim path and the
  material prim path.
- Use get_parameter_schema on material nodes to discover available params
  before guessing names.
- For Karma using SOP Cd (vertex color), set basecolor_usePointColor=1 on
  a principledshader. This reads the displayColor primvar automatically.

Lighting tips:
- Use create_light for individual lights (dome, distant, rect, sphere, disk, cylinder).
- Use create_light_rig with a preset ("outdoor", "three_point", "studio", "hdri")
  for a quick multi-light setup.
- Light intensity parameters use the prefix xn__inputsintensity_i0b (not just
  "intensity") in Houdini 20+. Use get_parameter_schema to discover exact names.
- Set exposure (not raw intensity) for easier light balancing.
- After adding/changing lights, use capture_screenshot to check the viewport
  preview — do NOT render to disk just to see the result.

Key concepts:
- LOPs build a USD stage layer by layer
- Each LOP node adds its edit to the active layer
- Use get_usd_layers to understand the layer stack
- Use get_usd_composition to inspect references, payloads, and variants
- The display flag determines which node's output is viewed
{_NETWORK_HOUSEKEEPING}"""


@mcp.prompt()
def simulation_setup(
    sim_type: str,
    description: str = "",
) -> str:
    """Guide for setting up a dynamics simulation.

    Args:
        sim_type: Type of simulation (pyro, flip, rbd, vellum, pop)
        description: Additional context about the simulation
    """
    return f"""You are setting up a {sim_type} simulation in Houdini.

Goal: {description or f"Create a {sim_type} simulation"}

Workflow:
1. Start with source geometry in SOPs (create a geo node with the source shape).
2. Create a DOP network for the simulation:
   - For Pyro: use Pyro Solver, Smoke Object, source nodes
   - For FLIP: use FLIP Solver, FLIP Object, particle source
   - For RBD: use Bullet/RBD Solver, RBD Packed Object
   - For Vellum: use Vellum Solver, Vellum Source
   - For POP: use POP Solver, POP Source
3. Wire the source geometry into the DOP network.
4. Use get_simulation_info to check the simulation state.
5. Use step_simulation to advance and test.
6. Use get_dop_object to inspect simulation objects.
7. Adjust solver parameters with set_parameter.

Tips:
- Verify geometry source with get_geometry_info before simulation
- Use reset_simulation when changing fundamental parameters
- Check get_sim_memory_usage for large simulations
- Use list_node_types with context="Dop" to discover available node types
- Build source geometry with SOP node chains (Box, Grid, Sphere, Scatter,
  Boolean, PolyExtrude, Copy to Points, etc.) — NOT VEX wrangles.
  Wrangles are a last resort for logic no built-in SOP can express.
  Plan your node chain before building. Call list_node_types to discover SOPs.
{_NETWORK_HOUSEKEEPING}"""


@mcp.prompt()
def pdg_pipeline(
    task_description: str,
) -> str:
    """Guide for building a PDG/TOPs pipeline.

    Args:
        task_description: What the pipeline should accomplish
    """
    return f"""You are building a PDG/TOPs pipeline in Houdini.

Goal: {task_description}

Workflow:
1. Navigate to the /tasks context.
2. Create TOP nodes to define the dependency graph:
   - File Pattern, HDA Processor, ROP Fetch, Python Script
   - Partitioners for grouping work items
   - Wait for All nodes for synchronization
3. Wire the dependency chain.
4. Use generate_static_items to preview work items without cooking.
5. Use get_work_item_states to check the pipeline state.
6. Use cook_top_node to execute the pipeline.
7. Monitor with get_work_item_info during cooking.

Tips:
- Use list_node_types with context="Top" to discover available node types
- Check get_top_scheduler_info for scheduler configuration
- Use dirty_work_items to regenerate items after parameter changes
{_NETWORK_HOUSEKEEPING}"""


@mcp.prompt()
def hda_development(
    asset_description: str,
    context: str = "Sop",
) -> str:
    """Guide for creating a Houdini Digital Asset.

    Args:
        asset_description: What the HDA should do
        context: Node context for the HDA (Sop, Lop, Object, etc.)
    """
    return f"""You are developing a Houdini Digital Asset (HDA).

Goal: {asset_description}
Context: {context}

Workflow:
1. Create a subnet node to hold the internal logic.
2. Build the internal network with the required functionality.
3. Promote internal parameters to the subnet level using create_spare_parameters
   (plural, batch tool) with a folder_name to group them in a tab.
4. Test the network thoroughly using get_geometry_info or get_stage_info.
5. Use create_hda to convert the subnet into an HDA.
6. Use get_hda_info to verify the definition.
7. Use get_hda_sections to inspect the asset contents.
8. Use set_hda_section_content to add help documentation.

Tips:
- Use get_parameter_schema on existing nodes to understand parameter types
- Use list_node_types to verify the HDA type name is unique
- Test with different inputs before finalizing the HDA
- Use update_hda to save changes after modifications
- Build internal logic with SOP node chains (Box, Grid, Scatter, Boolean,
  PolyExtrude, Copy to Points, Blast, Transform, etc.) — NOT VEX wrangles.
  A network of visible nodes is far more user-friendly and debuggable inside
  an HDA than opaque wrangles. Plan the node chain before building.
  Wrangles are a last resort for logic no built-in SOP can express.
{_NETWORK_HOUSEKEEPING}"""


@mcp.prompt()
def debug_scene(
    problem_description: str = "general issues",
) -> str:
    """Systematic approach to debugging a Houdini scene.

    Args:
        problem_description: What problem the user is experiencing
    """
    return f"""You are debugging a Houdini scene.

Problem: {problem_description}

Systematic debug workflow:
1. get_scene_info -- Understand the overall scene state.
2. find_error_nodes -- Find all nodes with errors or warnings.
3. For each error node, use get_node_info to get the full error message.
4. Check the node's inputs are connected: get_node_info shows connection state.
5. Check parameter values: get_parameter_schema and get_parameter.
6. If geometry issues: get_geometry_info on the problematic node and its inputs.
7. If USD issues: get_stage_info and list_usd_prims.
8. If simulation issues: get_simulation_info and get_dop_object.
9. Try setting bypass flag on suspected nodes: set_node_flags.
10. Check expressions: get_expression on parameters with broken references.

Common issues:
- Missing inputs: connect_nodes or check file paths
- Wrong parameter values: compare with get_parameter_schema defaults
- Cooking errors: check upstream nodes first (data flows top to bottom)
- Memory issues: get_sim_memory_usage, get_geometry_info for polygon counts
{_NETWORK_HOUSEKEEPING}"""
