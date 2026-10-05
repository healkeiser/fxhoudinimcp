"""DOP (dynamics/simulation) handlers for FXHoudini-MCP.

Provides tools for inspecting and controlling DOP simulations:
simulation info, object listing, field reading, relationships,
stepping, resetting, and memory usage.
"""

from __future__ import annotations

# Built-in
import contextlib
import logging
from typing import Any

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message

logger = logging.getLogger(__name__)


###### Helpers


def _get_dop_node(node_path: str) -> hou.Node:
    """Return a DOP network node or raise if not found."""
    node = hou.node(node_path)
    if node is None:
        raise hou.NodeError(f"Node not found: {node_path}")
    return node


def _get_simulation(node_path: str) -> hou.DopSimulation:
    """Return the DopSimulation from the given DOP network node."""
    node = _get_dop_node(node_path)
    sim = node.simulation()
    if sim is None:
        raise hou.OperationFailed(
            f"Node '{node_path}' does not have a simulation. Ensure it is a DOP network node."
        )
    return sim


def _reset_button_owner(node: hou.Node) -> hou.Node | None:
    """The node whose Reset Simulation button resets *node*'s simulation.

    That is *node* itself or its nearest parent with a "resimulate" parm (the
    DOP network, or a SOP-level solver such as a POP Network), None if none.
    """
    owner = node
    while owner is not None and owner.parm("resimulate") is None:
        owner = owner.parent()
    return owner


# A write through HOM into a node inside a DOP network leaves the frames the
# simulation already cooked as they were. Measured on 22.0.429: a POP
# source's impulserate 100 -> 400, then 50, then 250, and frame 25 still held
# 100 particles however long the wait and whichever frames were visited in
# between; the same with a bare parm.set() and hou.setFrame(). Only a reset
# of the simulation brought the new value.
_DOP_CACHE_NOTE = (
    "Frames this simulation cooked before this edit may still hold the old "
    "result: an edit inside a DOP network, or upstream of a simulation, does not "
    "reset its cache. Call reset_simulation(node_path=<network>) before reading "
    "such a frame. Leave the memory cache (cacheenabled) on: it is what keeps "
    "the cooked frames, and turning it off is not the fix."
)

# How many nodes downstream of an edit are looked at for a simulation that
# reads it. The walk follows wires and references, and a scene rarely needs
# more; a bigger one gets no note rather than a slow write.
_DOWNSTREAM_LIMIT = 500

# Deeper than any network nests; bounds the walks up the parents.
_MAX_DEPTH = 64


def _inside_dop(node: hou.Node) -> bool:
    """Whether *node* is a DOP or sits anywhere inside one (a SOP Solver's SOPs)."""
    for _ in range(_MAX_DEPTH):
        if node is None:
            return False
        if node.type().category() == hou.dopNodeTypeCategory():
            return True
        node = node.parent()
    return False


def _simulation_to_reset(node: hou.Node) -> hou.Node | None:
    """_reset_button_owner, lifted out of locked assets to the instance a user can press.

    A Vellum Solver SOP keeps its DOP network inside the asset; reset_simulation
    is given the solver, not /obj/.../vellumsolver1/dopnet1.
    """
    owner = _reset_button_owner(node)
    for _ in range(_MAX_DEPTH):
        buried = False
        with contextlib.suppress(Exception):
            buried = owner is not None and owner.isInsideLockedHDA() is True
        if not buried:
            break
        lifted = _reset_button_owner(owner.parent())
        if lifted is None:
            break  # no Reset promoted above: the network itself is still pressable
        owner = lifted
    return owner


def _downstream(node: hou.Node) -> list[hou.Node]:
    """Nodes that read *node*, by wire or by reference, up to _DOWNSTREAM_LIMIT.

    A node inside a DOP network is listed but not followed: what reads the
    simulation reads the network (a DOP Import names it), not its insides.
    Nor are a node's own contents, which depend on it and say nothing about
    who reads it -- an HDA's insides were most of the walk before (22.0.429).
    """
    seen = {node.path()}
    queue, found = [node], []
    while queue and len(seen) < _DOWNSTREAM_LIMIT:
        current = queue.pop(0)
        inside = current.path() + "/"
        neighbours: list = []
        with contextlib.suppress(Exception):
            neighbours = list(current.outputs()) + list(current.dependents())
        with contextlib.suppress(Exception):
            # The node a subnet outputs: what reads the subnet reads it.
            # Measured on 22.0: a grid inside a subnet feeding a Vellum
            # Solver had no note.
            parent = current.parent()
            if not neighbours and (
                current.type().name() == "output" or parent.displayNode() == current
            ):
                neighbours.append(parent)
        for other in neighbours:
            path = other.path()
            if path in seen or path.startswith(inside):
                continue
            seen.add(path)
            found.append(other)
            if not _inside_dop(other):
                queue.append(other)
    return found


def dop_cache_note(nodes: Any, rewired: bool = False) -> dict[str, Any] | None:
    """The simulations an edit of *nodes* leaves with stale cooked frames, or None.

    ``networks`` are the nodes reset_simulation presses for them, so any of
    them can be passed to it as is. Measured on 22.0.429, each of these left
    frame 25 stale until a reset: a node inside a DOP network (a SOP Solver's
    own SOPs too), a box a POP Source reads by path, a grid upstream of a
    Vellum Solver SOP. A solver's own parameter re-simulates by itself, so
    the edited node is never its own reason -- unless *rewired*: its inputs
    changed, and those do not. Measured on 22.0: a Vellum Solver rewired
    from cloth A to cloth B still showed A at frame 10 until a reset.
    """
    networks: list[str] = []

    def add(owner: hou.Node | None) -> None:
        if owner is not None and owner.path() not in networks:
            networks.append(owner.path())

    for node in nodes or ():
        with contextlib.suppress(Exception):
            if _inside_dop(node):
                add(_simulation_to_reset(node))
                continue
            if rewired and node.parm("resimulate") is not None:
                add(_simulation_to_reset(node))
            for reader in _downstream(node):
                if _inside_dop(reader) or reader.parm("resimulate") is not None:
                    add(_simulation_to_reset(reader))
    if not networks:
        return None
    return {"networks": networks, "note": _DOP_CACHE_NOTE}


def _subdata_tree(data: hou.DopData, depth: int = 0, max_depth: int = 4) -> list[dict]:
    """Recursively build a tree of DOP subdata entries.

    Returns a list of dicts with name, data_type, and children.
    """
    if depth >= max_depth:
        return []

    result = []
    try:
        for name in data.subDataNames():
            child = data.findSubData(name)
            entry = {
                "name": name,
                "data_type": child.dataType() if child is not None else "unknown",
            }
            if child is not None:
                children = _subdata_tree(child, depth + 1, max_depth)
                if children:
                    entry["children"] = children
            result.append(entry)
    except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
        logger.debug("Failed to read subdata tree: %s", e)
    return result


def _records_to_dict(data: hou.DopData) -> dict:
    """Extract all record fields from a DopData into a plain dict."""
    result = {}
    try:
        for record_type in data.recordTypes():
            records = data.records(record_type)
            if not records:
                continue
            record_list = []
            for rec in records:
                fields = {}
                try:
                    for field_name in rec.fieldNames():
                        try:
                            val = rec.field(field_name)
                            # Convert hou types to plain Python
                            if isinstance(val, (hou.Vector2, hou.Vector3, hou.Vector4)):
                                val = list(val)
                            elif isinstance(val, (hou.Matrix3, hou.Matrix4)):
                                val = [list(row) for row in val.asTupleOfTuples()]
                            elif isinstance(val, hou.Quaternion):
                                val = list(val.components())
                            fields[field_name] = val
                        except (hou.OperationFailed, AttributeError) as e:
                            logger.debug("Unreadable field '%s': %s", field_name, e)
                            fields[field_name] = "<unreadable>"
                except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
                    logger.debug("Failed to read record fields: %s", e)
                record_list.append(fields)
            # If only one record, flatten out of the list
            if len(record_list) == 1:
                result[record_type] = record_list[0]
            else:
                result[record_type] = record_list
    except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
        logger.debug("Failed to read record types: %s", e)
    return result


###### Handlers


def _get_simulation_info(node_path: str) -> dict:
    """Get DOP network simulation state information."""
    node = _get_dop_node(node_path)
    sim = _get_simulation(node_path)

    objects = sim.objects()
    object_count = len(objects) if objects is not None else 0

    # Memory usage (bytes) -- may not be available in all Houdini versions
    memory_bytes = 0
    try:
        memory_bytes = sim.memoryUsage()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read simulation memory usage: %s", e)

    # Check if currently simulating
    is_simulating = False
    try:
        is_simulating = node.isSimulating()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read isSimulating: %s", e)

    # Timestep info
    timestep = None
    try:
        timestep = sim.timestep()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read timestep: %s", e)

    return {
        "node_path": node_path,
        "node_type": node.type().name(),
        "simulation_time": sim.time(),
        "timestep": timestep,
        "object_count": object_count,
        "memory_usage_bytes": memory_bytes,
        "memory_usage_mb": round(memory_bytes / (1024 * 1024), 2) if memory_bytes else 0,
        "is_simulating": is_simulating,
        "current_frame": hou.frame(),
    }


def _list_dop_objects(node_path: str) -> dict:
    """List all DOP objects and their types in the simulation."""
    sim = _get_simulation(node_path)
    objects = sim.objects()

    object_list = []
    if objects is not None:
        for obj in objects:
            entry = {
                "name": obj.name(),
                "object_id": obj.objid(),
            }
            try:
                entry["data_type"] = obj.dataType()
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read data_type for DOP object: %s", e)
                entry["data_type"] = "unknown"
            try:
                entry["record_types"] = list(obj.recordTypes())
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read record_types for DOP object: %s", e)
                entry["record_types"] = []
            object_list.append(entry)

    return {
        "node_path": node_path,
        "object_count": len(object_list),
        "objects": object_list,
    }


def _get_dop_object(node_path: str, object_name: str) -> dict:
    """Get detailed data for a specific simulation object."""
    sim = _get_simulation(node_path)

    dop_obj = sim.findObject(object_name)
    if dop_obj is None:
        raise hou.OperationFailed(
            f"DOP object '{object_name}' not found in simulation at '{node_path}'."
        )

    result = {
        "node_path": node_path,
        "object_name": dop_obj.name(),
        "object_id": dop_obj.objid(),
    }

    try:
        result["data_type"] = dop_obj.dataType()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read data_type for DOP object '%s': %s", object_name, e)
        result["data_type"] = "unknown"

    # Extract all records
    result["records"] = _records_to_dict(dop_obj)

    # Build subdata tree
    result["subdata_tree"] = _subdata_tree(dop_obj)

    return result


def _get_dop_field(
    node_path: str,
    object_name: str,
    data_path: str,
    field_name: str,
) -> dict:
    """Read a specific field value from a DOP record."""
    sim = _get_simulation(node_path)

    dop_obj = sim.findObject(object_name)
    if dop_obj is None:
        raise hou.OperationFailed(
            f"DOP object '{object_name}' not found in simulation at '{node_path}'."
        )

    # Navigate to the subdata at data_path
    data = dop_obj
    if data_path:
        data = dop_obj.findSubData(data_path)
        if data is None:
            raise hou.OperationFailed(
                f"Subdata path '{data_path}' not found on object '{object_name}'."
            )

    # Try to read the field from the first record of each record type
    value = None
    found = False
    try:
        for record_type in data.recordTypes():
            records = data.records(record_type)
            for rec in records:
                if field_name in rec.fieldNames():
                    value = rec.field(field_name)
                    found = True
                    break
            if found:
                break
    except Exception as e:
        raise hou.OperationFailed(
            f"Error reading field '{field_name}' at data path '{data_path}': {readable_message(e)}"
        ) from e

    if not found:
        raise hou.OperationFailed(
            f"Field '{field_name}' not found in data at path '{data_path}' "
            f"on object '{object_name}'."
        )

    # Convert hou types
    if isinstance(value, (hou.Vector2, hou.Vector3, hou.Vector4)):
        value = list(value)
    elif isinstance(value, (hou.Matrix3, hou.Matrix4)):
        value = [list(row) for row in value.asTupleOfTuples()]
    elif isinstance(value, hou.Quaternion):
        value = list(value.components())

    return {
        "node_path": node_path,
        "object_name": object_name,
        "data_path": data_path,
        "field_name": field_name,
        "value": value,
    }


def _relationship_names(obj_records: dict, record_type: str) -> list:
    """Relationship names an object lists under one of its Rel* records."""
    found = obj_records.get(record_type)
    if found is None:
        return []
    if isinstance(found, dict):
        found = [found]
    return [f.get("relname") for f in found if isinstance(f, dict) and f.get("relname")]


def _get_dop_relationships(node_path: str) -> dict:
    """List relationships between DOP objects.

    Relationships belong to the simulation, not to an object (``hou.DopObject``
    has no ``relationships()``), so they come from ``sim.relationships()`` and
    each object's ``RelInGroup``/``RelInAffectors`` records say who is in them.
    """
    sim = _get_simulation(node_path)

    members: dict = {}
    for obj in sim.objects() or []:
        try:
            recs = _records_to_dict(obj)
        except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
            logger.debug("Could not read records for object: %s", e)
            continue
        for key, bucket in (("RelInGroup", "group"), ("RelInAffectors", "affectors")):
            for relname in _relationship_names(recs, key):
                members.setdefault(relname, {"group": [], "affectors": []})[bucket].append(
                    obj.name()
                )

    relationships = []
    for rel in sim.relationships() or []:
        try:
            entry = {"name": rel.name()}
            try:
                entry["type"] = rel.dataType()
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read relationship data_type: %s", e)
                entry["type"] = "unknown"
            try:
                entry["records"] = _records_to_dict(rel)
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read relationship records: %s", e)
                entry["records"] = {}
            found = members.get(entry["name"], {"group": [], "affectors": []})
            entry["objects_in_group"] = found["group"]
            entry["objects_in_affectors"] = found["affectors"]
            relationships.append(entry)
        except (hou.OperationFailed, hou.ObjectWasDeleted) as e:
            logger.debug("Could not read a relationship: %s", e)
            continue

    return {
        "node_path": node_path,
        "relationship_count": len(relationships),
        "relationships": relationships,
    }


def _step_simulation(node_path: str, steps: int = 1) -> dict:
    """Advance the simulation by N frames."""
    _get_dop_node(node_path)
    # Ensure the node is a DOP network with a simulation
    _get_simulation(node_path)

    if steps < 1:
        raise hou.OperationFailed("steps must be >= 1")

    start_frame = hou.frame()
    for _ in range(steps):
        hou.setFrame(hou.frame() + 1)

    end_frame = hou.frame()

    return {
        "node_path": node_path,
        "steps_advanced": steps,
        "start_frame": start_frame,
        "end_frame": end_frame,
    }


def _reset_simulation(node_path: str) -> dict:
    """Reset the simulation to its initial state."""
    node = _get_dop_node(node_path)
    # hou.DopSimulation has no clear(): the AttributeError went to a debug log
    # and this reported simulation_reset after only moving the frame. The
    # reset is the network's own Reset Simulation button ("resimulate", also
    # the name on the SOP-level solvers).
    owner = _reset_button_owner(node)
    if owner is None:
        raise ValueError(f"No Reset Simulation button on {node_path} or any of its parents.")
    owner.parm("resimulate").pressButton()

    start_frame, _ = hou.playbar.frameRange()
    hou.setFrame(start_frame)

    return {
        "node_path": node_path,
        "reset_node": owner.path(),
        "reset_to_frame": start_frame,
        "status": "simulation_reset",
    }


def _get_sim_memory_usage(node_path: str) -> dict:
    """Get a detailed memory breakdown for the simulation."""
    _get_dop_node(node_path)
    sim = _get_simulation(node_path)

    # Total memory
    total_bytes = 0
    try:
        total_bytes = sim.memoryUsage()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read total memory usage: %s", e)

    # Per-object memory breakdown
    objects = sim.objects()
    per_object = []
    if objects is not None:
        for obj in objects:
            obj_mem = 0
            try:
                obj_mem = obj.memoryUsage()
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read memory for object '%s': %s", obj.name(), e)
            per_object.append(
                {
                    "name": obj.name(),
                    "memory_bytes": obj_mem,
                    "memory_mb": round(obj_mem / (1024 * 1024), 2) if obj_mem else 0,
                }
            )

    # Sort by memory usage descending
    per_object.sort(key=lambda x: x["memory_bytes"], reverse=True)

    return {
        "node_path": node_path,
        "total_memory_bytes": total_bytes,
        "total_memory_mb": round(total_bytes / (1024 * 1024), 2) if total_bytes else 0,
        "object_count": len(per_object),
        "per_object": per_object,
        "current_frame": hou.frame(),
        "simulation_time": sim.time(),
    }


###### Registration

register_handler("dops.get_simulation_info", _get_simulation_info)
register_handler("dops.list_dop_objects", _list_dop_objects)
register_handler("dops.get_dop_object", _get_dop_object)
register_handler("dops.get_dop_field", _get_dop_field)
register_handler("dops.get_dop_relationships", _get_dop_relationships)
register_handler("dops.step_simulation", _step_simulation)
register_handler("dops.reset_simulation", _reset_simulation)
register_handler("dops.get_sim_memory_usage", _get_sim_memory_usage)
