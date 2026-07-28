"""Utility for loading markdown prompt files with disk-read caching.

Layout of ``prompts/markdown/``:

* ``instructions/`` -- what the server tells every client at connect time.
* ``workflows/``    -- one file per subject, named after the SideFX help scope
  it draws on, served by the MCP prompts.
* ``shared/``       -- fragments injected into the above, never served alone.

Callers pass the path relative to ``markdown/``, e.g. ``workflows/pyro.md``, so
which of the three kinds a file is stays visible at every call site.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fxhoudinimcp.config import auto_layout_enabled

_MD_DIR = Path(__file__).parent / "prompts" / "markdown"

# Prose lives in markdown, not in Python string constants. These two are
# alternatives chosen by FXHOUDINIMCP_AUTO_LAYOUT, so they cannot simply be
# included by the files that need them.
_LAYOUT_ON = "shared/layout_on.md"
_LAYOUT_OFF = "shared/layout_off.md"
_HOUSEKEEPING = "shared/housekeeping.md"


@cache
def _read(name: str) -> str:
    """Read a markdown file once and cache it for the process lifetime."""
    return (_MD_DIR / name).read_text(encoding="utf-8")


@cache
def markdown_exists(name: str) -> bool:
    """Whether a markdown prompt file ships under ``markdown/``.

    Lets a prompt dispatch to a specialised file and fall back to a generic
    one, which is how simulation_setup serves a deep pyro guide without
    needing a separate MCP prompt per solver.
    """
    return (_MD_DIR / name).is_file()


def _layout_guidance() -> str:
    """Layout instruction matching the current auto-layout toggle.

    Stripped because it is substituted mid-sentence into a bullet list, and a
    trailing newline from the file would break the list.
    """
    return _read(_LAYOUT_ON if auto_layout_enabled() else _LAYOUT_OFF).strip()


def load_markdown(name: str, **kwargs: str) -> str:
    """Load a markdown prompt file, optionally formatting placeholders.

    File contents are cached after the first read — the files never change
    at runtime, so this avoids repeated disk I/O on every prompt invocation.

    Args:
        name: Path relative to the ``markdown/`` directory, including the
            subdirectory, e.g. ``workflows/pyro.md``.
        **kwargs: Values to substitute into ``{placeholder}`` tokens in the
            markdown text.  The special keys ``network_housekeeping`` and
            ``layout_guidance`` are automatically populated from
            ``shared/`` if not explicitly provided.

    Returns:
        The formatted markdown string.
    """
    text = _read(name)

    if "{layout_guidance}" in text and "layout_guidance" not in kwargs:
        kwargs["layout_guidance"] = _layout_guidance()
    if "{network_housekeeping}" in text and "network_housekeeping" not in kwargs:
        kwargs["network_housekeeping"] = _read(_HOUSEKEEPING).format(
            layout_guidance=_layout_guidance()
        )
    if kwargs:
        text = text.format(**kwargs)

    return text
