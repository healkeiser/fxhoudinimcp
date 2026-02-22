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
    """Set up a complete Pyro smoke/fire simulation with solver, source, container, and cache.

    Builds a full Pyro simulation network in one call: creates a geometry
    node at /obj containing a DOP Network with a Pyro solver, smoke object,
    source volume, and resize container.  An Object Merge SOP references
    the source geometry, and a File Cache SOP is added for the output.

    Args:
        ctx: MCP context.
        source_geo: Path to the source geometry SOP to drive the simulation
                    (e.g. "/obj/geo1/sphere1").
        container: Container type hint (default: "box").
        res_scale: Resolution scale multiplier for the simulation (default: 1.0).
        substeps: Number of DOP substeps (default: 1).
        name: Name for the top-level geometry node (default: "pyro_sim").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("workflow.setup_pyro_sim", {
        "source_geo": source_geo,
        "container": container,
        "res_scale": res_scale,
        "substeps": substeps,
        "name": name,
    })


@mcp.tool()
async def setup_rbd_sim(
    ctx: Context,
    geo_path: str = "/obj/geo1",
    ground: bool = True,
    pieces_type: str = "voronoi",
    name: str = "rbd_sim",
) -> dict:
    """Set up a complete RBD rigid-body simulation with solver, fracture, ground, and cache.

    Builds a full RBD simulation network: creates a geometry node with a
    DOP Network containing an RBD Bullet Solver, optional Voronoi fracture,
    optional ground plane, and a File Cache for the output.

    Args:
        ctx: MCP context.
        geo_path: Path to the source geometry object (e.g. "/obj/geo1").
        ground: If True, add a ground plane to the simulation (default: True).
        pieces_type: Fracture method -- "voronoi" adds a Voronoi Fracture SOP
                     (default: "voronoi").
        name: Name for the top-level geometry node (default: "rbd_sim").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("workflow.setup_rbd_sim", {
        "geo_path": geo_path,
        "ground": ground,
        "pieces_type": pieces_type,
        "name": name,
    })


@mcp.tool()
async def setup_flip_sim(
    ctx: Context,
    source_geo: str = "/obj/geo1/sphere1",
    domain: str = "box",
    particle_sep: float = 0.05,
    name: str = "flip_sim",
) -> dict:
    """Set up a complete FLIP fluid simulation with solver, source, domain, and cache.

    Builds a full FLIP simulation network: creates a geometry node with a
    DOP Network containing a FLIP solver, FLIP object, FLIP source, and
    a tank/domain.  An Object Merge SOP references the source geometry,
    and a File Cache SOP is added for the output.

    Args:
        ctx: MCP context.
        source_geo: Path to the source geometry SOP (e.g. "/obj/geo1/sphere1").
        domain: Domain type hint (default: "box").
        particle_sep: Particle separation distance (default: 0.05).
        name: Name for the top-level geometry node (default: "flip_sim").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("workflow.setup_flip_sim", {
        "source_geo": source_geo,
        "domain": domain,
        "particle_sep": particle_sep,
        "name": name,
    })


@mcp.tool()
async def setup_vellum_sim(
    ctx: Context,
    geo_path: str = "/obj/geo1",
    sim_type: str = "cloth",
    substeps: int = 5,
    name: str = "vellum_sim",
) -> dict:
    """Set up a complete Vellum simulation with configure node, solver, and cache.

    Builds a full Vellum simulation network: creates a geometry node with
    a Vellum Configure node (cloth/hair/grain/softbody), Vellum Solver,
    Object Merge for source geometry, and a File Cache SOP.

    Args:
        ctx: MCP context.
        geo_path: Path to the source geometry object (e.g. "/obj/geo1").
        sim_type: Simulation type -- "cloth", "hair", "grain", or "softbody"
                  (default: "cloth").
        substeps: Number of solver substeps (default: 5).
        name: Name for the top-level geometry node (default: "vellum_sim").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("workflow.setup_vellum_sim", {
        "geo_path": geo_path,
        "sim_type": sim_type,
        "substeps": substeps,
        "name": name,
    })


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
    """Create a material/shader in the /mat context with configurable properties.

    Creates either a Principled Shader or MaterialX Standard Surface in
    the /mat network, and sets base color, roughness, metallic, and opacity
    parameters.

    Args:
        ctx: MCP context.
        name: Name for the material node (default: "material1").
        mat_type: Material type -- "principled" or "materialx" (default: "principled").
        base_color: Optional [R, G, B] base color, each 0.0 to 1.0
                    (e.g. [1.0, 0.0, 0.0] for red).
        roughness: Surface roughness, 0.0 (mirror) to 1.0 (diffuse) (default: 0.5).
        metallic: Metallic factor, 0.0 (dielectric) to 1.0 (metal) (default: 0.0).
        opacity: Opacity, 0.0 (transparent) to 1.0 (opaque) (default: 1.0).
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
    """Assign a material to a geometry node by creating a Material SOP.

    Creates a Material SOP at the end of the SOP chain inside the target
    geometry node, sets the material path parameter, wires it after the
    last displayed SOP, and sets the display flag on the new Material SOP.

    Args:
        ctx: MCP context.
        geo_path: Path to the geometry node (e.g. "/obj/geo1").
        material_path: Path to the material to assign (e.g. "/mat/material1").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("workflow.assign_material", {
        "geo_path": geo_path,
        "material_path": material_path,
    })


@mcp.tool()
async def build_sop_chain(
    ctx: Context,
    parent_path: str = "/obj/geo1",
    steps: Optional[list] = None,
) -> dict:
    """Build a sequential chain of SOP nodes, wired together automatically.

    Creates each node specified in the steps list, wires them sequentially
    (output 0 to input 0), sets optional parameters, and sets the display
    flag on the last node.

    Each step is a dict with keys:
    - "type" (str, required): Node type to create (e.g. "box", "mountain").
    - "name" (str, optional): Explicit node name.
    - "params" (dict, optional): Parameter name/value pairs to set.

    Example steps: [{"type": "box"}, {"type": "mountain", "params": {"height": 0.5}},
                    {"type": "null", "name": "OUT"}]

    Args:
        ctx: MCP context.
        parent_path: Path to the parent SOP network (default: "/obj/geo1").
        steps: List of step dicts describing the node chain.
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
    """Set up a complete render configuration with camera and ROP node.

    Creates a camera (if none specified), a ROP node in /out (Karma or
    Mantra), and configures the output path, resolution, sample count,
    and camera assignment.

    Args:
        ctx: MCP context.
        renderer: Renderer to use -- "karma" or "mantra" (default: "karma").
        camera: Path to an existing camera node. If omitted, creates a new
                camera at /obj/render_cam.
        output_path: Output image file path, supports Houdini variables
                     (default: "$HIP/render/output.$F4.exr").
        resolution: [width, height] resolution (default: [1920, 1080]).
        samples: Number of render samples (default: 64).
        name: Name for the ROP node in /out (default: "render1").
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
