"""set_wrangle_code edits a block of the snippet in place.

Changing one block of a ~130-line snippet needed the whole text back.
edits=[{old, new}] replaces exact text, each `old` found exactly once; one bad
edit writes nothing, and the reply names the changed lines instead of echoing
the code.

hou is mocked here; the live check ran on Houdini 22.0.466.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.vex_handlers as vex  # noqa: E402

_SNIPPET = "int a = 1;\n// block\nfloat w = 0.5;\nfloat h = 0.25;\n// end\n@P.y += a;"


class TestSnippetEdits:
    def test_replacements_apply_in_order_and_name_their_lines(self):
        code, applied = vex._apply_snippet_edits(
            _SNIPPET,
            [
                {
                    "old": "float w = 0.5;\nfloat h = 0.25;",
                    "new": "float w = 0.25;\nfloat h = 0.5;",
                },
                {"old": "@P.y += a;", "new": "@P.y += a * w;"},
            ],
        )
        assert code == _SNIPPET.replace("0.5;\nfloat h = 0.25", "0.25;\nfloat h = 0.5").replace(
            "+= a;", "+= a * w;"
        )
        assert applied[0]["lines"] == [3, 4]
        assert applied[1]["lines"] == [6, 6]

    @pytest.mark.parametrize(
        ("old", "why"), [("float", "occurs 2 times"), ("nope", "occurs 0 times"), ("", "is empty")]
    )
    def test_an_old_that_is_not_there_exactly_once_writes_nothing(self, old, why):
        with pytest.raises(ValueError, match=rf"edits\[0\]: old {why}.*Nothing was written"):
            vex._apply_snippet_edits(_SNIPPET, [{"old": old, "new": "x"}])

    def test_the_handler_writes_once_and_answers_without_the_code(self, monkeypatch):
        node = MagicMock()
        node.path.return_value = "/obj/g/w"
        parm = node.parm.return_value
        parm.unexpandedString.return_value = _SNIPPET
        monkeypatch.setattr(vex, "_get_node", lambda path: node)
        monkeypatch.setattr(vex, "_validate_vex_quick", lambda n: {})
        result = vex.set_wrangle_code(
            "/obj/g/w", edits=[{"old": "int a = 1;", "new": "int a = 2;"}]
        )
        parm.set.assert_called_once_with(_SNIPPET.replace("a = 1", "a = 2"))
        assert "vex_code" not in result and result["line_count"] == 6

    def test_code_and_edits_together_are_refused(self, monkeypatch):
        node = MagicMock()
        monkeypatch.setattr(vex, "_get_node", lambda path: node)
        with pytest.raises(ValueError, match="vex_code .* or edits"):
            vex.set_wrangle_code("/obj/g/w", vex_code="x", edits=[{"old": "a", "new": "b"}])
