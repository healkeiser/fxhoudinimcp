"""MCP tool wrappers for higher-level composite workflow operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.  These tools build entire node graphs in a single
call -- complete simulation setups, material creation/assignment, SOP
chain building, and render configuration.
"""

from __future__ import annotations

# Built-in
from typing import Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def setup_pyro_sim(
    ctx: Context,
    source_geo: str = "/obj/geo1/sphere1",
    container: str = "box",
    res_scale: float = 1.0,
    substeps: int = 1,
    name: str = "pyro_sim",
) -> dict:
    """Build a Pyro smoke/fire simulation network from source geometry.

    Args:
        source_geo: Source SOP path.
        container: Container type.
        res_scale: Resolution scale multiplier.
        substeps: DOP substeps.
        name: Top-level geo node name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "workflow.setup_pyro_sim",
        {
            "source_geo": source_geo,
            "container": container,
            "res_scale": res_scale,
            "substeps": substeps,
            "name": name,
        },
    )


@mcp.tool()
async def setup_rbd_sim(
    ctx: Context,
    geo_path: str = "/obj/geo1",
    ground: bool = True,
    pieces_type: str = "voronoi",
    name: str = "rbd_sim",
) -> dict:
    """Build an RBD rigid-body simulation network with fracture and solver.

    Args:
        geo_path: Source geometry object path.
        ground: Add a ground plane.
        pieces_type: Fracture method ("voronoi").
        name: Top-level geo node name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "workflow.setup_rbd_sim",
        {
            "geo_path": geo_path,
            "ground": ground,
            "pieces_type": pieces_type,
            "name": name,
        },
    )


@mcp.tool()
async def setup_flip_sim(
    ctx: Context,
    source_geo: str = "/obj/geo1/sphere1",
    domain: str = "box",
    particle_sep: float = 0.05,
    name: str = "flip_sim",
) -> dict:
    """Build a FLIP fluid simulation network from source geometry.

    Args:
        source_geo: Source SOP path.
        domain: Domain type.
        particle_sep: Particle separation distance.
        name: Top-level geo node name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "workflow.setup_flip_sim",
        {
            "source_geo": source_geo,
            "domain": domain,
            "particle_sep": particle_sep,
            "name": name,
        },
    )


@mcp.tool()
async def setup_vellum_sim(
    ctx: Context,
    geo_path: str = "/obj/geo1",
    sim_type: str = "cloth",
    substeps: int = 5,
    name: str = "vellum_sim",
) -> dict:
    """Build a Vellum simulation network with configure node and solver.

    Args:
        geo_path: Source geometry object path.
        sim_type: Simulation type ("cloth", "hair", "grain", "softbody").
        substeps: Solver substeps.
        name: Top-level geo node name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "workflow.setup_vellum_sim",
        {
            "geo_path": geo_path,
            "sim_type": sim_type,
            "substeps": substeps,
            "name": name,
        },
    )


@mcp.tool()
async def create_material(
    ctx: Context,
    name: str = "material1",
    mat_type: str = "principled",
    base_color: Optional[list] = None,
    roughness: float = 0.5,
    metallic: float = 0.0,
    opacity: float = 1.0,
) -> dict:
    """Create a material in /mat with configurable surface properties.

    Args:
        name: Material node name.
        mat_type: Material type ("principled", "materialx").
        base_color: [R, G, B] base color, 0-1 per channel.
        roughness: Surface roughness, 0-1.
        metallic: Metallic factor, 0-1.
        opacity: Opacity, 0-1.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "name": name,
        "mat_type": mat_type,
        "roughness": roughness,
        "metallic": metallic,
        "opacity": opacity,
    }
    if base_color is not None:
        params["base_color"] = base_color
    return await bridge.execute("workflow.create_material", params)


@mcp.tool()
async def assign_material(
    ctx: Context,
    geo_path: str,
    material_path: str,
) -> dict:
    """Assign a material to a geometry node via a Material SOP.

    Args:
        geo_path: Target geometry node path.
        material_path: Material to assign.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "workflow.assign_material",
        {
            "geo_path": geo_path,
            "material_path": material_path,
        },
    )


@mcp.tool()
async def build_sop_chain(
    ctx: Context,
    parent_path: str = "/obj/geo1",
    steps: Optional[list] = None,
) -> dict:
    """Build a sequential chain of SOP nodes wired together.

    Each step dict: {"type": str, "name": str, "params": dict}.

    Args:
        parent_path: Parent SOP network path.
        steps: List of step dicts defining the chain.
    """
    bridge = _get_bridge(ctx)
    params: dict = {"parent_path": parent_path}
    if steps is not None:
        params["steps"] = steps
    return await bridge.execute("workflow.build_sop_chain", params)


@mcp.tool()
async def setup_render(
    ctx: Context,
    renderer: str = "karma",
    camera: Optional[str] = None,
    output_path: str = "$HIP/render/output.$F4.exr",
    resolution: Optional[list] = None,
    samples: int = 64,
    name: str = "render1",
) -> dict:
    """Set up a render configuration with camera and ROP node.

    Args:
        renderer: Renderer type ("karma", "mantra").
        camera: Camera node path; creates one if omitted.
        output_path: Output image path (supports Houdini variables).
        resolution: [width, height] resolution.
        samples: Render sample count.
        name: ROP node name in /out.
    """
    bridge = _get_bridge(ctx)
    params: dict = {
        "renderer": renderer,
        "output_path": output_path,
        "samples": samples,
        "name": name,
    }
    if camera is not None:
        params["camera"] = camera
    if resolution is not None:
        params["resolution"] = resolution
    return await bridge.execute("workflow.setup_render", params)
