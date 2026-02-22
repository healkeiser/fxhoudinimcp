"""Entry point for the FXHoudini MCP server."""

from __future__ import annotations

# Built-in
import logging
import os


def main() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    # Import server (triggers tool, resource, and prompt registration)
    from fxhoudinimcp.server import mcp  # noqa: F811

    # Force import all tool modules to register them
    from fxhoudinimcp import tools as _tools  # noqa: F401
    from fxhoudinimcp import resources as _resources  # noqa: F401
    from fxhoudinimcp import prompts as _prompts  # noqa: F401

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
