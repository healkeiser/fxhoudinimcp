"""COP (Copernicus) handlers for FXHoudini-MCP.

Provides tools for querying and manipulating COP nodes in Houdini 20.5+
Copernicus compositing networks.
"""

from __future__ import annotations

# Built-in
import contextlib
import logging

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler
from fxhoudinimcp_server.errors import readable_message
from fxhoudinimcp_server.handlers.node_handlers import _refuse_taken_name
from fxhoudinimcp_server.ui import focus_network_editor as _focus_network_editor

logger = logging.getLogger(__name__)


###### Helpers


def _get_cop_node(node_path: str) -> hou.Node:
    """Return a COP node, or say why the given node is not one.

    This checked only existence despite its name, so every cops.* command trusted
    it and answered about whatever it was handed. get_cop_info on a box SOP came
    back success with category "Sop", x_resolution None and planes [] -- it knew
    the node was not a COP and reported an image summary anyway. A caller reading
    "x_resolution: None" has no way to tell a wrong node type from an image with no
    resolution, which is worse than an error.
    """
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    category = node.type().category().name()
    if category == "Cop":
        return node
    # A COP network container is accepted: some callers pass the copnet.
    children = node.childTypeCategory()
    if children is not None and children.name() == "Cop":
        return node
    raise ValueError(
        f"{node_path} is a {category} node ({node.type().name()}), not a COP. "
        f"COP tools work on nodes inside a copnet or /img."
    )


###### cops.get_cop_info


def get_cop_info(node_path: str) -> dict:
    """Return information about a COP node.

    Includes output type, data format, and resolution info.

    Args:
        node_path: Path to the COP node.
    """
    node = _get_cop_node(node_path)

    info = {
        "node_path": node.path(),
        "node_type": node.type().name(),
        "category": node.type().category().name(),
    }

    # Resolution and format info
    try:
        # COP2 nodes have xRes/yRes methods
        info["x_resolution"] = node.xRes()
        info["y_resolution"] = node.yRes()
    except AttributeError:
        info["x_resolution"] = None
        info["y_resolution"] = None

    # Depth / data format
    try:
        info["depth"] = str(node.depth())
    except AttributeError:
        info["depth"] = None

    # Number of planes/layers
    try:
        planes = node.planes()
        info["planes"] = list(planes) if planes else []
    except AttributeError:
        info["planes"] = []

    # Sequence info
    try:
        info["sequence_start"] = node.sequenceStartFrame()
        info["sequence_end"] = node.sequenceEndFrame()
        info["sequence_length"] = node.sequenceFrameLength()
    except AttributeError:
        info["sequence_start"] = None
        info["sequence_end"] = None
        info["sequence_length"] = None

    # Input/output counts
    try:
        info["num_inputs"] = len(node.inputs())
        info["num_outputs"] = len(node.outputs())
    except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
        logger.debug("Could not read input/output counts for '%s': %s", node_path, e)
        info["num_inputs"] = 0
        info["num_outputs"] = 0

    # Errors and warnings
    try:
        errors = node.errors()
        warnings = node.warnings()
        info["errors"] = list(errors) if errors else []
        info["warnings"] = list(warnings) if warnings else []
    except (hou.OperationFailed, hou.ObjectWasDeleted, AttributeError) as e:
        logger.debug("Could not read errors/warnings for '%s': %s", node_path, e)
        info["errors"] = []
        info["warnings"] = []

    return info


###### cops.get_cop_geometry


def get_cop_geometry(node_path: str, output_index: int = 0) -> dict:
    """Get geometry representation from a COP node.

    In Copernicus (Houdini 20.5+), COP nodes can output geometry data.

    Args:
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
    """
    node = _get_cop_node(node_path)

    try:
        geo = node.geometry(output_index)
    except Exception as e:
        raise ValueError(
            f"Failed to get geometry from COP node {node_path} at output {output_index}: {readable_message(e)}"
        ) from e

    if geo is None:
        return {
            "node_path": node.path(),
            "output_index": output_index,
            "has_geometry": False,
            "message": "No geometry data at this output.",
        }

    # Gather geometry info
    result = {
        "node_path": node.path(),
        "output_index": output_index,
        "has_geometry": True,
        "num_points": geo.intrinsicValue("pointcount")
        if geo.intrinsicValue("pointcount") is not None
        else len(geo.points()),
        "num_prims": geo.intrinsicValue("primitivecount")
        if geo.intrinsicValue("primitivecount") is not None
        else len(geo.prims()),
        "num_vertices": geo.intrinsicValue("vertexcount")
        if geo.intrinsicValue("vertexcount") is not None
        else len(geo.vertices()),
    }

    # Point attributes
    try:
        point_attribs = []
        for attrib in geo.pointAttribs():
            point_attribs.append(
                {
                    "name": attrib.name(),
                    "type": str(attrib.dataType()),
                    "size": attrib.size(),
                }
            )
        result["point_attributes"] = point_attribs
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read point attributes for '%s': %s", node_path, e)
        result["point_attributes"] = []

    # Primitive attributes
    try:
        prim_attribs = []
        for attrib in geo.primAttribs():
            prim_attribs.append(
                {
                    "name": attrib.name(),
                    "type": str(attrib.dataType()),
                    "size": attrib.size(),
                }
            )
        result["primitive_attributes"] = prim_attribs
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read primitive attributes for '%s': %s", node_path, e)
        result["primitive_attributes"] = []

    # Bounding box
    try:
        bbox = geo.boundingBox()
        result["bounding_box"] = {
            "min": list(bbox.minvec()),
            "max": list(bbox.maxvec()),
        }
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read bounding box for '%s': %s", node_path, e)
        result["bounding_box"] = None

    return result


###### cops.get_cop_layer


def get_cop_layer(
    node_path: str,
    output_index: int = 0,
    wire: int | str | None = None,
    wire_sum: bool = False,
) -> dict:
    """Get image layer data information from a COP node.

    A cable output says so: ``is_cable`` and ``wires`` (name, data type and
    each wire's own layer summary). It used to read back as its first wire,
    with nothing to say the other wires existed.

    Args:
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
        wire: On a cable output, the wire whose layer ``copernicus_layer``
            describes (index or name); default the first.
        wire_sum: On a cable output, min/max/average of the per-pixel sum of
            its one-channel wires ("the weights sum to 1").
    """
    node = _get_cop_node(node_path)

    result = {
        "node_path": node.path(),
        "output_index": output_index,
    }

    # Try to get layer info via planes/components
    try:
        planes = node.planes()
        layer_info = []
        for plane in planes:
            components = node.components(plane)
            layer_info.append(
                {
                    "plane_name": plane,
                    "components": list(components) if components else [],
                    "depth": str(node.planeDepth(plane)) if hasattr(node, "planeDepth") else None,
                }
            )
        result["layers"] = layer_info
        result["layer_count"] = len(layer_info)
    except AttributeError:
        result["layers"] = []
        result["layer_count"] = 0

    # Resolution
    try:
        result["x_resolution"] = node.xRes()
        result["y_resolution"] = node.yRes()
    except AttributeError:
        result["x_resolution"] = None
        result["y_resolution"] = None

    # Copernicus: the layer itself. This used to answer only "available: true",
    # with no resolution and no values, so a COP chain could not be checked
    # without a screenshot of a visualizer that is not the data.
    try:
        layer_data = node.layer(output_index)
    except Exception:
        layer_data = None
    cable = _output_cable(node, output_index)
    if cable is None and (wire is not None or wire_sum):
        raise ValueError(
            f"Output {output_index} of {node.path()} is not a cable: wire and wire_sum "
            "read the wires of a cable."
        )
    if cable is not None:
        index = 0 if wire is None else _resolve_wire(cable, wire)
        layer_data = cable.layerByIndex(index)
        result["is_cable"] = True
        result["wire_count"] = cable.wireCount()
        result["wires"] = _wire_entries(cable)
        result["layer_read"] = {"wire": index, "name": cable.wireName(index)}
        if wire_sum:
            result["wire_sum"] = _wire_sum(cable)
    result["copernicus_layer"] = (
        _layer_summary(layer_data) if layer_data is not None else {"available": False}
    )
    if layer_data is not None and result.get("x_resolution") is None:
        resolution = result["copernicus_layer"].get("resolution") or [None, None]
        result["x_resolution"], result["y_resolution"] = resolution[:2]
    return result


def _layer_summary(layer) -> dict:
    """Resolution, channels and per-channel value range of a Copernicus layer.

    computeMin/Max/Average run in Houdini, so no pixel crosses into Python.
    """
    summary: dict = {"available": True}
    with contextlib.suppress(Exception):
        summary["resolution"] = list(layer.bufferResolution())
    with contextlib.suppress(Exception):
        summary["storage"] = str(layer.storageType()).rsplit(".", 1)[-1]
    with contextlib.suppress(Exception):
        summary["is_constant"] = bool(layer.isConstant())
    channels = 0
    with contextlib.suppress(Exception):
        channels = int(layer.channelCount())
    summary["channels"] = channels
    ranges = []
    for channel in range(min(channels, 4)):
        with contextlib.suppress(Exception):
            ranges.append(
                {
                    "min": layer.computeMin(channel),
                    "max": layer.computeMax(channel),
                    "mean": layer.computeAverage(channel),
                }
            )
    if ranges:
        summary["channel_ranges"] = ranges
    return summary


###### cops.get_cop_layer: cables


def _output_cable(node: hou.Node, output_index: int):
    """The output's CopCable when it carries a cable, else None.

    HOM has no "is a cable" flag: a plain layer output is a cable of one
    wire, often named (a Fractal Noise's wire is "noise", and a Blur passes
    it on), and outputDataTypes() answers Mono for a cablepack. More than
    one wire is a cable; a cable of one wire reads as that wire's layer.
    """
    try:
        cable = node.cable(output_index)
        count = cable.wireCount()
    except Exception:
        return None
    return cable if count > 1 else None


def _wire_entries(cable) -> list[dict]:
    wires = []
    for index in range(cable.wireCount()):
        entry: dict = {"index": index, "name": cable.wireName(index)}
        with contextlib.suppress(Exception):
            entry["data_type"] = str(cable.wireDataTypeByIndex(index)).rsplit(".", 1)[-1]
        layer = None
        with contextlib.suppress(Exception):
            layer = cable.layerByIndex(index)
        if layer is not None:
            entry["layer"] = _layer_summary(layer)
        wires.append(entry)
    return wires


def _resolve_wire(cable, wire) -> int:
    names = list(cable.wireNames())
    if isinstance(wire, str) and not wire.lstrip("-").isdigit():
        if wire not in names:
            raise ValueError(f"No wire named '{wire}' in this cable. Wires: {names}")
        if names.count(wire) > 1:
            raise ValueError(
                f"{names.count(wire)} wires are named '{wire}'; give its index. Wires: {names}"
            )
        return names.index(wire)
    index = int(wire)
    if not 0 <= index < len(names):
        raise ValueError(f"Wire index {index} out of range: the cable has {len(names)} wires.")
    return index


def _wire_sum(cable) -> dict:
    """min/max/average of the per-pixel sum of a cable's one-channel wires.

    For checks such as "the weights sum to 1"; wires that are not Mono
    (an ID, a geometry) or of another resolution are named in `skipped`,
    not added. Any storage is read as Float32, so 8- and 16-bit masks count.
    """
    import numpy

    total, summed, skipped, resolution = None, [], [], None
    for index in range(cable.wireCount()):
        name = cable.wireName(index) or f"#{index}"
        try:
            # An ID wire is one Int32 channel too, but not a weight.
            data_type = str(cable.wireDataTypeByIndex(index)).rsplit(".", 1)[-1]
            if data_type != "Mono":
                skipped.append({"wire": name, "why": data_type})
                continue
            layer = cable.layerByIndex(index)
            res = tuple(layer.bufferResolution())
            if resolution is not None and res != resolution:
                skipped.append({"wire": name, "why": f"resolution {list(res)}"})
                continue
            values = numpy.frombuffer(
                layer.allBufferElements(hou.imageLayerStorageType.Float32, 1), dtype="float32"
            )
        except Exception as exc:
            skipped.append({"wire": name, "why": readable_message(exc)})
            continue
        resolution = res
        values = values.astype("float64")
        total = values if total is None else total + values
        summed.append(name)
    result: dict = {"wires": summed}
    if total is not None:
        result.update(
            min=float(total.min()),
            max=float(total.max()),
            average=float(total.mean()),
            resolution=list(resolution),
        )
    if skipped:
        result["skipped"] = skipped
    return result


###### cops.create_cop_node


def create_cop_node(
    parent_path: str,
    cop_type: str,
    name: str = None,
) -> dict:
    """Create a Copernicus COP node.

    Args:
        parent_path: Path to the parent COP network.
        cop_type: The COP node type to create (e.g. "file", "vopcop2gen").
        name: Optional explicit name for the node.
    """
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Parent node not found: {parent_path}")
    if name:
        _refuse_taken_name(parent, name)

    try:
        node = parent.createNode(cop_type, name) if name else parent.createNode(cop_type)
    except hou.OperationFailed as e:
        raise ValueError(
            f"Failed to create COP node of type '{cop_type}' under {parent_path}: {readable_message(e)}"
        ) from e

    _focus_network_editor(node)

    return {
        "success": True,
        "node_path": node.path(),
        "node_type": node.type().name(),
        "node_name": node.name(),
    }


###### cops.set_cop_flags


def set_cop_flags(
    node_path: str,
    display: bool = None,
    export_flag: bool = None,
    compress: bool = None,
) -> dict:
    """Set flags on a COP node.

    Args:
        node_path: Path to the COP node.
        display: Set the display flag.
        export_flag: Set the render/export flag.
        compress: Set the compress flag.
    """
    node = _get_cop_node(node_path)

    flags_set = {}

    if display is not None:
        try:
            node.setDisplayFlag(display)
            flags_set["display"] = display
        except Exception as e:
            flags_set["display_error"] = str(e)

    if export_flag is not None:
        # Copernicus COPs have setExportFlag, not setRenderFlag (COP2's name),
        # so this always failed while the call still said success.
        setter = "setExportFlag" if hasattr(node, "setExportFlag") else "setRenderFlag"
        try:
            getattr(node, setter)(export_flag)
            flags_set["export_flag"] = export_flag
        except Exception as e:
            flags_set["export_flag_error"] = str(e)

    if compress is not None:
        try:
            node.setCompressFlag(compress)
            flags_set["compress"] = compress
        except (AttributeError, Exception) as e:
            flags_set["compress_error"] = str(e)

    return {
        "success": not any(key.endswith("_error") for key in flags_set),
        "node_path": node.path(),
        "flags_set": flags_set,
    }


###### cops.list_cop_node_types


def list_cop_node_types(filter: str = None) -> dict:
    """List available COP node types.

    Args:
        filter: Optional substring filter for node type names.
    """
    # Copernicus ("Cop", Houdini 20.5+) is what create_cop_node creates
    # inside a copnet; fall back to legacy Cop2 on older builds.
    cop_types = []

    try:
        category = hou.nodeTypeCategories().get("Cop") or hou.cop2NodeTypeCategory()
        for type_name, node_type in category.nodeTypes().items():
            if filter and filter.lower() not in type_name.lower():
                continue
            type_info = {
                "name": type_name,
                "label": node_type.description(),
            }
            try:
                type_info["min_inputs"] = node_type.minNumInputs()
                type_info["max_inputs"] = node_type.maxNumInputs()
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not read input counts for COP type '%s': %s", type_name, e)
                type_info["min_inputs"] = None
                type_info["max_inputs"] = None
            cop_types.append(type_info)
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not enumerate COP2 node types: %s", e)

    # Sort by name
    cop_types.sort(key=lambda x: x["name"])

    # Capped with a count, like list_node_types; the icon path each row used
    # to carry is dropped (get_node_info drops it too).
    return {
        "cop_type_count": len(cop_types),
        "truncated": len(cop_types) > 200,
        "cop_types": cop_types[:200],
        "filter_applied": filter,
    }


###### cops.get_cop_vdb


def get_cop_vdb(node_path: str, output_index: int = 0) -> dict:
    """Get VDB data information from a COP node.

    In Copernicus, COP nodes can work with volumetric (VDB) data.

    Args:
        node_path: Path to the COP node.
        output_index: Output connector index (default 0).
    """
    node = _get_cop_node(node_path)

    try:
        geo = node.geometry(output_index)
    except Exception as e:
        raise ValueError(
            f"Failed to get geometry from COP node {node_path} at output {output_index}: {readable_message(e)}"
        ) from e

    if geo is None:
        return {
            "node_path": node.path(),
            "output_index": output_index,
            "has_vdb": False,
            "message": "No geometry data at this output.",
        }

    # Look for VDB primitives
    vdb_prims = []
    try:
        for prim in geo.prims():
            if prim.type() == hou.primType.VDB:
                vdb_info = {
                    "name": prim.attribValue("name")
                    if prim.attribValue("name")
                    else f"vdb_{prim.number()}",
                    "prim_index": prim.number(),
                    "type": str(prim.type()),
                }
                try:
                    vdb_info["data_type"] = str(prim.dataType())
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read VDB data_type: %s", e)
                    vdb_info["data_type"] = None
                try:
                    vdb_info["voxel_count"] = prim.voxelCount()
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read VDB voxel_count: %s", e)
                    vdb_info["voxel_count"] = None
                try:
                    vdb_info["active_voxel_count"] = prim.activeVoxelCount()
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read VDB active_voxel_count: %s", e)
                    vdb_info["active_voxel_count"] = None
                try:
                    bbox = prim.boundingBox()
                    vdb_info["bounding_box"] = {
                        "min": list(bbox.minvec()),
                        "max": list(bbox.maxvec()),
                    }
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read VDB bounding box: %s", e)
                    vdb_info["bounding_box"] = None
                try:
                    vdb_info["transform"] = [
                        list(row) for row in prim.transform().asTupleOfTuples()
                    ]
                except (hou.OperationFailed, AttributeError) as e:
                    logger.debug("Could not read VDB transform: %s", e)
                    vdb_info["transform"] = None

                vdb_prims.append(vdb_info)
    except Exception as e:
        return {
            "node_path": node.path(),
            "output_index": output_index,
            "has_vdb": False,
            "error": str(e),
        }

    return {
        "node_path": node.path(),
        "output_index": output_index,
        "has_vdb": len(vdb_prims) > 0,
        "vdb_count": len(vdb_prims),
        "vdb_primitives": vdb_prims,
    }


###### Registration

register_handler("cops.get_cop_info", get_cop_info)
register_handler("cops.get_cop_geometry", get_cop_geometry)
register_handler("cops.get_cop_layer", get_cop_layer)
register_handler("cops.create_cop_node", create_cop_node)
register_handler("cops.set_cop_flags", set_cop_flags)
register_handler("cops.list_cop_node_types", list_cop_node_types)
register_handler("cops.get_cop_vdb", get_cop_vdb)
