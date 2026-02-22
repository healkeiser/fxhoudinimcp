"""MCP tool wrappers for Houdini Digital Asset (HDA) operations.

Each tool delegates to the corresponding handler running inside Houdini
via the HTTP bridge.
"""

from __future__ import annotations

# Built-in
from typing import Optional

# Third-party
from mcp.server.fastmcp import Context

# Internal
from fxhoudinimcp.server import mcp, _get_bridge


@mcp.tool()
async def list_installed_hdas(
    ctx: Context,
    filter: Optional[str] = None,
) -> dict:
    """List all installed HDA files and their definitions.

    Returns type names, descriptions, library file paths, and versions.

    Args:
        ctx: MCP context.
        filter: Optional substring filter for HDA type names or file paths.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if filter is not None:
        params["filter"] = filter
    return await bridge.execute("hda.list_installed_hdas", params)


@mcp.tool()
async def get_hda_info(
    ctx: Context,
    node_path: Optional[str] = None,
    hda_file: Optional[str] = None,
    type_name: Optional[str] = None,
) -> dict:
    """Get detailed information about an HDA definition.

    Provide at least one of node_path, hda_file, or type_name. Returns
    version, description, inputs/outputs, parameters, and section list.

    Args:
        ctx: MCP context.
        node_path: Path to an HDA node instance in the scene.
        hda_file: Path to an HDA file on disk.
        type_name: Fully qualified HDA type name.
    """
    bridge = _get_bridge(ctx)
    params: dict = {}
    if node_path is not None:
        params["node_path"] = node_path
    if hda_file is not None:
        params["hda_file"] = hda_file
    if type_name is not None:
        params["type_name"] = type_name
    return await bridge.execute("hda.get_hda_info", params)


@mcp.tool()
async def install_hda(
    ctx: Context,
    file_path: str,
    force: bool = False,
) -> dict:
    """Install an HDA file into the current Houdini session.

    Args:
        ctx: MCP context.
        file_path: Path to the HDA file to install.
        force: If True, force reinstall even if already loaded.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.install_hda", {
        "file_path": file_path,
        "force": force,
    })


@mcp.tool()
async def uninstall_hda(ctx: Context, file_path: str) -> dict:
    """Uninstall an HDA file from the current Houdini session.

    Args:
        ctx: MCP context.
        file_path: Path to the HDA file to uninstall.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.uninstall_hda", {"file_path": file_path})


@mcp.tool()
async def reload_hda(ctx: Context, file_path: str) -> dict:
    """Reload an HDA file from disk to pick up external changes.

    Args:
        ctx: MCP context.
        file_path: Path to the HDA file to reload.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.reload_hda", {"file_path": file_path})


@mcp.tool()
async def create_hda(
    ctx: Context,
    node_path: str,
    hda_file: str,
    type_name: str,
    label: str,
    version: str = "1.0",
) -> dict:
    """Create a new HDA from an existing subnet node.

    Converts a subnet into a reusable Houdini Digital Asset and saves
    it to the specified file.

    Args:
        ctx: MCP context.
        node_path: Path to the subnet node to convert.
        hda_file: Destination file path for the HDA.
        type_name: The operator type name for the HDA.
        label: Human-readable label for the HDA.
        version: Version string (default "1.0").
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.create_hda", {
        "node_path": node_path,
        "hda_file": hda_file,
        "type_name": type_name,
        "label": label,
        "version": version,
    })


@mcp.tool()
async def update_hda(ctx: Context, node_path: str) -> dict:
    """Save the current node contents back to its HDA definition.

    Updates the HDA definition on disk with any changes made to the
    node's internal network.

    Args:
        ctx: MCP context.
        node_path: Path to the HDA node instance.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.update_hda", {"node_path": node_path})


@mcp.tool()
async def get_hda_sections(ctx: Context, node_path: str) -> dict:
    """List all sections in an HDA definition.

    Sections include DialogScript, PythonModule, Help, ExtraFileOptions,
    and other embedded data sections.

    Args:
        ctx: MCP context.
        node_path: Path to an HDA node instance.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.get_hda_sections", {"node_path": node_path})


@mcp.tool()
async def get_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
) -> dict:
    """Read the content of a specific section in an HDA definition.

    Common sections: "PythonModule", "DialogScript", "Help",
    "ExtraFileOptions", "OnCreated", etc.

    Args:
        ctx: MCP context.
        node_path: Path to an HDA node instance.
        section_name: Name of the section to read.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.get_hda_section_content", {
        "node_path": node_path,
        "section_name": section_name,
    })


@mcp.tool()
async def set_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
    content: str,
) -> dict:
    """Write content to a specific section in an HDA definition.

    Creates the section if it does not already exist. Use this to update
    PythonModule code, Help cards, dialog scripts, and other HDA sections.

    Args:
        ctx: MCP context.
        node_path: Path to an HDA node instance.
        section_name: Name of the section to write.
        content: The content to write to the section.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.set_hda_section_content", {
        "node_path": node_path,
        "section_name": section_name,
        "content": content,
    })
