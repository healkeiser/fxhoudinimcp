"""Live tests for writing caches, and for proving a cache was written.

write_cache used to set ``status = "success"`` immediately after calling
``pressButton()`` on a File Cache's Save to Disk. That is fire-and-forget: a
filecache SOP that fails to write records the failure on the node and raises
nothing at all, so the report said "success" on the strength of having pressed a
button, never on the strength of a cache existing.

The command was already exercised by the coverage suite -- with
``allow_error=True``, which asserts nothing about the answer. That is why 188/188
command coverage did not catch this, and why every test here asserts what the
report *says* rather than merely that a call returned.
"""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def cache_node(call):
    """A filecache SOP fed by a box, with an explicit output path."""

    def _make(out_path: str):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="cachegeo")[
            "node_path"
        ]
        node = hou.node(geo)
        box = node.createNode("box")
        cache = node.createNode("filecache")
        cache.setFirstInput(box)
        cache.parm("filemethod").set(1)  # explicit file path, not automatic
        cache.parm("file").set(out_path)
        return cache

    return _make


class TestWriteCacheProvesItWrote:
    def test_unwritable_path_is_not_reported_as_success(self, call, cache_node):
        # A drive that cannot exist, so Houdini produces a real error rather than
        # a simulated one.
        cache = cache_node("Q:/nonexistent-drive/fxh/cache.$F4.bgeo.sc")

        result = call("cache.write_cache", node_path=cache.path(), frame_range=[1, 1])
        assert result["success"] is False, result
        assert result["wrote_files"] is False, result
        assert result.get("errors") or result.get("error"), result
        # The legacy field has to agree with the evidence, not with a button press.
        assert result["status"].startswith("error"), result["status"]

    def test_a_real_cache_reports_success_and_the_file(self, call, cache_node, tmp_path):
        out = str(tmp_path / "cache.$F4.bgeo.sc").replace("\\", "/")
        cache = cache_node(out)

        result = call("cache.write_cache", node_path=cache.path(), frame_range=[1, 1])
        assert result["success"] is True, result
        assert result["wrote_files"] is True, result
        assert result["status"] == "success", result
        written = list(tmp_path.glob("cache.*.bgeo.sc"))
        assert written, f"reported success but nothing on disk: {result}"
        assert written[0].stat().st_size > 0

    def test_status_and_success_never_disagree(self, call, cache_node, tmp_path):
        """Two fields answering the same question must not contradict each other.

        `status` predates `success`, so it is kept for callers that read it -- but
        it is now derived from the same evidence rather than set independently.
        """
        for path in (
            "Q:/nonexistent-drive/fxh/cache.$F4.bgeo.sc",
            str(tmp_path / "agree.$F4.bgeo.sc").replace("\\", "/"),
        ):
            cache = cache_node(path)
            result = call("cache.write_cache", node_path=cache.path(), frame_range=[1, 1])
            assert result["success"] is (result["status"] == "success"), result


class TestWriteCacheReportsWhereItWrote:
    def test_the_output_path_is_reported_back(self, call, cache_node, tmp_path):
        out = str(tmp_path / "reported.$F4.bgeo.sc").replace("\\", "/")
        cache = cache_node(out)
        result = call("cache.write_cache", node_path=cache.path(), frame_range=[1, 1])
        # Without this a caller has to re-read the parm to learn where to look,
        # which is what a recorded session did with PowerShell.
        paths = [entry.get("path") for entry in result.get("outputs", [])]
        assert any(paths), result
        assert any(os.path.basename(str(p)).startswith("reported") for p in paths if p), paths
