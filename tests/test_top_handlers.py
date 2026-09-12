"""Pure-Python pieces of the TOP handlers that need no Houdini."""

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

from fxhoudinimcp_server.handlers.top_handlers import _log_uri_to_path, _work_item_log  # noqa: E402


@pytest.mark.parametrize(
    ("uri", "path"),
    [
        # What 22.0.368 actually hands out on Windows: no slashes after the scheme.
        (
            "file:C:/tmp/pdgtemp/1/logs/pythonscript1_2.log",
            "C:/tmp/pdgtemp/1/logs/pythonscript1_2.log",
        ),
        ("file:///C:/tmp/x.log", "C:/tmp/x.log"),
        ("file:///tmp/x.log", "/tmp/x.log"),
        ("file:/tmp/x.log", "/tmp/x.log"),
    ],
)
def test_log_uri_to_path(uri, path):
    assert _log_uri_to_path(uri) == path


def test_in_process_log_text_wins_over_a_file():
    item = MagicMock()
    item.logMessages = "ERROR: boom"
    item.logURI = "file:/nowhere.log"
    assert _work_item_log(item) == "ERROR: boom"


def test_falls_back_to_the_scheduler_file(tmp_path):
    log = tmp_path / "item.log"
    log.write_text("from the scheduler", encoding="utf-8")
    item = MagicMock()
    item.logMessages = ""
    item.logURI = "file:" + str(log).replace("\\", "/")
    assert _work_item_log(item) == "from the scheduler"


def test_nothing_recorded_is_empty_not_an_error():
    item = MagicMock()
    item.logMessages = ""
    item.logURI = "file:/definitely/not/here.log"
    assert _work_item_log(item) == ""
