"""PDG/TOPs handlers for FXHoudini-MCP.

Provides tools for querying and controlling TOP networks, work items,
schedulers, and PDG graph cooking in Houdini.
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

def _get_top_node(node_path: str) -> hou.Node:
    """Return a TOP node or raise if not found."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _get_pdg_node(node: hou.Node):
    """Return the underlying PDG node for a TOP node."""
    pdg_node = node.getPDGNode()
    if pdg_node is None:
        raise ValueError(
            f"Node {node.path()} does not have a PDG node. "
            "It may not be a TOP node or the graph has not been generated."
        )
    return pdg_node


def _get_graph_context(node: hou.Node):
    """Return the PDG graph context for a TOP node."""
    pdg_node = node.getPDGNode()
    if pdg_node is not None:
        ctx = pdg_node.context
        if ctx is not None:
            return ctx
    # Fallback: try to find the graph context from the parent topnet
    parent = node
    while parent is not None:
        if parent.type().category().name() == "TopNet" or parent.type().name() == "topnet":
            try:
                contexts = hou.pdg.GraphContext.contexts()
                for ctx in contexts:
                    if ctx.name == parent.name():
                        return ctx
                # Return the first context if name match fails
                if contexts:
                    return contexts[0]
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not retrieve PDG graph contexts: %s", e)
            break
        parent = parent.parent()
    raise ValueError(
        f"Cannot find PDG graph context for node {node.path()}. "
        "Ensure the node is inside a TOP network."
    )


def _work_item_state_name(state) -> str:
    """Convert a PDG work item state enum to a readable string."""
    state_map = {
        0: "undefined",
        1: "uncooked",
        2: "waiting",
        3: "scheduled",
        4: "cooking",
        5: "cooked_success",
        6: "cooked_cache",
        7: "cooked_fail",
        8: "cooked_cancel",
        9: "dirty",
    }
    try:
        return state_map.get(int(state), str(state))
    except (ValueError, TypeError) as e:
        logger.debug("Could not convert work item state to int: %s", e)
        return str(state)


def _work_item_to_dict(work_item) -> dict:
    """Convert a PDG work item to a plain dict."""
    info = {
        "id": work_item.id,
        "index": work_item.index,
        "name": work_item.name,
        "state": _work_item_state_name(work_item.state),
        "frame": work_item.frame,
        "priority": work_item.priority,
        "batch_index": work_item.batchIndex,
    }

    # Collect attributes
    try:
        attribs = {}
        for attrib in work_item.attribs:
            try:
                attribs[attrib.name] = {
                    "type": str(attrib.type),
                    "values": list(attrib.values),
                }
            except (AttributeError, TypeError) as e:
                logger.debug("Could not read work item attribute values for '%s': %s", attrib.name, e)
                attribs[attrib.name] = {"type": str(attrib.type), "values": []}
        info["attributes"] = attribs
    except (AttributeError, TypeError) as e:
        logger.debug("Could not read work item attributes: %s", e)
        info["attributes"] = {}

    # Collect output files
    try:
        info["output_files"] = [
            {"path": rf.path, "tag": rf.tag, "hash": rf.hash}
            for rf in work_item.resultData
        ]
    except (AttributeError, TypeError) as e:
        logger.debug("Could not read work item output files: %s", e)
        info["output_files"] = []

    return info


###### tops.get_top_network_info

def get_top_network_info(node_path: str) -> dict:
    """Return an overview of a TOP network.

    Provides node count, scheduler info, and cook state.

    Args:
        node_path: Path to a TOP network node (topnet) or a TOP node inside one.
    """
    node = _get_top_node(node_path)

    # If pointing at a topnet, enumerate children; otherwise use parent
    if node.type().category().name() == "TopNet" or node.type().name() == "topnet":
        topnet = node
    else:
        topnet = node.parent()
        if topnet is None or (
            topnet.type().category().name() != "TopNet"
            and topnet.type().name() != "topnet"
        ):
            topnet = node

    children = topnet.children()
    top_nodes = []
    scheduler_nodes = []

    for child in children:
        child_type = child.type().name()
        child_info = {
            "name": child.name(),
            "path": child.path(),
            "type": child_type,
        }
        try:
            errors = child.errors()
            child_info["has_errors"] = bool(errors)
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not read errors for child '%s': %s", child.name(), e)
            child_info["has_errors"] = False

        # Determine if it is a scheduler
        try:
            if hasattr(child, "isScheduler") and child.isScheduler():
                scheduler_nodes.append(child_info)
            elif "scheduler" in child_type.lower():
                scheduler_nodes.append(child_info)
            else:
                top_nodes.append(child_info)
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not determine scheduler status for '%s': %s", child.name(), e)
            top_nodes.append(child_info)

    # Cook state
    cook_state = "unknown"
    try:
        contexts = hou.pdg.GraphContext.contexts()
        for ctx in contexts:
            if ctx.name == topnet.name():
                cook_state = str(ctx.cookState)
                break
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read cook state for '%s': %s", topnet.name(), e)

    return {
        "network_path": topnet.path(),
        "network_type": topnet.type().name(),
        "top_node_count": len(top_nodes),
        "scheduler_count": len(scheduler_nodes),
        "top_nodes": top_nodes,
        "scheduler_nodes": scheduler_nodes,
        "cook_state": cook_state,
    }


###### tops.cook_top_node

def cook_top_node(
    node_path: str,
    block: bool = True,
    generate_only: bool = False,
) -> dict:
    """Cook a TOP node to execute its work items.

    Args:
        node_path: Path to the TOP node to cook.
        block: If True, wait for cooking to complete before returning.
        generate_only: If True, only generate work items without cooking.
    """
    node = _get_top_node(node_path)

    if generate_only:
        try:
            node.generateStaticWorkItems(block)
        except AttributeError:
            # Fallback for older Houdini versions
            pdg_node = _get_pdg_node(node)
            pdg_node.generateStaticItems()
        return {
            "success": True,
            "node_path": node.path(),
            "action": "generate_only",
            "message": "Static work items generated.",
        }

    if block:
        try:
            node.cookWorkItems(block=True)
        except AttributeError:
            # Fallback: use executeGraph
            node.executeGraph(False, False)
    else:
        try:
            node.executeGraph(False, False)
        except Exception as e:
            raise ValueError(f"Failed to start non-blocking cook: {e}")

    # Gather result info
    result = {
        "success": True,
        "node_path": node.path(),
        "action": "cook",
        "blocking": block,
    }

    try:
        pdg_node = _get_pdg_node(node)
        work_items = pdg_node.workItems
        result["work_item_count"] = len(work_items)
    except (ValueError, AttributeError) as e:
        logger.debug("Could not read work item count: %s", e)
        result["work_item_count"] = None

    try:
        errors = node.errors()
        result["errors"] = list(errors) if errors else []
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not read node errors: %s", e)
        result["errors"] = []

    return result


###### tops.cancel_top_cook

def cancel_top_cook(node_path: str) -> dict:
    """Cancel any active cooking on a TOP network.

    Args:
        node_path: Path to a TOP node or TOP network.
    """
    node = _get_top_node(node_path)

    try:
        ctx = _get_graph_context(node)
        ctx.cancelCook()
    except Exception as e:
        raise ValueError(f"Failed to cancel cook: {e}")

    return {
        "success": True,
        "node_path": node.path(),
        "message": "Cook cancellation requested.",
    }


###### tops.pause_top_cook

def pause_top_cook(node_path: str) -> dict:
    """Pause cooking on a TOP network.

    Args:
        node_path: Path to a TOP node or TOP network.
    """
    node = _get_top_node(node_path)

    try:
        ctx = _get_graph_context(node)
        ctx.pauseCook()
    except Exception as e:
        raise ValueError(f"Failed to pause cook: {e}")

    return {
        "success": True,
        "node_path": node.path(),
        "message": "Cook paused.",
    }


###### tops.dirty_work_items

def dirty_work_items(node_path: str, remove_outputs: bool = False) -> dict:
    """Dirty (invalidate) work items on a TOP node so they can be regenerated.

    Args:
        node_path: Path to the TOP node.
        remove_outputs: If True, also remove output files from disk.
    """
    node = _get_top_node(node_path)

    try:
        pdg_node = _get_pdg_node(node)
        pdg_node.dirty(remove_outputs)
    except (ValueError, AttributeError, hou.OperationFailed) as e:
        logger.debug("Primary dirty failed, trying fallback: %s", e)
        # Fallback: try dirtying via the node itself
        try:
            node.dirtyAllWorkItems(remove_outputs)
        except AttributeError:
            # Last resort: dirty through graph context
            ctx = _get_graph_context(node)
            ctx.dirty(remove_outputs)

    return {
        "success": True,
        "node_path": node.path(),
        "remove_outputs": remove_outputs,
        "message": "Work items dirtied.",
    }


###### tops.get_work_item_states

def get_work_item_states(node_path: str) -> dict:
    """Return the count of work items in each state for a TOP node.

    States include: waiting, scheduled, cooking, cooked_success,
    cooked_fail, cooked_cancel, etc.

    Args:
        node_path: Path to the TOP node.
    """
    node = _get_top_node(node_path)
    pdg_node = _get_pdg_node(node)

    state_counts = {}
    total = 0

    try:
        work_items = pdg_node.workItems
        for wi in work_items:
            state_name = _work_item_state_name(wi.state)
            state_counts[state_name] = state_counts.get(state_name, 0) + 1
            total += 1
    except Exception as e:
        raise ValueError(f"Failed to read work items: {e}")

    return {
        "node_path": node.path(),
        "total_work_items": total,
        "state_counts": state_counts,
    }


###### tops.get_work_item_info

def get_work_item_info(node_path: str, work_item_index: int) -> dict:
    """Return detailed information about a specific work item.

    Args:
        node_path: Path to the TOP node.
        work_item_index: Index of the work item within the node.
    """
    node = _get_top_node(node_path)
    pdg_node = _get_pdg_node(node)

    try:
        work_items = list(pdg_node.workItems)
    except Exception as e:
        raise ValueError(f"Failed to read work items: {e}")

    if work_item_index < 0 or work_item_index >= len(work_items):
        raise ValueError(
            f"Work item index {work_item_index} out of range. "
            f"Node has {len(work_items)} work items (0-{len(work_items) - 1})."
        )

    wi = work_items[work_item_index]
    return {
        "node_path": node.path(),
        "work_item": _work_item_to_dict(wi),
    }


###### tops.get_pdg_graph

def get_pdg_graph(node_path: str) -> dict:
    """Return the PDG dependency graph structure for a TOP network.

    Shows nodes and their dependency connections.

    Args:
        node_path: Path to a TOP network node or TOP node inside one.
    """
    node = _get_top_node(node_path)

    # Navigate to the topnet
    if node.type().category().name() == "TopNet" or node.type().name() == "topnet":
        topnet = node
    else:
        topnet = node.parent()
        if topnet is None:
            topnet = node

    children = topnet.children()
    nodes_info = []
    edges = []

    for child in children:
        node_info = {
            "name": child.name(),
            "path": child.path(),
            "type": child.type().name(),
        }

        # Work item count if available
        try:
            pdg_n = child.getPDGNode()
            if pdg_n is not None:
                node_info["work_item_count"] = len(pdg_n.workItems)
            else:
                node_info["work_item_count"] = 0
        except (hou.OperationFailed, AttributeError) as e:
            logger.debug("Could not read work item count for '%s': %s", child.name(), e)
            node_info["work_item_count"] = 0

        nodes_info.append(node_info)

        # Track input connections as edges
        for input_idx, input_connectors in enumerate(child.inputConnectors()):
            for connector in input_connectors:
                src_node = connector.inputNode()
                if src_node is not None:
                    edges.append({
                        "from": src_node.path(),
                        "to": child.path(),
                        "input_index": input_idx,
                    })

    return {
        "network_path": topnet.path(),
        "node_count": len(nodes_info),
        "nodes": nodes_info,
        "edge_count": len(edges),
        "edges": edges,
    }


###### tops.generate_static_items

def generate_static_items(node_path: str) -> dict:
    """Generate static work items on a TOP node without cooking them.

    This is useful for previewing what work items will be created.

    Args:
        node_path: Path to the TOP node.
    """
    node = _get_top_node(node_path)

    try:
        node.generateStaticWorkItems(True)
    except AttributeError:
        try:
            pdg_node = _get_pdg_node(node)
            pdg_node.generateStaticItems()
        except Exception as e:
            raise ValueError(f"Failed to generate static items: {e}")

    # Gather generated item info
    generated_count = 0
    try:
        pdg_node = _get_pdg_node(node)
        work_items = pdg_node.workItems
        generated_count = len(work_items)
    except (ValueError, AttributeError) as e:
        logger.debug("Could not read generated work item count: %s", e)

    return {
        "success": True,
        "node_path": node.path(),
        "generated_count": generated_count,
        "message": f"Generated {generated_count} static work items.",
    }


###### tops.get_top_scheduler_info

def get_top_scheduler_info(node_path: str) -> dict:
    """Return information about a TOP scheduler node.

    Args:
        node_path: Path to a TOP scheduler node or a TOP network
                   (returns info about its default scheduler).
    """
    node = _get_top_node(node_path)

    # If the node itself is a scheduler, report on it directly
    is_scheduler = False
    try:
        if hasattr(node, "isScheduler") and node.isScheduler():
            is_scheduler = True
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not check isScheduler: %s", e)
        if "scheduler" in node.type().name().lower():
            is_scheduler = True

    if not is_scheduler:
        # Find schedulers in the network
        if node.type().category().name() == "TopNet" or node.type().name() == "topnet":
            topnet = node
        else:
            topnet = node.parent()
            if topnet is None:
                topnet = node

        schedulers = []
        for child in topnet.children():
            try:
                if hasattr(child, "isScheduler") and child.isScheduler():
                    schedulers.append(child)
                elif "scheduler" in child.type().name().lower():
                    schedulers.append(child)
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not check scheduler status for '%s': %s", child.name(), e)

        if not schedulers:
            return {
                "node_path": node.path(),
                "message": "No scheduler nodes found in network.",
                "schedulers": [],
            }

        # Report on all found schedulers
        scheduler_infos = []
        for sched in schedulers:
            info = _build_scheduler_info(sched)
            scheduler_infos.append(info)

        return {
            "node_path": node.path(),
            "scheduler_count": len(scheduler_infos),
            "schedulers": scheduler_infos,
        }

    # Single scheduler node
    info = _build_scheduler_info(node)
    return {
        "node_path": node.path(),
        "scheduler_count": 1,
        "schedulers": [info],
    }


def _build_scheduler_info(sched_node: hou.Node) -> dict:
    """Build a dict of scheduler info from a scheduler node."""
    info = {
        "name": sched_node.name(),
        "path": sched_node.path(),
        "type": sched_node.type().name(),
    }

    # Read common scheduler parameters
    parm_names = [
        "pdg_maxitems", "pdg_maxprocs", "pdg_workingdir",
        "pdg_tempdirname", "maxprocsmenu",
    ]
    parms = {}
    for pname in parm_names:
        parm = sched_node.parm(pname)
        if parm is not None:
            try:
                parms[pname] = parm.eval()
            except (hou.OperationFailed, AttributeError) as e:
                logger.debug("Could not eval parm '%s': %s", pname, e)
                parms[pname] = parm.rawValue()
    info["parameters"] = parms

    # Check if scheduler is the default
    try:
        parent = sched_node.parent()
        if parent is not None:
            default_sched = parent.parm("topscheduler")
            if default_sched is not None:
                info["is_default"] = default_sched.eval() == sched_node.name()
            else:
                info["is_default"] = None
        else:
            info["is_default"] = None
    except (hou.OperationFailed, AttributeError) as e:
        logger.debug("Could not determine default scheduler: %s", e)
        info["is_default"] = None

    return info


###### Registration

register_handler("tops.get_top_network_info", get_top_network_info)
register_handler("tops.cook_top_node", cook_top_node)
register_handler("tops.cancel_top_cook", cancel_top_cook)
register_handler("tops.pause_top_cook", pause_top_cook)
register_handler("tops.dirty_work_items", dirty_work_items)
register_handler("tops.get_work_item_states", get_work_item_states)
register_handler("tops.get_work_item_info", get_work_item_info)
register_handler("tops.get_pdg_graph", get_pdg_graph)
register_handler("tops.generate_static_items", generate_static_items)
register_handler("tops.get_top_scheduler_info", get_top_scheduler_info)
