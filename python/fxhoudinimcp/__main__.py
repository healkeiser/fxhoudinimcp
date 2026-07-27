"""Entry point for the FXHoudini MCP server."""

from __future__ import annotations

# Built-in
import logging
import os
import sys


def main() -> None:
    # Subcommands are handled before the MCP plumbing loads: the server is
    # normally launched by an MCP client with no arguments, so argparse-ing the
    # whole entry point would risk changing that contract.
    if len(sys.argv) > 1 and sys.argv[1] == "houdini-package":
        from fxhoudinimcp.houdini_package import main as houdini_package_main

        raise SystemExit(houdini_package_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from fxhoudinimcp.install import main as install_main

        raise SystemExit(install_main(sys.argv[2:]))

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
