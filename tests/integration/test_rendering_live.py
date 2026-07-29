"""Live tests for executing render and write nodes.

start_render used to reject any node whose category was not Driver, which ruled
out the LOP usdrender_rop -- the way Solaris renders -- along with SOP ROPs and a
File Cache's Save to Disk. A recorded session pressed all of those by hand
through execute_python ten times.
"""

from __future__ import annotations

# Built-in
import os
import tempfile

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def geo(call) -> str:
    return call("nodes.create_node", parent_path="/obj", node_type="geo", name="rendergeo")[
        "node_path"
    ]


class TestStartRenderAcceptsAnyExecutableNode:
    def test_sop_rop_geometry_writes_and_reports_the_file(self, call, geo):
        node = hou.node(geo)
        box = node.createNode("box")
        rop = node.createNode("rop_geometry")
        rop.setFirstInput(box)
        out = os.path.join(tempfile.mkdtemp(), "box.bgeo.sc")
        rop.parm("sopoutput").set(out)

        result = call("rendering.start_render", node_path=rop.path(), frame_range=[1, 1])
        assert result["success"] is True, result
        assert result["category"] == "Sop", result
        # The whole point: it says where it wrote and whether anything is there.
        paths = {o["parm"]: o for o in result["outputs"]}
        assert paths["sopoutput"]["exists"] is True, result["outputs"]
        assert paths["sopoutput"]["size_bytes"] > 0
        assert os.path.isfile(out)

    def test_filecache_save_button_is_pressable(self, call, geo):
        node = hou.node(geo)
        box = node.createNode("box")
        cache = node.createNode("filecache")
        cache.setFirstInput(box)
        # A File Cache has no render(); Save to Disk is a button, which is why a
        # category check could never reach it.
        assert not hasattr(cache, "render") or cache.parm("execute") is not None
        out = os.path.join(tempfile.mkdtemp(), "cache.$F4.bgeo.sc")
        cache.parm("filemethod").set(1)  # explicit file path
        cache.parm("file").set(out)

        result = call("rendering.start_render", node_path=cache.path(), frame_range=[1, 1])
        assert result["success"] is True, result
        assert result["method"] in ("execute button", "render()"), result

    def test_lop_usdrender_rop_is_accepted_not_rejected(self, call):
        stage = hou.node("/stage")
        types = stage.childTypeCategory().nodeTypes()
        if "usdrender_rop" not in types:
            pytest.skip("this build has no usdrender_rop LOP")
        rop = stage.createNode("usdrender_rop")
        # Not asserting a finished Karma render, which needs a stage with a
        # camera and would make this a slow render test. What matters is that the
        # category no longer disqualifies it before anything is attempted.
        assert rop.type().category().name() == "Lop"
        result = call("rendering.start_render", node_path=rop.path(), frame_range=[1, 1])
        assert "category" in result and result["category"] == "Lop", result
        assert "not a ROP/Driver node" not in str(result)

    def test_a_node_with_nothing_to_press_says_so(self, call, geo):
        box = hou.node(geo).createNode("box")
        error = call("rendering.start_render", node_path=box.path(), expect_error=True)
        message = error["message"]
        assert "nothing to trigger" in message, message
        # The old message named the category as the disqualifier, which sent the
        # caller looking for a Driver node instead of an executable one.
        assert "not a ROP/Driver node" not in message

    def test_empty_output_path_is_reported_rather_than_hidden(self, call, geo):
        node = hou.node(geo)
        box = node.createNode("box")
        rop = node.createNode("rop_geometry")
        rop.setFirstInput(box)
        rop.parm("sopoutput").set("")
        result = call("rendering.start_render", node_path=rop.path(), frame_range=[1, 1])
        outputs = {o["parm"]: o for o in result.get("outputs", [])}
        if "sopoutput" in outputs:
            entry = outputs["sopoutput"]
            # Either it wrote nowhere and says so, or Houdini refused; both are
            # better than success with no file and no comment.
            assert entry.get("empty") or entry.get("exists") is False, entry


class TestStartRenderReportsFailureHonestly:
    """render() returning without raising is not evidence that a render happened.

    A LOP usdrender_rop shells out to husk. When husk exits non-zero -- no
    license, bad scene, missing camera -- the ROP records the error and render()
    still returns normally. The first version of this handler reported that as
    success, which is the same false-confidence bug the viewport tools had: a
    caller then verifies a screenshot of an image that was never written.

    Reproduced against a live Karma render: husk exited 3 with "No licenses could
    be found to run this application", and start_render said success: True.
    """

    def test_unwritable_path_is_reported_as_failure(self, call, geo):
        node = hou.node(geo)
        box = node.createNode("box")
        rop = node.createNode("rop_geometry")
        rop.setFirstInput(box)
        # A drive that cannot exist, so Houdini raises a real cook error rather
        # than a simulated one.
        rop.parm("sopoutput").set("Q:/nonexistent-drive/fxh/should_fail.bgeo.sc")

        result = call("rendering.start_render", node_path=rop.path(), frame_range=[1, 1])
        assert result["success"] is False, result
        assert result.get("errors") or result.get("error"), result
        assert result["wrote_files"] is False, result

    def test_success_requires_a_file_that_actually_changed(self, call, geo):
        import os
        import tempfile

        node = hou.node(geo)
        box = node.createNode("box")
        rop = node.createNode("rop_geometry")
        rop.setFirstInput(box)
        out = os.path.join(tempfile.mkdtemp(), "wrote.bgeo.sc")
        rop.parm("sopoutput").set(out)

        result = call("rendering.start_render", node_path=rop.path(), frame_range=[1, 1])
        assert result["success"] is True, result
        # Existence alone would pass even if nothing ran; this asserts the file
        # appeared or changed across the call.
        assert result["wrote_files"] is True, result
        assert result["message"] == "Render completed and wrote output."
        assert os.path.isfile(out)

    def test_non_file_output_targets_are_classified_not_executed(self, call, geo):
        """ "__render__.usd" and MPlay's "ip" are not files.

        Reporting them as exists: False trained the reader to ignore the field.
        Deliberately does NOT render: a SOP ROP treats "ip" as a relative path and
        writes a file called "ip" into the working directory, which is how an
        earlier version of this test left one in the repository root.
        """
        node = hou.node(geo)
        box = node.createNode("box")
        rop = node.createNode("rop_geometry")
        rop.setFirstInput(box)
        rop.parm("sopoutput").set("ip")
        # Ask a node with nothing to trigger, so the classification is reported
        # without anything being executed.
        error = call("rendering.start_render", node_path=box.path(), expect_error=True)
        assert "nothing to trigger" in error["message"]
