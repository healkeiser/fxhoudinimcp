You are debugging a Houdini scene.

Problem: {problem_description}

## Systematic debug workflow

1. `get_scene_info` for overall state, then find_error_nodes for everything erroring or warning.
2. `get_node_info` on each error node: full message plus input connection state.
3. `get_parameter_schema` and `get_parameter` to compare values against defaults.
4. Narrow by domain: `get_geometry_info` on the node and its inputs; `get_stage_info` and `list_usd_prims` for USD; `get_simulation_info` and `get_dop_object` for sims.
5. `set_node_flags` to bypass a suspect node and see what changes.
6. `get_expression` on parameters whose references look broken.

## Common causes

- Missing inputs: `connect_nodes`, or a wrong file path.
- Cooking errors: check upstream first, data flows top to bottom.
- Empty output: display flag placement, group names that match nothing, geometry blasted upstream.
- VEX errors: `validate_vex` for compilation; ch()/chi() return 0 silently on a bad path.
- Simulation exploding: reduce timestep/substeps, check collision geometry, inspect with `get_dop_object`.
- Material not showing: material path, assignmaterial prim path, and whether the viewport renderer is Karma CPU or Storm.
- USD composition: `get_usd_layers` and `get_usd_composition` for the layer stack.
- Node type not found: `list_node_types` to confirm the name exists in that context.
- Memory: `get_sim_memory_usage`, and `get_geometry_info` for polygon counts.

{network_housekeeping}
