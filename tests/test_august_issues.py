"""Four rough edges reported against 2.10.0 (#39, #40, #41).

- create_light / create_light_rig asked Houdini 22 for a ``rectlight`` node
  that no longer exists: rect, sphere, disk and cylinder lights are the generic
  ``light`` node with its lighttype menu set.
- create_material_network dropped ``base_color`` and ``roughness`` silently:
  the MaterialX parameters are ``base_colorr/g/b`` and ``specular_roughness``.
- write_verdict pronounced "nothing was written" the instant render()
  returned, before husk's image reached the disk.
- Setting an expression-driven parameter surfaced Houdini's generic permission
  error instead of naming the expression.
"""

from __future__ import annotations

# Built-in
import os
import pathlib
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.lops_handlers as lops  # noqa: E402
import fxhoudinimcp_server.handlers.material_handlers as mats  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parms  # noqa: E402
import fxhoudinimcp_server.outputs as outputs  # noqa: E402

_HANDLER_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "houdini",
    "scripts",
    "python",
    "fxhoudinimcp_server",
    "handlers",
)


class TestLopLightTypes:
    def test_shaped_lights_are_the_generic_light_node(self):
        assert lops._lop_light_type("rect") == ("light", "UsdLuxRectLight")
        assert lops._lop_light_type("dome") == ("domelight", None)

    def test_no_preset_asks_for_a_node_type_that_does_not_exist(self):
        source = pathlib.Path(_HANDLER_DIR, "lops_handlers.py").read_text(encoding="utf-8")
        for gone in ("rectlight", "spherelight", "disklight", "cylinderlight"):
            assert f'"{gone}"' not in source, gone

    def test_shape_is_set_on_the_menu(self):
        node = MagicMock()
        lops._set_light_shape(node, "UsdLuxRectLight")
        node.parm.assert_called_once_with("lighttype")
        node.parm.return_value.set.assert_called_once_with("UsdLuxRectLight")


class TestShaderParams:
    def test_documented_keys_land_on_materialx(self):
        node = MagicMock()
        node.parm.side_effect = lambda n: (
            MagicMock() if n in ("specular_roughness", "metalness") else None
        )
        node.parmTuple.side_effect = lambda n: MagicMock() if n == "base_color" else None
        applied, skipped = mats._apply_shader_params(
            node,
            "mtlxstandard_surface",
            {"base_color": [0.8, 0.5, 0.2], "roughness": 0.3, "metalness": 0.9, "bogus": 1},
        )
        assert applied == {
            "base_color": "base_color",
            "roughness": "specular_roughness",
            "metalness": "metalness",
        }
        assert list(skipped) == ["bogus"]


class TestWriteVerdictGrace:
    def test_a_file_that_lands_late_still_counts(self, monkeypatch):
        node = MagicMock()
        monkeypatch.setattr(outputs, "node_messages", lambda n: ([], []))
        snapshots = iter(
            [
                [{"path": "a.exr", "exists": False, "is_file_output": True}],
                [{"path": "a.exr", "exists": True, "is_file_output": True}],
            ]
        )
        monkeypatch.setattr(outputs, "reported_outputs", lambda n: next(snapshots))
        monkeypatch.setattr(outputs, "wrote_anything", lambda b, a: a[0]["exists"])
        monkeypatch.setattr(outputs.time, "sleep", lambda s: None)
        verdict = outputs.write_verdict(
            node, [{"path": "a.exr", "exists": False, "is_file_output": True}], grace=1.0
        )
        assert verdict["wrote_files"] is True
        assert verdict["success"] is True


class _NotAnimated(Exception):
    """Stands in for hou.OperationFailed, which the hou stub does not define."""


@pytest.fixture
def real_operation_failed(monkeypatch):
    monkeypatch.setattr(parms.hou, "OperationFailed", _NotAnimated, raising=False)


class TestExpressionDrivenParm:
    def test_names_the_expression(self, real_operation_failed):
        driven = MagicMock()
        driven.name.return_value = "resolutiony"
        driven.node.return_value.path.return_value = "/stage/rendersettings"
        driven.expression.return_value = "pythonexprf('autoheight')"
        plain = MagicMock()
        plain.expression.side_effect = parms.hou.OperationFailed("not animated")
        message = parms._expression_driven([plain, driven])
        assert "resolutiony" in message
        assert "autoheight" in message
        assert "revert_parameter" in message

    def test_none_when_nothing_is_driven(self, real_operation_failed):
        plain = MagicMock()
        plain.expression.side_effect = parms.hou.OperationFailed("not animated")
        assert parms._expression_driven([plain]) is None


class TestRenderSettingsAcceptAnyRenderable:
    def test_category_check_is_gone(self):
        source = pathlib.Path(_HANDLER_DIR, "rendering_handlers.py").read_text(encoding="utf-8")
        assert "is not a ROP/Driver node" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
