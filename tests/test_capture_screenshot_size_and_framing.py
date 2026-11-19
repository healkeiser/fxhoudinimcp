"""capture_screenshot names the verbs that size and frame a shot.

A session needed frames of one size and scale for a comparison sheet and
went to HOM (frameBoundingBox, a flipbook) for what render_viewport
(resolution) and frame_all (node_paths, bounds) already do: the
capture_screenshot description did not point at them."""

from __future__ import annotations

# Built-in
import ast
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "python" / "fxhoudinimcp" / "tools"


def _tool(module: str, name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse((_TOOLS / module).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


class TestScreenshotNamesSizeAndFraming:
    def test_size_and_framing_verbs_are_named(self):
        doc = ast.get_docstring(_tool("viewport.py", "capture_screenshot"))
        for phrase in ("render_viewport(resolution=", "frame_all(node_paths=", "frame_all(bounds="):
            assert phrase in doc

    def test_the_named_arguments_exist(self):
        render = [a.arg for a in _tool("rendering.py", "render_viewport").args.args]
        frame_all = [a.arg for a in _tool("viewport.py", "frame_all").args.args]
        assert "resolution" in render
        assert "node_paths" in frame_all and "bounds" in frame_all
