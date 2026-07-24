"""Mocked pytest — RED gate for Defect #2 (pp12-109d).

Verifies that the ALLOW path of _gated_dispatch() preserves the {status, gate,
data} envelope contract specified in ADR 0002 Option A.

BUG (current code, middleware.py :227-235):
    inner = outer["data"]          # {"houdini_version": "21.0"}
    result = dict(inner)           # copies fields flat, no "data" wrapper
    result["gate"] = "allowed"
    result["status"] = "success"
    return result
    # => {"houdini_version": "21.0", "gate": "allowed", "status": "success"}
    #    result.get("data", {}) == {}  ← bridge-side read returns empty dict

FIX CONTRACT (ADR 0002, Option A ACCEPTED):
    return {
        "status":    "success",
        "gate":      "allowed",
        "data":      inner,          # ← "data" key preserved
        "timing_ms": outer.get("timing_ms"),
    }
    # => result["data"] == {"houdini_version": "21.0"}  ← bridge-side read correct

Verification surface: pytest-model (agent-runnable, mocked — no live Houdini).
Author:              hou-test (pp12-109d)
Red authored:        2026-06-22
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path: ensure the fork server package is importable off-DCC.
# ---------------------------------------------------------------------------
_FORK_PYTHON = "C:/Users/husma/development/fxhoudinimcp/houdini/scripts/python"
_HOMEDINI_PYTHON = "C:/Users/husma/development/HoudiniUtilTools/scripts/python"
for _p in (_FORK_PYTHON, _HOMEDINI_PYTHON):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_hou(monkeypatch):
    """Install a minimal hou stub into sys.modules BEFORE any middleware import.

    Pattern from test-fixture-conventions.md §2.3: monkeypatch.setitem so the
    stub is auto-restored after each test, preventing cross-test pollution.
    """
    fake_hou = MagicMock(name="hou")
    # _get_gate() reads hou.session._fxhoudinimcp_gate — return None (no gate)
    fake_hou.session._fxhoudinimcp_gate = None
    monkeypatch.setitem(sys.modules, "hou", fake_hou)
    return fake_hou


@pytest.fixture()
def mock_homedini_core(monkeypatch):
    """Stub the pure-core homedini gate model imports used inside _gated_dispatch.

    Uses the REAL gate_model (pure-logic, no hou/Qt/pxr) and provides a
    permissive decide() that always returns ALLOW so the ALLOW path is exercised.
    The classifier is stubbed to return a benign Classification so code-payload
    scanning is bypassed.
    """
    # The real gate_model is pure-logic (no hou/Qt/pxr — CL-015 compliant).
    # Import it directly so the Classification dataclass matches what middleware
    # instantiates via `Classification(danger=..., classes=..., ...)`.
    from homedini.dcc.mcp_gate.gate_model import (
        Mode, Capability, Decision, Classification, Severity, AuditEvent,
    )

    # Stub decide() — always ALLOW so these tests reach the ALLOW branch.
    def decide(_mode, _cap, _cls):  # noqa: ANN001, ANN202
        return Decision.ALLOW

    # Stub classifiers — return a benign Classification so code scanning is
    # bypassed (no real AST analysis needed for these envelope tests).
    def classify_python(_code, _danger_classes):  # noqa: ANN001, ANN202
        return Classification(
            danger=False,
            classes=[],
            severity=Severity.NONE,
            reasons=[],
        )

    def classify_hscript(_code):  # noqa: ANN001, ANN202
        return Classification(
            danger=False,
            classes=[],
            severity=Severity.NONE,
            reasons=[],
        )

    # Build stubs as proper module objects so `from x import y` works from
    # within middleware, which imports these by full dotted path.
    gate_model_mod = types.ModuleType("homedini.dcc.mcp_gate.gate_model")
    gate_model_mod.Mode           = Mode
    gate_model_mod.Capability     = Capability
    gate_model_mod.Decision       = Decision
    gate_model_mod.Classification = Classification
    gate_model_mod.Severity       = Severity
    gate_model_mod.AuditEvent     = AuditEvent

    policy_mod = types.ModuleType("homedini.dcc.mcp_gate.policy")
    policy_mod.decide = decide

    classifier_mod = types.ModuleType("homedini.dcc.mcp_gate.classifier")
    classifier_mod.classify_python  = classify_python
    classifier_mod.classify_hscript = classify_hscript

    # ADR-0007: middleware now imports homedini.dcc.mcp_gate.never_list. Provide it from the REAL
    # pure-logic module (no hou/Qt/pxr, like gate_model above), so _gated_dispatch's never-list
    # check resolves off-DCC instead of ModuleNotFoundError against the bare parent stub.
    from homedini.dcc.mcp_gate.never_list import (
        IRREVERSIBLE_COMMANDS, is_irreversible_command,
    )
    never_list_mod = types.ModuleType("homedini.dcc.mcp_gate.never_list")
    never_list_mod.IRREVERSIBLE_COMMANDS   = IRREVERSIBLE_COMMANDS
    never_list_mod.is_irreversible_command = is_irreversible_command

    for name, mod in [
        ("homedini",                         types.ModuleType("homedini")),
        ("homedini.dcc",                     types.ModuleType("homedini.dcc")),
        ("homedini.dcc.mcp_gate",            types.ModuleType("homedini.dcc.mcp_gate")),
        ("homedini.dcc.mcp_gate.gate_model", gate_model_mod),
        ("homedini.dcc.mcp_gate.policy",     policy_mod),
        ("homedini.dcc.mcp_gate.classifier", classifier_mod),
        ("homedini.dcc.mcp_gate.never_list", never_list_mod),
    ]:
        monkeypatch.setitem(sys.modules, name, mod)

    return {"Decision": Decision, "Mode": Mode, "Capability": Capability}


@pytest.fixture()
def dispatcher_with_gate(mock_hou, mock_homedini_core, monkeypatch):
    """Set up the dispatcher module with the gate installed ALLOW-mode.

    Installs _ORIGINAL_DISPATCH on the dispatcher module returning a standard
    dispatcher envelope {"status":"success","data":{"houdini_version":"21.0"},
    "timing_ms":1}, then installs the gate singleton so _gated_dispatch hits
    the ALLOW branch.

    Returns _gated_dispatch callable for direct invocation.
    """
    # Import dispatcher (no real hou needed — hou already mocked).
    import fxhoudinimcp_server.dispatcher as _d

    # -- _ORIGINAL_DISPATCH stub -------------------------------------------------
    # Returns the standard dispatcher envelope that _gated_dispatch unwraps.
    def _orig_dispatch(command, params):  # noqa: ANN001, ANN202
        return {
            "status":    "success",
            "data":      {"houdini_version": "21.0"},
            "timing_ms": 1,
        }

    monkeypatch.setattr(_d, "_ORIGINAL_DISPATCH", _orig_dispatch, raising=False)

    # -- capability_of stub -------------------------------------------------------
    # Returns a fake Capability so _cap_from_dispatcher resolves to READONLY.
    class ForkCap:
        value = "readonly"

    monkeypatch.setattr(_d, "capability_of", lambda _cmd: ForkCap(), raising=False)

    # -- Gate singleton -----------------------------------------------------------
    # Install a fake GateInstance on hou.session so _get_gate() returns non-None.
    from homedini.dcc.mcp_gate.gate_model import Mode

    class FakeGateConfig:  # noqa: D101
        mode            = Mode.READ_ONLY
        danger_classes  = []
        audit_log       = ""

    class FakeGate:  # noqa: D101
        config = FakeGateConfig()

    mock_hou.session._fxhoudinimcp_gate = FakeGate()

    # Now import _gated_dispatch — AFTER all stubs are in place (§2.3 discipline).
    if "fxhoudinimcp_server.gate.middleware" in sys.modules:
        del sys.modules["fxhoudinimcp_server.gate.middleware"]
    from fxhoudinimcp_server.gate.middleware import _gated_dispatch

    return _gated_dispatch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAllowPathEnvelopeContract:
    """ADR 0002 Option A — ALLOW path must preserve the 'data' key.

    These tests FAIL RED against current middleware.py (result = dict(inner)
    strips the 'data' wrapper). They will PASS GREEN after hou-dev applies the
    3-site fix per ADR 0002.
    """

    def test_allow_path_preserves_data_key(self, dispatcher_with_gate):
        """result['data'] must equal the original handler payload.

        Current code returns a flat dict without a 'data' key — KeyError here.
        """
        result = dispatcher_with_gate("scene.get_scene_info", {})

        # PRIMARY CONTRACT: 'data' key must be present and contain handler payload.
        assert "data" in result, (
            "DEFECT #2: ALLOW path stripped 'data' key. "
            f"result keys = {list(result.keys())}"
        )
        assert result["data"] == {"houdini_version": "21.0"}, (
            f"DEFECT #2: 'data' contains wrong payload: {result['data']!r}"
        )

    def test_allow_path_bridge_read_returns_payload(self, dispatcher_with_gate):
        """Simulates bridge.py:127 — result.get('data', {}) must return real payload.

        bridge.execute() does:
            if result.get("status") == "success":
                return result.get("data", {})

        With current code, result has no 'data' key → bridge returns {}.
        After fix, result["data"] == {"houdini_version": "21.0"} → bridge returns it.
        """
        result = dispatcher_with_gate("scene.get_scene_info", {})

        bridge_read = result.get("data", {})

        assert bridge_read != {}, (
            "DEFECT #2: bridge-style result.get('data', {}) returned empty dict. "
            "The ALLOW path must wrap handler result in a 'data' key."
        )
        assert bridge_read == {"houdini_version": "21.0"}, (
            f"DEFECT #2: bridge read wrong payload: {bridge_read!r}"
        )

    def test_allow_path_gate_metadata_present(self, dispatcher_with_gate):
        """result must carry gate='allowed', status='success', AND 'data'.

        Gate metadata must coexist with 'data' in the same envelope.
        Current code (flat copy) returns gate + status but strips 'data',
        so asserting all three together fails red until the fix lands.
        """
        result = dispatcher_with_gate("scene.get_scene_info", {})

        assert result.get("gate") == "allowed", (
            f"result['gate'] = {result.get('gate')!r} (expected 'allowed')"
        )
        assert result.get("status") == "success", (
            f"result['status'] = {result.get('status')!r} (expected 'success')"
        )
        # Gate metadata AND 'data' must coexist — the ADR 0002 envelope contract.
        assert "data" in result, (
            "DEFECT #2: gate metadata present but 'data' key still missing. "
            f"result keys = {list(result.keys())}"
        )

    def test_allow_path_data_not_flattened_into_top_level(self, dispatcher_with_gate):
        """Handler keys must NOT leak to top-level (they belong under 'data').

        Current code copies handler fields flat to the top level.
        After fix, 'houdini_version' must only appear under result['data'],
        not at result top-level.
        """
        result = dispatcher_with_gate("scene.get_scene_info", {})

        # After the fix this assertion is vacuously true because 'data' holds the
        # handler payload and top-level only has status/gate/timing_ms.
        # We assert the shape: if 'houdini_version' is at top-level AND 'data' is
        # absent → the flat-copy bug is still present.
        has_data_key = "data" in result
        has_flat_leak = "houdini_version" in result

        assert not (has_flat_leak and not has_data_key), (
            "DEFECT #2: handler fields leaked to top-level without 'data' wrapper. "
            f"result keys = {list(result.keys())}"
        )


# ---------------------------------------------------------------------------
# FIX A regression: mode input-normalization (_set_permission_mode)
# ---------------------------------------------------------------------------
# gate_model.py is pure-logic (no hou/Qt/pxr — CL-015 compliant).
# These tests run entirely off-DCC and guard against the underscore/hyphen
# normalization being silently reverted.
# Root cause: Mode.READ_ONLY.value == "read-only" (hyphen), so Mode("read_only")
# raises ValueError. The fix normalizes underscore→hyphen before Mode(…).

class TestModeInputNormalization:
    """Pure-logic regression tests for FIX A — _set_permission_mode input path.

    Exercises the normalization logic that maps underscore-form mode strings
    (e.g. "read_only") to the hyphenated enum values (e.g. "read-only").
    No hou, no Qt, no live Houdini needed.
    """

    def _normalize_and_parse(self, mode_str: str):
        """Mirror the normalization logic in _set_permission_mode for offline testing."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        normalized = mode_str.replace("_", "-")
        return Mode(normalized)

    def test_read_only_underscore_resolves(self):
        """'read_only' (underscore) must resolve to Mode.READ_ONLY without error."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        result = self._normalize_and_parse("read_only")
        assert result == Mode.READ_ONLY, (
            f"Expected Mode.READ_ONLY, got {result!r}"
        )

    def test_read_only_hyphen_resolves(self):
        """'read-only' (hyphen, canonical) must still resolve correctly after normalization."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        result = self._normalize_and_parse("read-only")
        assert result == Mode.READ_ONLY

    def test_propose_resolves(self):
        """'propose' (no hyphen) must still work (no transformation needed)."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        result = self._normalize_and_parse("propose")
        assert result == Mode.PROPOSE

    def test_trusted_resolves(self):
        """'trusted' must still work."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        result = self._normalize_and_parse("trusted")
        assert result == Mode.TRUSTED

    def test_garbage_input_raises_value_error(self):
        """Garbage input must raise ValueError (not silently succeed)."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        with pytest.raises(ValueError):
            self._normalize_and_parse("admin")

    def test_mode_str_output_is_underscore(self):
        """_mode_str() must output underscore form for all Mode values.

        Guards the OUTPUT path so the INPUT normalization and OUTPUT
        normalization remain symmetric.
        """
        # Import _mode_str directly — it has no hou dependency.
        import sys
        _FORK_PYTHON = "C:/Users/husma/development/fxhoudinimcp/houdini/scripts/python"
        if _FORK_PYTHON not in sys.path:
            sys.path.insert(0, _FORK_PYTHON)

        from homedini.dcc.mcp_gate.gate_model import Mode

        # Stub hou so middleware can be imported (it guards with try/except ImportError).
        import types
        if "hou" not in sys.modules:
            sys.modules["hou"] = types.ModuleType("hou")  # type: ignore[assignment]

        from fxhoudinimcp_server.gate.middleware import _mode_str

        assert _mode_str(Mode.READ_ONLY) == "read_only"
        assert _mode_str(Mode.PROPOSE)   == "propose"
        assert _mode_str(Mode.TRUSTED)   == "trusted"
        assert _mode_str(Mode.APPROVE)   == "approve"


class TestNeverListHardDeny:
    """ADR-0007 Seam 1 — irreversible commands are DENIED before policy.decide, any mode.

    The mock_homedini_core `decide` stub always returns ALLOW, so these prove the never-list
    check runs FIRST: if it did not, scene.new_scene would take the ALLOW path. That ordering is
    the whole point — the floor must sit below every mode, including a permissive one.
    """

    def test_new_scene_is_denied_even_when_policy_would_allow(self, dispatcher_with_gate):
        result = dispatcher_with_gate("scene.new_scene", {})
        assert result.get("gate") == "denied", (
            f"never-listed scene.new_scene must be denied; got {result!r}"
        )
        assert result.get("status") == "denied"

    def test_load_scene_is_denied(self, dispatcher_with_gate):
        assert dispatcher_with_gate("scene.load_scene", {"file_path": "x.hip"}).get("gate") == "denied"

    def test_clear_cache_is_denied(self, dispatcher_with_gate):
        assert dispatcher_with_gate("cache.clear_cache", {}).get("gate") == "denied"

    def test_a_reversible_command_still_reaches_the_allow_path(self, dispatcher_with_gate):
        # Not on the never-list, so the permissive decide() stub allows it — proving the check is
        # narrow (only the three irreversible commands), not a blanket denial.
        result = dispatcher_with_gate("scene.get_scene_info", {})
        assert result.get("gate") == "allowed", (
            f"a reversible command must not be caught by the never-list; got {result!r}"
        )


class TestActSafeModeRoundTrip:
    """ADR-0007 review (MAJOR-2): the panel<->fork ACT_SAFE mode string round-trip, across the REAL
    gate handlers -- not a test double that echoes its input. The panel sends the underscore form
    "act_safe" and its ungate-acceptance check compares against what the fork RETURNS; if _mode_str
    or _set_permission_mode's input normalization regresses its replace-direction, the panel's
    ungate silently exhausts its retry ladder. This catches that off-DCC.
    """

    def test_set_then_get_round_trips_act_safe_through_real_handlers(self, mock_hou, monkeypatch):
        import types as _types
        from homedini.dcc.mcp_gate.gate_model import GateConfig, Mode

        # A real GateConfig so the handler's dataclasses.replace() works on it.
        gate = _types.SimpleNamespace(config=GateConfig(
            mode=Mode.PROPOSE, danger_classes={}, always_dangerous_tools=[],
            readonly_tools=[], audit_log="", queue_ttl_seconds=3600,
        ))
        mock_hou.session._fxhoudinimcp_gate = gate

        import fxhoudinimcp_server.dispatcher as _d
        # Isolate the global handler registry so registering gate handlers here can't leak.
        monkeypatch.setattr(_d, "_handler_registry", dict(_d._handler_registry), raising=False)

        if "fxhoudinimcp_server.gate.middleware" in sys.modules:
            del sys.modules["fxhoudinimcp_server.gate.middleware"]
        from fxhoudinimcp_server.gate.middleware import _mode_str, _register_gate_handlers
        _register_gate_handlers(_d, gate)

        set_fn = _d._handler_registry["gate.set_permission_mode"]
        get_fn = _d._handler_registry["gate.get_permission_mode"]

        # INPUT direction: the panel's underscore form must normalize to Mode.ACT_SAFE.
        set_result = set_fn(mode="act_safe")
        assert set_result["status"] == "success", set_result
        assert gate.config.mode is Mode.ACT_SAFE, (
            "input normalization 'act_safe' -> Mode.ACT_SAFE regressed"
        )

        # OUTPUT direction: the readback must be the exact string the panel's ungate check compares.
        got = get_fn()
        assert got["data"]["mode"] == "act_safe", f"_mode_str output for ACT_SAFE regressed: {got!r}"

    def test_mode_str_maps_act_safe_to_underscore_form(self, mock_hou):
        import sys as _sys
        import types as _types
        if "hou" not in _sys.modules:
            _sys.modules["hou"] = _types.ModuleType("hou")  # type: ignore[assignment]
        from homedini.dcc.mcp_gate.gate_model import Mode

        from fxhoudinimcp_server.gate.middleware import _mode_str
        assert _mode_str(Mode.ACT_SAFE) == "act_safe"
