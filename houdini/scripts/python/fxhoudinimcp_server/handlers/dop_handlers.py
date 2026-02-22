"""DOP (dynamics/simulation) handlers for FXHoudini-MCP.

Provides tools for inspecting and controlling DOP simulations:
simulation info, object listing, field reading, relationships,
stepping, resetting, and memory usage.
"""

from __future__ import annotations

# Built-in
import logging

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler

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
            f"Node '{node_path}' does not have a simulation. "
            "Ensure it is a DOP network node."
        )
    return sim


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
            f"Error reading field '{field_name}' at data path '{data_path}': {e}"
        )

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


def _get_dop_relationships(node_path: str) -> dict:
    """List relationships between DOP objects."""
    sim = _get_simulation(node_path)
    objects = sim.objects()

    relationships = []
    if objects is not None:
        for obj in objects:
            try:
                rels = obj.relationships()
                if rels is None:
                    continue
                for rel in rels:
                    entry = {
                        "name": rel.name(),
                    }
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
                    # Try to find objects involved
                    try:
                        entry["object_names"] = [
                            o.name() for o in rel.objects()
                        ]
                    except (hou.OperationFailed, AttributeError) as e:
                        logger.debug("Could not read relationship objects: %s", e)
                        entry["source_object"] = obj.name()
                    relationships.append(entry)
            except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
                logger.debug("Could not read relationships for object: %s", e)
                continue

    return {
        "node_path": node_path,
        "relationship_count": len(relationships),
        "relationships": relationships,
    }


def _step_simulation(node_path: str, steps: int = 1) -> dict:
    """Advance the simulation by N frames."""
    node = _get_dop_node(node_path)
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
    sim = _get_simulation(node_path)

    # Attempt to clear the simulation cache
    try:
        sim.clear()
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not clear simulation cache: %s", e)

    # Also reset the frame to the start of the global frame range
    start_frame, _ = hou.playbar.frameRange()
    hou.setFrame(start_frame)

    return {
        "node_path": node_path,
        "reset_to_frame": start_frame,
        "status": "simulation_reset",
    }


def _get_sim_memory_usage(node_path: str) -> dict:
    """Get a detailed memory breakdown for the simulation."""
    node = _get_dop_node(node_path)
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
            per_object.append({
                "name": obj.name(),
                "memory_bytes": obj_mem,
                "memory_mb": round(obj_mem / (1024 * 1024), 2) if obj_mem else 0,
            })

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
