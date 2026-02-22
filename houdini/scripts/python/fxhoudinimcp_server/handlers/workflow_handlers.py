"""Higher-level composite workflow handlers for FXHoudini-MCP.

Provides tools that build entire node graphs in a single call --
complete simulation setups, material creation/assignment, SOP chain
building, and render configuration.
"""

from __future__ import annotations

# Built-in
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _ensure_obj_context() -> hou.Node:
    """Return the /obj context node."""
    obj = hou.node("/obj")
    if obj is None:
        raise ValueError("Cannot find /obj context")
    return obj


def _ensure_mat_context() -> hou.Node:
    """Return the /mat context node, creating it if necessary."""
    mat = hou.node("/mat")
    if mat is None:
        mat = hou.node("/").createNode("matnet", "mat")
        print("[workflow] Created /mat context")
    return mat


def _ensure_out_context() -> hou.Node:
    """Return the /out context node."""
    out = hou.node("/out")
    if out is None:
        raise ValueError("Cannot find /out context")
    return out


def _set_parm_safe(node: hou.Node, parm_name: str, value: Any) -> bool:
    """Set a parameter value if the parameter exists. Returns True on success."""
    parm = node.parm(parm_name)
    if parm is not None:
        try:
            parm.set(value)
            return True
        except Exception as e:
            print(f"[workflow] Warning: could not set {parm_name}={value} on {node.path()}: {e}")
            return False
    return False


###### workflow.setup_pyro_sim

def _setup_pyro_sim(
    source_geo: str = "/obj/geo1/sphere1",
    container: str = "box",
    res_scale: float = 1.0,
    substeps: int = 1,
    name: str = "pyro_sim",
    **_: Any,
) -> dict:
    """Build a complete Pyro smoke/fire simulation network.

    Creates a geometry node with a DOP Network containing a Pyro solver,
    smoke object, source volume, and resize container.  Optionally merges
    source geometry and adds a File Cache for the output.

    Args:
        source_geo: Path to the source geometry SOP to drive the simulation.
        container: Container type hint (reserved for future use).
        res_scale: Resolution scale multiplier for the simulation.
        substeps: Number of DOP substeps.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    all_nodes: list[str] = []

    # -- Step 1: Create top-level geo container
    print(f"[workflow] Creating geo node '{name}' under /obj")
    geo = obj.createNode("geo", name)
    # Remove default children
    for child in geo.children():
        child.destroy()
    all_nodes.append(geo.path())

    # -- Step 2: Create DOP Network inside the geo
    print("[workflow] Creating DOP Network inside geo")
    dopnet = geo.createNode("dopnet", "dopnet1")
    all_nodes.append(dopnet.path())

    # -- Step 3: Create Pyro solver inside DOPnet
    print("[workflow] Creating pyrosolver DOP")
    try:
        pyrosolver = dopnet.createNode("pyrosolver", "pyrosolver1")
    except hou.OperationFailed:
        pyrosolver = dopnet.createNode("pyrosolver::2.0", "pyrosolver1")
    all_nodes.append(pyrosolver.path())

    # -- Step 4: Create smoke object
    print("[workflow] Creating smokeobject DOP")
    try:
        smokeobj = dopnet.createNode("smokeobject", "smokeobject1")
    except hou.OperationFailed:
        smokeobj = dopnet.createNode("smokeconfigureobject", "smokeobject1")
    all_nodes.append(smokeobj.path())

    # -- Step 5: Create source volume
    print("[workflow] Creating source volume DOP")
    try:
        source_vol = dopnet.createNode("sourcevolume", "source_volume1")
        all_nodes.append(source_vol.path())
    except hou.OperationFailed:
        print("[workflow] Warning: sourcevolume not available, skipping")
        source_vol = None

    # -- Step 6: Create resize container
    print("[workflow] Creating resize container DOP")
    try:
        resize = dopnet.createNode("gasresizefluiddynamic", "resize_container1")
        all_nodes.append(resize.path())
    except hou.OperationFailed:
        print("[workflow] Warning: gasresizefluiddynamic not available, skipping")
        resize = None

    # -- Step 7: Wire solver chain
    print("[workflow] Wiring DOP solver chain")
    try:
        if source_vol is not None:
            pyrosolver.setInput(0, smokeobj, 0)
            if resize is not None:
                resize.setInput(0, pyrosolver, 0)
        else:
            pyrosolver.setInput(0, smokeobj, 0)
    except Exception as e:
        print(f"[workflow] Warning: Could not auto-wire DOP chain: {e}")

    # Set substeps
    _set_parm_safe(dopnet, "substep", substeps)

    # -- Step 8: Object Merge for source geometry
    print(f"[workflow] Creating Object Merge for source: {source_geo}")
    objmerge = geo.createNode("object_merge", "source_geo")
    _set_parm_safe(objmerge, "objpath1", source_geo)
    all_nodes.append(objmerge.path())

    # Check if source exists
    if hou.node(source_geo) is not None:
        print(f"[workflow] Source geometry found at {source_geo}")
    else:
        print(f"[workflow] Warning: source geometry '{source_geo}' not found -- Object Merge created but path may need updating")

    # -- Step 9: DOP Import for output
    print("[workflow] Creating DOP Import SOP")
    dopimport = geo.createNode("dopimport", "dop_import1")
    _set_parm_safe(dopimport, "doppath", dopnet.path())
    all_nodes.append(dopimport.path())

    # -- Step 10: File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    filecache.setInput(0, dopimport, 0)
    all_nodes.append(filecache.path())

    # Set display/render flags
    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    # -- Step 11: Layout
    print("[workflow] Laying out nodes")
    geo.layoutChildren()
    dopnet.layoutChildren()

    print(f"[workflow] Pyro simulation '{name}' setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "dop_path": dopnet.path(),
        "cache_path": filecache.path(),
        "all_nodes": all_nodes,
    }


###### workflow.setup_rbd_sim

def _setup_rbd_sim(
    geo_path: str = "/obj/geo1",
    ground: bool = True,
    pieces_type: str = "voronoi",
    name: str = "rbd_sim",
    **_: Any,
) -> dict:
    """Build a complete RBD (rigid body dynamics) simulation network.

    Creates a geometry node with a DOP Network, RBD solver, optional
    voronoi fracture, optional ground plane, and a File Cache output.

    Args:
        geo_path: Path to the source geometry object.
        ground: If True, add a ground plane to the simulation.
        pieces_type: Fracture method -- "voronoi" adds a Voronoi Fracture SOP.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    all_nodes: list[str] = []

    # -- Step 1: Create geo container
    print(f"[workflow] Creating geo node '{name}' under /obj")
    geo = obj.createNode("geo", name)
    for child in geo.children():
        child.destroy()
    all_nodes.append(geo.path())

    # -- Step 2: Object Merge source
    print(f"[workflow] Creating Object Merge for source: {geo_path}")
    objmerge = geo.createNode("object_merge", "source_geo")
    _set_parm_safe(objmerge, "objpath1", geo_path)
    all_nodes.append(objmerge.path())
    last_sop = objmerge

    # -- Step 3: Optional Voronoi Fracture
    if pieces_type == "voronoi":
        print("[workflow] Creating Voronoi Fracture SOP")
        try:
            voronoi = geo.createNode("voronoifracture", "voronoi_fracture1")
            voronoi.setInput(0, last_sop, 0)
            all_nodes.append(voronoi.path())
            last_sop = voronoi
        except hou.OperationFailed:
            print("[workflow] Warning: voronoifracture not available, trying boolean fracture")
            try:
                voronoi = geo.createNode("boolean::2.0", "fracture1")
                voronoi.setInput(0, last_sop, 0)
                all_nodes.append(voronoi.path())
                last_sop = voronoi
            except hou.OperationFailed:
                print("[workflow] Warning: fracture node not available, skipping fracture step")

    # -- Step 4: Create DOP Network
    print("[workflow] Creating DOP Network")
    dopnet = geo.createNode("dopnet", "dopnet1")
    all_nodes.append(dopnet.path())

    # -- Step 5: Create RBD solver inside DOPnet
    print("[workflow] Creating RBD Bullet Solver DOP")
    try:
        rbdsolver = dopnet.createNode("rbdbulletsolver", "rbdsolver1")
    except hou.OperationFailed:
        try:
            rbdsolver = dopnet.createNode("rbdsolver", "rbdsolver1")
        except hou.OperationFailed:
            rbdsolver = dopnet.createNode("bulletrbdsolver", "rbdsolver1")
    all_nodes.append(rbdsolver.path())

    # -- Step 6: Create RBD packed object
    print("[workflow] Creating RBD Packed Object DOP")
    try:
        rbdobj = dopnet.createNode("rbdpackedobject", "rbdobject1")
        all_nodes.append(rbdobj.path())
        rbdsolver.setInput(0, rbdobj, 0)
    except hou.OperationFailed:
        print("[workflow] Warning: rbdpackedobject not available")
        rbdobj = None

    # -- Step 7: Ground plane
    if ground:
        print("[workflow] Creating Ground Plane DOP")
        try:
            groundplane = dopnet.createNode("groundplane", "groundplane1")
            all_nodes.append(groundplane.path())
        except hou.OperationFailed:
            print("[workflow] Warning: groundplane DOP not available, creating static ground in SOPs")
            try:
                ground_sop = geo.createNode("grid", "ground_plane")
                _set_parm_safe(ground_sop, "sizex", 20.0)
                _set_parm_safe(ground_sop, "sizey", 20.0)
                all_nodes.append(ground_sop.path())
            except Exception as e:
                print(f"[workflow] Warning: could not create ground: {e}")

    # -- Step 8: DOP Import
    print("[workflow] Creating DOP Import SOP")
    dopimport = geo.createNode("dopimport", "dop_import1")
    _set_parm_safe(dopimport, "doppath", dopnet.path())
    all_nodes.append(dopimport.path())

    # -- Step 9: File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    filecache.setInput(0, dopimport, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    # -- Step 10: Layout
    print("[workflow] Laying out nodes")
    geo.layoutChildren()
    dopnet.layoutChildren()

    print(f"[workflow] RBD simulation '{name}' setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "dop_path": dopnet.path(),
        "cache_path": filecache.path(),
        "all_nodes": all_nodes,
    }


###### workflow.setup_flip_sim

def _setup_flip_sim(
    source_geo: str = "/obj/geo1/sphere1",
    domain: str = "box",
    particle_sep: float = 0.05,
    name: str = "flip_sim",
    **_: Any,
) -> dict:
    """Build a complete FLIP fluid simulation network.

    Creates a geometry node with a DOP Network, FLIP solver, FLIP source,
    FLIP domain/tank, Object Merge for source, and a File Cache.

    Args:
        source_geo: Path to the source geometry SOP.
        domain: Domain type hint (reserved for future use).
        particle_sep: Particle separation distance for the FLIP sim.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    all_nodes: list[str] = []

    # -- Step 1: Create geo container
    print(f"[workflow] Creating geo node '{name}' under /obj")
    geo = obj.createNode("geo", name)
    for child in geo.children():
        child.destroy()
    all_nodes.append(geo.path())

    # -- Step 2: Object Merge for source
    print(f"[workflow] Creating Object Merge for source: {source_geo}")
    objmerge = geo.createNode("object_merge", "source_geo")
    _set_parm_safe(objmerge, "objpath1", source_geo)
    all_nodes.append(objmerge.path())

    if hou.node(source_geo) is not None:
        print(f"[workflow] Source geometry found at {source_geo}")
    else:
        print(f"[workflow] Warning: source geometry '{source_geo}' not found -- Object Merge created but path may need updating")

    # -- Step 3: Create DOP Network
    print("[workflow] Creating DOP Network")
    dopnet = geo.createNode("dopnet", "dopnet1")
    all_nodes.append(dopnet.path())

    # -- Step 4: Create FLIP solver
    print("[workflow] Creating FLIP Solver DOP")
    try:
        flipsolver = dopnet.createNode("flipsolver", "flipsolver1")
    except hou.OperationFailed:
        flipsolver = dopnet.createNode("flipsolver::2.0", "flipsolver1")
    all_nodes.append(flipsolver.path())

    # -- Step 5: Create FLIP Object
    print("[workflow] Creating FLIP Object DOP")
    try:
        flipobj = dopnet.createNode("flipobject", "flipobject1")
        all_nodes.append(flipobj.path())
        _set_parm_safe(flipobj, "particlesep", particle_sep)
        flipsolver.setInput(0, flipobj, 0)
    except hou.OperationFailed:
        print("[workflow] Warning: flipobject not available")
        flipobj = None

    # -- Step 6: Create FLIP Source
    print("[workflow] Creating FLIP Source DOP")
    try:
        flipsource = dopnet.createNode("flipsource", "flipsource1")
        all_nodes.append(flipsource.path())
    except hou.OperationFailed:
        print("[workflow] Warning: flipsource not available, trying volume source")
        try:
            flipsource = dopnet.createNode("sourcevolume", "flipsource1")
            all_nodes.append(flipsource.path())
        except hou.OperationFailed:
            print("[workflow] Warning: source volume not available")
            flipsource = None

    # -- Step 7: Create FLIP Tank / Domain
    print("[workflow] Creating FLIP Tank / Domain")
    try:
        fliptank = geo.createNode("fluidtank", "flip_tank1")
        all_nodes.append(fliptank.path())
    except hou.OperationFailed:
        print("[workflow] Warning: fluidtank not available, creating box domain")
        try:
            fliptank = geo.createNode("box", "flip_domain1")
            _set_parm_safe(fliptank, "sizex", 4.0)
            _set_parm_safe(fliptank, "sizey", 4.0)
            _set_parm_safe(fliptank, "sizez", 4.0)
            all_nodes.append(fliptank.path())
        except Exception as e:
            print(f"[workflow] Warning: could not create domain: {e}")
            fliptank = None

    # -- Step 8: DOP Import
    print("[workflow] Creating DOP Import SOP")
    dopimport = geo.createNode("dopimport", "dop_import1")
    _set_parm_safe(dopimport, "doppath", dopnet.path())
    all_nodes.append(dopimport.path())

    # -- Step 9: File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    filecache.setInput(0, dopimport, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    # -- Step 10: Layout
    print("[workflow] Laying out nodes")
    geo.layoutChildren()
    dopnet.layoutChildren()

    print(f"[workflow] FLIP simulation '{name}' setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "dop_path": dopnet.path(),
        "cache_path": filecache.path(),
        "all_nodes": all_nodes,
    }


###### workflow.setup_vellum_sim

def _setup_vellum_sim(
    geo_path: str = "/obj/geo1",
    sim_type: str = "cloth",
    substeps: int = 5,
    name: str = "vellum_sim",
    **_: Any,
) -> dict:
    """Build a complete Vellum simulation network.

    Creates a geometry node with Vellum Configure (cloth/hair/grain/softbody),
    Vellum Solver, Object Merge source, and a File Cache.

    Args:
        geo_path: Path to the source geometry object.
        sim_type: Simulation type -- "cloth", "hair", "grain", or "softbody".
        substeps: Number of solver substeps.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    all_nodes: list[str] = []

    valid_types = ("cloth", "hair", "grain", "softbody")
    if sim_type not in valid_types:
        raise ValueError(f"Invalid sim_type '{sim_type}'. Must be one of: {valid_types}")

    # Map sim_type to Vellum configure node type
    configure_map = {
        "cloth": "vellumdrape",
        "hair": "vellumhair",
        "grain": "vellumgrain",
        "softbody": "vellumsoftbody",
    }
    # Fallback: vellumconstraints works for all types
    configure_fallback = "vellumconstraints"

    # -- Step 1: Create geo container
    print(f"[workflow] Creating geo node '{name}' under /obj")
    geo = obj.createNode("geo", name)
    for child in geo.children():
        child.destroy()
    all_nodes.append(geo.path())

    # -- Step 2: Object Merge source
    print(f"[workflow] Creating Object Merge for source: {geo_path}")
    objmerge = geo.createNode("object_merge", "source_geo")
    _set_parm_safe(objmerge, "objpath1", geo_path)
    all_nodes.append(objmerge.path())

    if hou.node(geo_path) is not None:
        print(f"[workflow] Source geometry found at {geo_path}")
    else:
        print(f"[workflow] Warning: source geometry '{geo_path}' not found -- Object Merge created but path may need updating")

    # -- Step 3: Vellum Configure
    print(f"[workflow] Creating Vellum Configure ({sim_type})")
    configure_type = configure_map[sim_type]
    try:
        vellum_configure = geo.createNode(configure_type, f"vellum_{sim_type}1")
    except hou.OperationFailed:
        print(f"[workflow] Warning: {configure_type} not available, falling back to {configure_fallback}")
        try:
            vellum_configure = geo.createNode(configure_fallback, f"vellum_{sim_type}1")
        except hou.OperationFailed:
            raise ValueError(
                f"Could not create Vellum configure node. "
                f"Tried '{configure_type}' and '{configure_fallback}'."
            )
    vellum_configure.setInput(0, objmerge, 0)
    all_nodes.append(vellum_configure.path())

    # -- Step 4: Vellum Solver
    print("[workflow] Creating Vellum Solver SOP")
    try:
        vellum_solver = geo.createNode("vellumsolver", "vellum_solver1")
    except hou.OperationFailed:
        vellum_solver = geo.createNode("vellumsolver::2.0", "vellum_solver1")
    # Connect geometry output and constraints output
    vellum_solver.setInput(0, vellum_configure, 0)
    try:
        vellum_solver.setInput(1, vellum_configure, 1)
    except Exception:
        print("[workflow] Warning: could not connect constraints output to solver input 1")
    all_nodes.append(vellum_solver.path())

    # Set substeps
    _set_parm_safe(vellum_solver, "substeps", substeps)

    # -- Step 5: File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    filecache.setInput(0, vellum_solver, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    # -- Step 6: Layout
    print("[workflow] Laying out nodes")
    geo.layoutChildren()

    print(f"[workflow] Vellum simulation '{name}' ({sim_type}) setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "solver_path": vellum_solver.path(),
        "configure_path": vellum_configure.path(),
        "cache_path": filecache.path(),
        "sim_type": sim_type,
        "all_nodes": all_nodes,
    }


###### workflow.create_material

def _create_material(
    name: str = "material1",
    mat_type: str = "principled",
    base_color: list = None,
    roughness: float = 0.5,
    metallic: float = 0.0,
    opacity: float = 1.0,
    **_: Any,
) -> dict:
    """Create a material/shader in the /mat context.

    Supports principled shader and MaterialX standard surface.

    Args:
        name: Name for the material subnet/node.
        mat_type: Material type -- "principled" or "materialx".
        base_color: Optional [R, G, B] base color (0.0-1.0 each).
        roughness: Surface roughness (0.0 = mirror, 1.0 = diffuse).
        metallic: Metallic factor (0.0 = dielectric, 1.0 = metal).
        opacity: Opacity (0.0 = transparent, 1.0 = opaque).
    """
    mat = _ensure_mat_context()

    if mat_type == "principled":
        # -- Principled Shader
        print(f"[workflow] Creating principled shader '{name}' in /mat")
        try:
            shader = mat.createNode("principledshader", name)
        except hou.OperationFailed:
            shader = mat.createNode("principledshader::2.0", name)

        if base_color is not None and len(base_color) >= 3:
            print(f"[workflow] Setting base color to {base_color}")
            _set_parm_safe(shader, "basecolorr", base_color[0])
            _set_parm_safe(shader, "basecolorg", base_color[1])
            _set_parm_safe(shader, "basecolorb", base_color[2])

        print(f"[workflow] Setting roughness={roughness}, metallic={metallic}, opacity={opacity}")
        _set_parm_safe(shader, "rough", roughness)
        _set_parm_safe(shader, "metallic", metallic)
        _set_parm_safe(shader, "opac", opacity)

        shader_path = shader.path()

    elif mat_type == "materialx":
        # -- MaterialX Standard Surface
        print(f"[workflow] Creating MaterialX standard surface '{name}' in /mat")
        try:
            shader = mat.createNode("mtlxstandard_surface", name)
        except hou.OperationFailed:
            try:
                shader = mat.createNode("mtlxsurface", name)
            except hou.OperationFailed:
                # Fallback: create a subnet with materialx nodes
                shader = mat.createNode("subnet", name)
                print("[workflow] Warning: MaterialX node types not directly available, created subnet")

        if base_color is not None and len(base_color) >= 3:
            print(f"[workflow] Setting base color to {base_color}")
            _set_parm_safe(shader, "base_colorr", base_color[0])
            _set_parm_safe(shader, "base_colorg", base_color[1])
            _set_parm_safe(shader, "base_colorb", base_color[2])

        print(f"[workflow] Setting roughness={roughness}, metallic={metallic}, opacity={opacity}")
        _set_parm_safe(shader, "specular_roughness", roughness)
        _set_parm_safe(shader, "metalness", metallic)
        _set_parm_safe(shader, "opacity", opacity)

        shader_path = shader.path()

    else:
        raise ValueError(f"Unknown mat_type '{mat_type}'. Must be 'principled' or 'materialx'.")

    mat.layoutChildren()

    print(f"[workflow] Material '{name}' created at {shader_path}")

    return {
        "success": True,
        "material_path": shader_path,
        "shader_node_path": shader_path,
        "type": mat_type,
    }


###### workflow.assign_material

def _assign_material(
    geo_path: str,
    material_path: str,
    **_: Any,
) -> dict:
    """Assign a material to a geometry node.

    Creates a Material SOP at the end of the SOP chain inside the
    geometry node, sets the material path, and enables the display flag.

    Args:
        geo_path: Path to the geometry Object node (e.g. "/obj/geo1").
        material_path: Path to the material to assign (e.g. "/mat/material1").
    """
    print(f"[workflow] Assigning material '{material_path}' to '{geo_path}'")

    geo = _get_node(geo_path)

    # Determine the SOP-level parent -- if geo_path points to an Object-level
    # node we work inside it; if it already points to a SOP network, use it.
    category = geo.type().category().name()
    if category == "Object":
        sop_parent = geo
    elif category == "Sop":
        sop_parent = geo.parent()
    else:
        sop_parent = geo

    # Find the last displayed SOP
    print("[workflow] Finding last displayed SOP")
    last_displayed = None
    for child in sop_parent.children():
        try:
            if child.isDisplayFlagSet():
                last_displayed = child
        except Exception:
            pass

    # If no display flag found, pick the last child
    if last_displayed is None:
        children = list(sop_parent.children())
        if children:
            last_displayed = children[-1]

    # -- Create Material SOP
    print("[workflow] Creating Material SOP")
    mat_sop = sop_parent.createNode("material", "material1")

    # Wire after last displayed SOP
    if last_displayed is not None:
        print(f"[workflow] Wiring Material SOP after {last_displayed.path()}")
        mat_sop.setInput(0, last_displayed, 0)

    # Set material path
    print(f"[workflow] Setting shop_materialpath1 to {material_path}")
    _set_parm_safe(mat_sop, "shop_materialpath1", material_path)

    # Set display and render flags
    try:
        mat_sop.setDisplayFlag(True)
        mat_sop.setRenderFlag(True)
    except Exception:
        pass

    sop_parent.layoutChildren()

    print(f"[workflow] Material assigned: {mat_sop.path()} -> {material_path}")

    return {
        "success": True,
        "material_sop_path": mat_sop.path(),
        "material_path": material_path,
    }


###### workflow.build_sop_chain

def _build_sop_chain(
    parent_path: str = "/obj/geo1",
    steps: list = None,
    **_: Any,
) -> dict:
    """Build a sequential chain of SOPs inside a network.

    Each step dict specifies a node type and optional name/params.
    Nodes are wired sequentially (output 0 -> input 0).

    Args:
        parent_path: Path to the parent SOP network.
        steps: List of step dicts, each with keys:
               - "type" (str): Node type to create (required).
               - "name" (str): Optional node name.
               - "params" (dict): Optional parameter values to set.
    """
    if steps is None or len(steps) == 0:
        raise ValueError("steps list is required and must not be empty")

    parent = _get_node(parent_path)
    created_nodes: list[dict] = []
    prev_node = None

    for i, step in enumerate(steps):
        node_type = step.get("type")
        if node_type is None:
            raise ValueError(f"Step {i} is missing required 'type' key")

        node_name = step.get("name")
        params = step.get("params", {})

        print(f"[workflow] Step {i + 1}/{len(steps)}: Creating '{node_type}'" +
              (f" (name='{node_name}')" if node_name else ""))

        try:
            node = parent.createNode(node_type, node_name=node_name)
        except hou.OperationFailed as e:
            raise ValueError(
                f"Failed to create node of type '{node_type}' at step {i + 1}: {e}"
            )

        # Wire to previous node
        if prev_node is not None:
            try:
                node.setInput(0, prev_node, 0)
            except Exception as e:
                print(f"[workflow] Warning: could not wire step {i + 1} to previous node: {e}")

        # Set parameters
        if params:
            print(f"[workflow] Setting {len(params)} parameter(s) on {node.path()}")
            for parm_name, parm_value in params.items():
                _set_parm_safe(node, parm_name, parm_value)

        created_nodes.append({
            "path": node.path(),
            "type": node.type().name(),
            "name": node.name(),
        })
        prev_node = node

    # Set display flag on last node
    if prev_node is not None:
        try:
            prev_node.setDisplayFlag(True)
            prev_node.setRenderFlag(True)
            print(f"[workflow] Display flag set on {prev_node.path()}")
        except Exception:
            pass

    # Layout
    print("[workflow] Laying out nodes")
    parent.layoutChildren()

    print(f"[workflow] SOP chain built: {len(created_nodes)} node(s)")

    return {
        "success": True,
        "nodes": created_nodes,
        "displayed": prev_node.path() if prev_node else None,
    }


###### workflow.setup_render

def _setup_render(
    renderer: str = "karma",
    camera: str = None,
    output_path: str = "$HIP/render/output.$F4.exr",
    resolution: list = None,
    samples: int = 64,
    name: str = "render1",
    **_: Any,
) -> dict:
    """Set up a complete render configuration.

    Creates a camera (if none specified), a ROP node in /out, and
    configures output path, resolution, and sample count.

    Args:
        renderer: Renderer to use -- "karma" or "mantra".
        camera: Path to an existing camera. If None, creates one in /obj.
        output_path: Output image file path (supports Houdini variables).
        resolution: [width, height] resolution (default: [1920, 1080]).
        samples: Number of render samples.
        name: Name for the ROP node.
    """
    if resolution is None:
        resolution = [1920, 1080]

    obj = _ensure_obj_context()
    out = _ensure_out_context()
    all_nodes: list[str] = []

    # -- Step 1: Camera
    if camera is None:
        print("[workflow] Creating camera at /obj")
        cam = obj.createNode("cam", "render_cam")
        camera = cam.path()
        all_nodes.append(camera)

        # Set reasonable defaults
        _set_parm_safe(cam, "resx", resolution[0])
        _set_parm_safe(cam, "resy", resolution[1])
        print(f"[workflow] Camera created at {camera}")
    else:
        print(f"[workflow] Using existing camera: {camera}")
        if hou.node(camera) is None:
            print(f"[workflow] Warning: camera '{camera}' not found -- ROP will reference it anyway")

    # -- Step 2: ROP node
    if renderer == "karma":
        print(f"[workflow] Creating Karma ROP '{name}' in /out")
        try:
            rop = out.createNode("karma", name)
        except hou.OperationFailed:
            try:
                rop = out.createNode("karma::2.0", name)
            except hou.OperationFailed:
                rop = out.createNode("usdrender_rop", name)
                print("[workflow] Warning: karma ROP not available, using usdrender_rop")
    elif renderer == "mantra":
        print(f"[workflow] Creating Mantra ROP '{name}' in /out")
        try:
            rop = out.createNode("ifd", name)
        except hou.OperationFailed:
            rop = out.createNode("mantra", name)
    else:
        raise ValueError(f"Unknown renderer '{renderer}'. Must be 'karma' or 'mantra'.")

    all_nodes.append(rop.path())

    # -- Step 3: Configure output path
    print(f"[workflow] Setting output path: {output_path}")
    # Try common parameter names for different ROP types
    output_set = False
    for parm_name in ("picture", "vm_picture", "outputimage", "ar_picture"):
        if _set_parm_safe(rop, parm_name, output_path):
            output_set = True
            break
    if not output_set:
        print("[workflow] Warning: could not find output path parameter on ROP")

    # -- Step 4: Configure resolution
    print(f"[workflow] Setting resolution: {resolution[0]}x{resolution[1]}")
    # Resolution can be on the ROP or on the camera
    _set_parm_safe(rop, "resx", resolution[0])
    _set_parm_safe(rop, "resy", resolution[1])
    _set_parm_safe(rop, "res_overridex", resolution[0])
    _set_parm_safe(rop, "res_overridey", resolution[1])

    # -- Step 5: Configure samples
    print(f"[workflow] Setting samples: {samples}")
    for parm_name in ("vm_samples", "samples", "samplesperpixel", "vm_samplesx", "karma_samples"):
        _set_parm_safe(rop, parm_name, samples)

    # -- Step 6: Set camera path
    print(f"[workflow] Setting camera: {camera}")
    for parm_name in ("camera", "cam", "viewcamera"):
        if _set_parm_safe(rop, parm_name, camera):
            break

    # Layout
    out.layoutChildren()

    print(f"[workflow] Render setup '{name}' complete ({renderer})")

    return {
        "success": True,
        "rop_path": rop.path(),
        "camera_path": camera,
        "output_path": output_path,
        "renderer": renderer,
        "resolution": resolution,
        "samples": samples,
        "all_nodes": all_nodes,
    }


###### Registration

register_handler("workflow.setup_pyro_sim", _setup_pyro_sim)
register_handler("workflow.setup_rbd_sim", _setup_rbd_sim)
register_handler("workflow.setup_flip_sim", _setup_flip_sim)
register_handler("workflow.setup_vellum_sim", _setup_vellum_sim)
register_handler("workflow.create_material", _create_material)
register_handler("workflow.assign_material", _assign_material)
register_handler("workflow.build_sop_chain", _build_sop_chain)
register_handler("workflow.setup_render", _setup_render)
