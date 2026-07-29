"""MCP tool modules for FXHoudini-MCP.

Importing this package registers all MCP tools with the FastMCP server.
Each submodule uses the `@mcp.tool()` decorator at import time.
"""

from __future__ import annotations

# Built-in
import json

# Third-party
from mcp.types import ImageContent, TextContent


def result_with_image(result: dict) -> list[TextContent | ImageContent]:
    """Convert a handler result dict into MCP content blocks.

    If the result contains ``image_base64``, an ``ImageContent`` block is
    appended so that MCP clients (e.g. Claude Desktop) can display the
    image inline.  The base64 key is removed from the metadata text.
    """
    image_data = result.pop("image_base64", None)
    mime_type = result.pop("mime_type", "image/png")

    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(result)),
    ]

    if image_data:
        content.append(ImageContent(type="image", data=image_data, mimeType=mime_type))

    return content


# Internal. Imported below the helper above on purpose: importing a tool
# module registers its tools on mcp, and they need the helper to exist.
from fxhoudinimcp.tools import (  # noqa: E402
    animation,  # noqa: F401
    cache,  # noqa: F401
    chops,  # noqa: F401
    code,  # noqa: F401
    context,  # noqa: F401
    cops,  # noqa: F401
    dops,  # noqa: F401
    geometry,  # noqa: F401
    graph,  # noqa: F401
    hda,  # noqa: F401
    help,  # noqa: F401
    lops,  # noqa: F401
    materials,  # noqa: F401
    nodes,  # noqa: F401
    parameters,  # noqa: F401
    rendering,  # noqa: F401
    scene,  # noqa: F401
    takes,  # noqa: F401
    tops,  # noqa: F401
    vex,  # noqa: F401
    viewport,  # noqa: F401
    workflows,  # noqa: F401
)
