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

    Args:
        ctx: MCP context.
        filter: Substring filter for type names or file paths.
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

    Args:
        ctx: MCP context.
        node_path: Node path.
        hda_file: HDA file path.
        type_name: HDA type name.
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
    """Install an HDA file into the current session.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
        force: Force reinstall even if already loaded.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.install_hda",
        {
            "file_path": file_path,
            "force": force,
        },
    )


@mcp.tool()
async def uninstall_hda(ctx: Context, file_path: str) -> dict:
    """Uninstall an HDA file from the current session.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.uninstall_hda", {"file_path": file_path})


@mcp.tool()
async def reload_hda(ctx: Context, file_path: str) -> dict:
    """Reload an HDA file from disk.

    Args:
        ctx: MCP context.
        file_path: HDA file path.
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

    Args:
        ctx: MCP context.
        node_path: Subnet node path.
        hda_file: Destination HDA file path.
        type_name: Operator type name.
        label: Human-readable label.
        version: Version string.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.create_hda",
        {
            "node_path": node_path,
            "hda_file": hda_file,
            "type_name": type_name,
            "label": label,
            "version": version,
        },
    )


@mcp.tool()
async def update_hda(ctx: Context, node_path: str) -> dict:
    """Save the current node contents back to its HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("hda.update_hda", {"node_path": node_path})


@mcp.tool()
async def get_hda_sections(ctx: Context, node_path: str) -> dict:
    """List all sections in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.get_hda_sections", {"node_path": node_path}
    )


@mcp.tool()
async def get_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
) -> dict:
    """Read the content of a specific section in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
        section_name: Section name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.get_hda_section_content",
        {
            "node_path": node_path,
            "section_name": section_name,
        },
    )


@mcp.tool()
async def set_hda_section_content(
    ctx: Context,
    node_path: str,
    section_name: str,
    content: str,
) -> dict:
    """Write content to a specific section in an HDA definition.

    Args:
        ctx: MCP context.
        node_path: Node path.
        section_name: Section name.
        content: Section content.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "hda.set_hda_section_content",
        {
            "node_path": node_path,
            "section_name": section_name,
            "content": content,
        },
    )
