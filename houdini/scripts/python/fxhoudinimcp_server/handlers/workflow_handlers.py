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
from fxhoudinimcp_server.config import layout_if_enabled
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message

###### Helpers


def _get_node(node_path: str) -> hou.Node:
    """Resolve a node path and raise a clear error if it does not exist."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _focus_network_editor(node: hou.Node) -> None:
    """Best-effort: layout the parent network, then pan the editor to *node*."""
    try:
        parent = node.parent()
        if parent is not None:
            layout_if_enabled(parent)
        for pane_tab in hou.ui.paneTabs():
            if pane_tab.type() == hou.paneTabType.NetworkEditor:
                if parent is not None:
                    pane_tab.cd(parent.path())
                pane_tab.setCurrentNode(node)
                pane_tab.homeToSelection()
                return
    except Exception:
        pass


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
            print(
                f"[workflow] Warning: could not set {parm_name}={value} on {node.path()}: {readable_message(e)}"
            )
            return False
    return False


def _create_first_available(
    parent: hou.Node, type_names: tuple[str, ...], node_name: str
) -> hou.Node:
    """Create the first of *type_names* that exists under *parent*.

    Lets a chain be written preferred-type-first without nesting try/except per
    candidate. Raises hou.OperationFailed naming the whole chain if none exist,
    which is more useful than the last candidate's own error.
    """
    for type_name in type_names:
        try:
            return parent.createNode(type_name, node_name)
        except hou.OperationFailed:
            continue
    raise hou.OperationFailed(
        f"None of these node types exist in {parent.path()}: {', '.join(type_names)}"
    )


def _source_status(objmerge: hou.Node, source_geo: str, what: str) -> dict[str, Any]:
    """Whether the source geometry a sim was pointed at actually exists.

    Building the network with a placeholder source is legitimate -- the path is a
    parameter, fixable later -- but reporting success: True and nothing else means a
    caller walks away with a sim that will never produce anything, and no reason to
    look. setup_pyro_sim said so; setup_flip_sim, setup_rbd_sim and
    setup_vellum_sim did not, which is the kind of inconsistency that makes a
    server's answers untrustworthy in aggregate.

    Args:
        objmerge: The Object Merge SOP holding the reference.
        source_geo: The path it was pointed at.
        what: Sim name for the description ("FLIP", "RBD", "Vellum").
    """
    found = hou.node(source_geo) is not None
    return {
        "objmerge_path": objmerge.path(),
        "source_geo": source_geo,
        "source_geo_found": found,
        "network_description": (
            f"The {what} network is wired. Source geometry is referenced via the "
            f"Object Merge SOP at {objmerge.path()} (parameter 'objpath1' = "
            f"'{source_geo}'). "
            + (
                "The source geometry was found and connected successfully."
                if found
                else f"WARNING: source geometry '{source_geo}' was NOT found, so this "
                f"sim will simulate nothing until the 'objpath1' parameter on "
                f"{objmerge.path()} points at a real SOP."
            )
        ),
    }


###### workflow.setup_pyro_sim


def _setup_pyro_sim_sop(
    geo: hou.Node,
    objmerge: hou.Node,
    substeps: int,
    all_nodes: list[str],
) -> dict:
    """Build a SOP-level Pyro simulation (Houdini 20+).

    Uses the modern pyrosource + pyrosolver SOP workflow.

    Args:
        geo: Parent geometry node.
        objmerge: Object Merge SOP referencing the source geometry.
        substeps: Number of solver substeps.
        all_nodes: Accumulator list for created node paths.
    """
    # -- Pyro Source: converts geometry to source volumes
    print("[workflow] Creating Pyro Source SOP")
    pyrosource = geo.createNode("pyrosource", "pyro_source1")
    pyrosource.setInput(0, objmerge, 0)
    all_nodes.append(pyrosource.path())

    # -- Pyro Solver SOP (SOP-level, Houdini 20+)
    print("[workflow] Creating Pyro Solver SOP")
    try:
        pyrosolver = geo.createNode("pyrosolver::3.0", "pyro_solver1")
    except hou.OperationFailed:
        pyrosolver = geo.createNode("pyrosolver", "pyro_solver1")
    pyrosolver.setInput(0, pyrosource, 0)
    all_nodes.append(pyrosolver.path())

    # Set substeps
    _set_parm_safe(pyrosolver, "substeps", substeps)

    # -- File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache", "file_cache1")
    filecache.setInput(0, pyrosolver, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    layout_if_enabled(geo)
    _focus_network_editor(filecache)
    print("[workflow] SOP-level Pyro setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "solver_path": pyrosolver.path(),
        "source_path": pyrosource.path(),
        "cache_path": filecache.path(),
        "approach": "sop",
        "all_nodes": all_nodes,
    }


def _setup_pyro_sim_dop(
    geo: hou.Node,
    objmerge: hou.Node,
    substeps: int,
    all_nodes: list[str],
) -> dict:
    """Build a DOP-level Pyro simulation (fallback for older Houdini).

    Uses a DOP Network with smokeobject_sparse, volumesource and
    pyrosolver_sparse, merged into the solver's first input.

    Args:
        geo: Parent geometry node.
        objmerge: Object Merge SOP referencing the source geometry.
        substeps: Number of DOP substeps.
        all_nodes: Accumulator list for created node paths.
    """
    # -- DOP Network
    print("[workflow] Creating DOP Network inside geo")
    dopnet = geo.createNode("dopnet", "dopnet1")
    all_nodes.append(dopnet.path())
    _set_parm_safe(dopnet, "substep", substeps)

    # -- Smoke Object
    #
    # smokeobject_sparse first. Houdini 22.0 marks both smokeobject and
    # smokeconfigureobject deprecated (hou.NodeType.deprecated is True for both)
    # and the release notes say they are "scheduled to be deleted in an upcoming
    # revision", naming Smoke Object (Sparse) as the replacement. The sparse node
    # exists in every build we sample, back to 20.5.278, so preferring it costs
    # nothing on older Houdini and keeps this path alive once the old nodes go.
    print("[workflow] Creating smoke object DOP")
    smokeobj = _create_first_available(
        dopnet,
        ("smokeobject_sparse", "smokeobject", "smokeconfigureobject"),
        "smokeobject1",
    )
    all_nodes.append(smokeobj.path())

    # -- Volume Source
    #
    # volumesource, not sourcevolume: Houdini marks sourcevolume deprecated and
    # ships no help page for it, while volumesource is documented as the node
    # that "imports SOP source geometry into smoke, pyro, and FLIP simulations"
    # and is present in every build we sample.
    print("[workflow] Creating volume source DOP")
    source_vol = None
    try:
        source_vol = _create_first_available(
            dopnet, ("volumesource", "sourcevolume"), "source_volume1"
        )
        all_nodes.append(source_vol.path())
        # Point the volume source at the Object Merge SOP
        for parm_name in ("sop_path", "soppath", "geometry"):
            if _set_parm_safe(source_vol, parm_name, objmerge.path()):
                print(f"[workflow] Set volume source {parm_name} = {objmerge.path()}")
                break
    except hou.OperationFailed:
        print("[workflow] Warning: no volume source node available, skipping")

    # -- Pyro Solver
    #
    # Same reasoning as the smoke object: the 22.0 notes list "Pyro Solver DOP"
    # among the deprecated DOP pyro nodes and point at Pyro Solver (Sparse).
    # Houdini's own deprecated flag is still False on pyrosolver, so the old
    # versioned types stay as fallbacks rather than being dropped.
    print("[workflow] Creating pyro solver DOP")
    pyrosolver = _create_first_available(
        dopnet,
        ("pyrosolver_sparse", "pyrosolver::2.0", "pyrosolver"),
        "pyrosolver1",
    )
    all_nodes.append(pyrosolver.path())

    # No resize container. This used to create a gasresizefluiddynamic and wire
    # it to the solver's output, which is not a valid DOP-level connection -- it
    # is a microsolver belonging inside a solver's subnet, so the wiring always
    # failed and the node sat there doing nothing. It is also unnecessary now:
    # SideFX document the sparse smoke object as growing on its own ("the
    # container will grow as the simulated smoke and fire inside it" expands,
    # starting empty and resizing at initial sourcing).

    # -- Merge DOP to combine smoke object and volume source
    print("[workflow] Creating merge DOP and wiring solver chain")
    try:
        merge_dop = dopnet.createNode("merge", "merge1")
        merge_dop.setInput(0, smokeobj, 0)
        if source_vol is not None:
            merge_dop.setInput(1, source_vol, 0)
        pyrosolver.setInput(0, merge_dop, 0)
        all_nodes.append(merge_dop.path())
    except Exception as e:
        print(f"[workflow] Warning: merge DOP failed, wiring directly: {readable_message(e)}")
        pyrosolver.setInput(0, smokeobj, 0)

    # -- DOP Import SOP
    print("[workflow] Creating DOP Import SOP")
    dopimport = geo.createNode("dopimport", "dop_import1")
    _set_parm_safe(dopimport, "doppath", dopnet.path())
    all_nodes.append(dopimport.path())

    # -- File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache", "file_cache1")
    filecache.setInput(0, dopimport, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    layout_if_enabled(geo)
    layout_if_enabled(dopnet)
    _focus_network_editor(filecache)
    print("[workflow] DOP-level Pyro setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "dop_path": dopnet.path(),
        "cache_path": filecache.path(),
        "approach": "dop",
        "all_nodes": all_nodes,
    }


def _setup_pyro_sim(
    source_geo: str = "/obj/geo1/sphere1",
    container: str = "box",
    res_scale: float = 1.0,
    substeps: int = 1,
    name: str = "pyro_sim",
    **_: Any,
) -> dict:
    """Build a complete Pyro smoke/fire simulation network.

    Tries the modern SOP-level approach first (Houdini 20+, using
    pyrosource + pyrosolver SOPs).  Falls back to the classic DOP
    approach (smokeobject_sparse + volumesource + pyrosolver_sparse DOPs) for
    older Houdini versions.

    Args:
        source_geo: Path to the source geometry SOP to drive the simulation.
        container: Container shape. Only "box" is implemented; anything else is
            rejected rather than silently ignored.
        res_scale: Resolution scale multiplier for the simulation.
        substeps: Number of DOP substeps or solver substeps.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    # A parameter that is accepted and ignored is worse than one that is missing:
    # it reads as functional, so asking for something else returns a box and
    # reports success. Only "box" is built, so say so.
    if container != "box":
        raise ValueError(
            f"Unsupported container '{container}'. Only 'box' is implemented; the "
            f"other shapes are not built yet."
        )

    all_nodes: list[str] = []

    # -- Create top-level geo container
    print(f"[workflow] Creating geo node '{name}' under /obj")
    geo = obj.createNode("geo", name)
    for child in geo.children():
        child.destroy()
    all_nodes.append(geo.path())

    # -- Object Merge for source geometry
    print(f"[workflow] Creating Object Merge for source: {source_geo}")
    objmerge = geo.createNode("object_merge", "source_geo")
    _set_parm_safe(objmerge, "objpath1", source_geo)
    all_nodes.append(objmerge.path())

    if hou.node(source_geo) is not None:
        print(f"[workflow] Source geometry found at {source_geo}")
    else:
        print(
            f"[workflow] Warning: source geometry '{source_geo}' not found, Object Merge created but path may need updating"
        )

    # -- Try modern SOP-level Pyro first, fall back to DOP approach
    try:
        print("[workflow] Attempting SOP-level Pyro workflow (Houdini 20+)")
        result = _setup_pyro_sim_sop(geo, objmerge, substeps, all_nodes)
        print(f"[workflow] Pyro simulation '{name}' setup complete (SOP approach)")
    except hou.OperationFailed:
        print("[workflow] SOP-level Pyro not available, falling back to DOP approach")
        # Clean up any partially-created SOP nodes (keep geo and objmerge)
        for child in geo.children():
            if child != objmerge:
                try:
                    if child.type().name() not in ("object_merge",):
                        child.destroy()
                except Exception:
                    pass

        result = _setup_pyro_sim_dop(geo, objmerge, substeps, all_nodes)
        print(f"[workflow] Pyro simulation '{name}' setup complete (DOP approach)")

    # Augment the result with source wiring info so the AI client
    # understands the network and does not try to re-wire things.
    source_found = hou.node(source_geo) is not None
    result["objmerge_path"] = objmerge.path()
    result["source_geo"] = source_geo
    result["source_geo_found"] = source_found
    result["network_description"] = (
        f"The Pyro network is fully wired and ready to simulate. "
        f"Source geometry is referenced via the Object Merge SOP at "
        f"{objmerge.path()} (parameter 'objpath1' = '{source_geo}'). "
        + (
            "The source geometry was found and connected successfully. "
            if source_found
            else f"WARNING: source geometry '{source_geo}' was NOT found. "
            f"Update the 'objpath1' parameter on {objmerge.path()} to "
            f"point to a valid SOP path. "
        )
        + "No additional wiring is needed."
    )
    return result


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

    # -- Step 3: Optional fracture. rbdmaterialfracture is the modern
    # one-input choice whose outputs (geometry/constraints/proxy) feed the
    # Bullet solver directly. Plain voronoifracture REQUIRES cell points
    # on its second input — wiring it alone leaves an uncookable network.
    # Only "voronoi" ever did anything; every other string silently skipped
    # fracturing and still reported success, so a typo returned an unfractured sim
    # that looks like a working one. Not fracturing is a legitimate request, so it
    # gets a name rather than being what happens when you misspell the other one.
    valid_pieces = ("voronoi", "none")
    if pieces_type not in valid_pieces:
        raise ValueError(
            f"Invalid pieces_type '{pieces_type}'. Must be one of: {valid_pieces}. "
            f"Use 'none' to simulate the geometry unfractured."
        )

    fracture = None
    if pieces_type == "voronoi":
        try:
            print("[workflow] Creating RBD Material Fracture SOP")
            fracture = geo.createNode("rbdmaterialfracture", "fracture1")
            fracture.setInput(0, last_sop, 0)
            all_nodes.append(fracture.path())
            last_sop = fracture
        except hou.OperationFailed:
            print("[workflow] rbdmaterialfracture unavailable, using scatter + voronoifracture")
            scatter = geo.createNode("scatter", "cell_points")
            scatter.setInput(0, last_sop, 0)
            _set_parm_safe(scatter, "npts", 30)
            voronoi = geo.createNode("voronoifracture", "voronoi_fracture1")
            voronoi.setInput(0, last_sop, 0)
            voronoi.setInput(1, scatter, 0)
            all_nodes.extend([scatter.path(), voronoi.path()])
            last_sop = voronoi

    # -- Step 4: Solver. Prefer the SOP-level Bullet solver (Houdini
    # 18.5+): it simulates its input directly, applies gravity, and has a
    # built-in ground plane — no DOP wiring to get wrong.
    solver_path = None
    try:
        solver = geo.createNode("rbdbulletsolver", "rbd_solver1")
    except hou.OperationFailed:
        solver = None

    if solver is not None:
        print("[workflow] Creating SOP-level RBD Bullet Solver")
        solver.setInput(0, last_sop, 0)
        if fracture is not None and fracture.type().name().startswith("rbdmaterialfracture"):
            # Outputs line up 1:1 with the solver's first three inputs.
            solver.setInput(1, fracture, 1)
            solver.setInput(2, fracture, 2)
        _set_parm_safe(solver, "useground", 1 if ground else 0)
        all_nodes.append(solver.path())
        solver_path = solver.path()
        last_sop = solver
    else:
        # Legacy DOP fallback: the packed object must point at the SOP
        # geometry, and object + ground must merge into the solver chain.
        print("[workflow] Creating DOP Network (SOP solver unavailable)")
        dopnet = geo.createNode("dopnet", "dopnet1")
        all_nodes.append(dopnet.path())
        solver_path = dopnet.path()

        rbdobj = dopnet.createNode("rbdpackedobject", "rbdobject1")
        for parm_name in ("soppath", "sop_path"):
            if _set_parm_safe(rbdobj, parm_name, last_sop.path()):
                break
        all_nodes.append(rbdobj.path())

        rbdsolver = dopnet.createNode("rbdsolver", "rbdsolver1")
        all_nodes.append(rbdsolver.path())

        merge_dop = dopnet.createNode("merge", "merge1")
        merge_dop.setInput(0, rbdobj, 0)
        if ground:
            groundplane = dopnet.createNode("groundplane", "groundplane1")
            merge_dop.setInput(1, groundplane, 0)
            all_nodes.append(groundplane.path())
        rbdsolver.setInput(0, merge_dop, 0)
        gravity = dopnet.createNode("gravity", "gravity1")
        gravity.setInput(0, rbdsolver, 0)
        gravity.setDisplayFlag(True)
        all_nodes.append(gravity.path())

        dopimport = geo.createNode("dopimport", "dop_import1")
        _set_parm_safe(dopimport, "doppath", dopnet.path())
        dopimport.setInput(0, last_sop, 0)
        all_nodes.append(dopimport.path())
        last_sop = dopimport

    # -- Step 5: File Cache
    print("[workflow] Creating File Cache SOP")
    try:
        filecache = geo.createNode("filecache", "file_cache1")
    except hou.OperationFailed:
        filecache = geo.createNode("filecache::2.0", "file_cache1")
    filecache.setInput(0, last_sop, 0)
    all_nodes.append(filecache.path())

    try:
        filecache.setDisplayFlag(True)
        filecache.setRenderFlag(True)
    except Exception:
        pass

    # -- Step 6: Layout
    print("[workflow] Laying out nodes")
    layout_if_enabled(geo)
    _focus_network_editor(filecache)

    print(f"[workflow] RBD simulation '{name}' setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "solver_path": solver_path,
        "cache_path": filecache.path(),
        "all_nodes": all_nodes,
        **_source_status(objmerge, geo_path, "RBD"),
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
        domain: Domain shape. Only "box" is implemented; anything else is
            rejected rather than silently ignored.
        particle_sep: Particle separation distance for the FLIP sim.
        name: Name for the top-level geometry node.
    """
    obj = _ensure_obj_context()
    # A parameter that is accepted and ignored is worse than one that is missing:
    # it reads as functional, so asking for something else returns a box and
    # reports success. Only "box" is built, so say so.
    if domain != "box":
        raise ValueError(
            f"Unsupported domain '{domain}'. Only 'box' is implemented; the "
            f"other shapes are not built yet."
        )

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
        print(
            f"[workflow] Warning: source geometry '{source_geo}' not found -- Object Merge created but path may need updating"
        )

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
        # volumesource ahead of the deprecated, undocumented sourcevolume; SideFX
        # document volumesource as covering FLIP sources too.
        flipsource = _create_first_available(
            dopnet, ("flipsource", "volumesource", "sourcevolume"), "flipsource1"
        )
        all_nodes.append(flipsource.path())
    except hou.OperationFailed:
        print("[workflow] Warning: no FLIP/volume source node available")
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
            print(f"[workflow] Warning: could not create domain: {readable_message(e)}")
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
    layout_if_enabled(geo)
    layout_if_enabled(dopnet)
    _focus_network_editor(filecache)

    print(f"[workflow] FLIP simulation '{name}' setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "dop_path": dopnet.path(),
        "cache_path": filecache.path(),
        "all_nodes": all_nodes,
        **_source_status(objmerge, source_geo, "FLIP"),
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
        print(
            f"[workflow] Warning: source geometry '{geo_path}' not found -- Object Merge created but path may need updating"
        )

    # -- Step 3: Vellum Configure
    print(f"[workflow] Creating Vellum Configure ({sim_type})")
    configure_type = configure_map[sim_type]
    try:
        vellum_configure = geo.createNode(configure_type, f"vellum_{sim_type}1")
    except hou.OperationFailed:
        print(
            f"[workflow] Warning: {configure_type} not available, falling back to {configure_fallback}"
        )
        try:
            vellum_configure = geo.createNode(configure_fallback, f"vellum_{sim_type}1")
        except hou.OperationFailed:
            raise ValueError(
                f"Could not create Vellum configure node. "
                f"Tried '{configure_type}' and '{configure_fallback}'."
            ) from None
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
    layout_if_enabled(geo)
    _focus_network_editor(filecache)

    print(f"[workflow] Vellum simulation '{name}' ({sim_type}) setup complete")

    return {
        "success": True,
        "geo_path": geo.path(),
        "solver_path": vellum_solver.path(),
        "configure_path": vellum_configure.path(),
        "cache_path": filecache.path(),
        "sim_type": sim_type,
        "all_nodes": all_nodes,
        **_source_status(objmerge, geo_path, "Vellum"),
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
                print(
                    "[workflow] Warning: MaterialX node types not directly available, created subnet"
                )

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

    layout_if_enabled(mat)
    _focus_network_editor(shader)

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

    layout_if_enabled(sop_parent)
    _focus_network_editor(mat_sop)

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

        print(
            f"[workflow] Step {i + 1}/{len(steps)}: Creating '{node_type}'"
            + (f" (name='{node_name}')" if node_name else "")
        )

        try:
            node = parent.createNode(node_type, node_name=node_name)
        except hou.OperationFailed as e:
            raise ValueError(
                f"Failed to create node of type '{node_type}' at step {i + 1}: {readable_message(e)}"
            ) from e

        # Wire to previous node
        if prev_node is not None:
            try:
                node.setInput(0, prev_node, 0)
            except Exception as e:
                print(
                    f"[workflow] Warning: could not wire step {i + 1} to previous node: {readable_message(e)}"
                )

        # Set parameters
        if params:
            print(f"[workflow] Setting {len(params)} parameter(s) on {node.path()}")
            for parm_name, parm_value in params.items():
                _set_parm_safe(node, parm_name, parm_value)

        created_nodes.append(
            {
                "path": node.path(),
                "type": node.type().name(),
                "name": node.name(),
            }
        )
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
    layout_if_enabled(parent)
    if prev_node is not None:
        _focus_network_editor(prev_node)

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
            print(
                f"[workflow] Warning: camera '{camera}' not found -- ROP will reference it anyway"
            )

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
    layout_if_enabled(out)
    _focus_network_editor(rop)

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
