"""MCP prompt templates for common Houdini workflows.

These prompts guide AI assistants through multi-step Houdini tasks.
"""

from __future__ import annotations

# Internal
from fxhoudinimcp.server import mcp


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

Workflow:
1. Use get_scene_info to understand the current scene state.
2. Create a Geometry container node in {output_context} using create_node.
3. Inside the geo node, build a SOP network:
   - Start with a base shape (box, grid, sphere, etc.)
   - Chain modifier nodes (transform, mountain, scatter, etc.)
   - Use Attribute Wrangles for custom VEX when needed (create_wrangle tool)
   - For complex logic, prefer VEX wrangles over Python SOPs
4. Set the display flag on the final node using set_node_flags.
5. Use get_geometry_info to verify the result.
6. Use layout_children to clean up the network.

Tips:
- Check node cooking errors with get_node_info after creating nodes
- Use list_node_types with context="Sop" to discover available node types
- Paginate point data with get_points (start/count) for large geometry
- Use get_parameter_schema to understand node parameters before setting them
"""


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

Workflow:
1. Use get_scene_info to check the current state.
2. Navigate to the /stage context.
3. Build the LOP network:
   - Use create_lop_node for common operations (Camera, Light, Material, Xform)
   - For geometry references, use "Reference" or "Sublayer" LOP nodes
   - For materials, use MaterialX or Karma material networks
4. Connect nodes in a linear chain (LOPs are typically top-to-bottom).
5. Use get_stage_info to inspect the resulting USD stage.
6. Use list_usd_prims to verify the prim hierarchy.
7. Use get_usd_materials to verify material bindings.

Key concepts:
- LOPs build a USD stage layer by layer
- Each LOP node adds its edit to the active layer
- Use get_usd_layers to understand the layer stack
- Use get_usd_composition to inspect references, payloads, and variants
- The display flag determines which node's output is viewed
"""


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
"""


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
"""


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
3. Promote internal parameters to the subnet level using create_spare_parameter.
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
"""


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
"""
