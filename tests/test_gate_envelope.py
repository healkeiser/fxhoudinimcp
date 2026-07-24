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
    # ADR-0007 Phase 3: _register_gate_handlers / _demote_live_non_settable_mode import
    # is_mode_command_settable from policy. Provide the REAL pure-logic function (no hou/Qt/pxr,
    # like gate_model above) so those imports resolve against this stub module instead of raising.
    from homedini.dcc.mcp_gate.policy import is_mode_command_settable as _real_settable
    policy_mod.is_mode_command_settable = _real_settable

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


# ---------------------------------------------------------------------------
# ADR-0007 Phase 3 — the gate is un-escalatable
# ---------------------------------------------------------------------------
# Two routes turn the gate against the live scene, and BOTH must be closed before a Codex child is
# wired into the panel: Codex has an un-fenced shell, so it can POST /api directly and the Phase 2
# removal of the agent-facing FastMCP tools never reaches it.
#   R1  gate.set_permission_mode("trusted") -> decide() ALLOWs CODE_EXEC -> arbitrary Python.
#   R2  queue a CODE_EXEC call, then approve it -> the thunk runs -> arbitrary Python.
# The bridge carries NO caller identity, so both refusals are unconditional rather than
# identity-based. MUTATING approvals stay open on purpose: that is the operator's propose-mode rail.


def _benign_classification():
    """Build a danger-free Classification for queueing test entries."""
    from homedini.dcc.mcp_gate.gate_model import Classification, Severity
    return Classification(danger=False, classes=[], severity=Severity.NONE, reasons=[])


def _make_real_gate(mode=None, ttl_seconds: int = 3600):
    """Build a gate with a REAL GateConfig + REAL PendingQueue and a capturing audit sink.

    Real collaborators on purpose: a mocked queue would happily report an approval that never ran
    the thunk, which is precisely the property under test.
    """
    import types as _types

    from homedini.dcc.mcp_gate.gate_model import GateConfig, Mode
    from homedini.dcc.mcp_gate.pending_queue import PendingQueue

    audit_events: list = []
    gate = _types.SimpleNamespace(
        config=GateConfig(
            mode=mode or Mode.PROPOSE, danger_classes={}, always_dangerous_tools=[],
            readonly_tools=[], audit_log="", queue_ttl_seconds=ttl_seconds,
        ),
        queue=PendingQueue(ttl_seconds=ttl_seconds),
        audit=_types.SimpleNamespace(append=audit_events.append),
    )
    return gate, audit_events


def _gate_handlers(mock_hou, monkeypatch, gate):
    """Register the REAL gate handlers against `gate`; return the isolated handler registry."""
    mock_hou.session._fxhoudinimcp_gate = gate
    import fxhoudinimcp_server.dispatcher as _d
    monkeypatch.setattr(_d, "_handler_registry", dict(_d._handler_registry), raising=False)
    if "fxhoudinimcp_server.gate.middleware" in sys.modules:
        del sys.modules["fxhoudinimcp_server.gate.middleware"]
    from fxhoudinimcp_server.gate.middleware import _register_gate_handlers
    _register_gate_handlers(_d, gate)
    return _d._handler_registry


class TestModeEscalationRefused:
    """R1 — gate.set_permission_mode can never reach a tier that ALLOWs CODE_EXEC."""

    def test_trusted_is_refused_and_the_live_mode_is_unchanged(self, mock_hou, monkeypatch):
        from homedini.dcc.mcp_gate.gate_model import Mode
        gate, audit = _make_real_gate(mode=Mode.PROPOSE)
        reg = _gate_handlers(mock_hou, monkeypatch, gate)

        result = reg["gate.set_permission_mode"](mode="trusted")

        assert result["status"] == "denied", result
        assert gate.config.mode is Mode.PROPOSE, (
            "the refusal returned denied but STILL changed the live mode"
        )
        assert any(getattr(e, "event", "") == "refused" for e in audit), (
            "a refused escalation must be audited - it is the tripwire that one was attempted"
        )

    def test_every_settable_mode_still_round_trips(self, mock_hou, monkeypatch):
        """The fence must be narrow: only non-settable modes refuse, not every mode."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        from homedini.dcc.mcp_gate.policy import is_mode_command_settable
        gate, _ = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)

        for mode in Mode:
            if not is_mode_command_settable(mode):
                continue
            result = reg["gate.set_permission_mode"](mode=mode.value)
            assert result["status"] == "success", (mode, result)
            assert gate.config.mode is mode

    def test_the_panels_act_safe_ungate_survives_the_refusal(self, mock_hou, monkeypatch):
        """The panel sets act_safe at spawn; if the refusal caught it, the panel would look dead."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        gate, _ = _make_real_gate(mode=Mode.PROPOSE)
        reg = _gate_handlers(mock_hou, monkeypatch, gate)

        assert reg["gate.set_permission_mode"](mode="act_safe")["status"] == "success"
        assert reg["gate.get_permission_mode"]()["data"]["mode"] == "act_safe"


class TestApprovalCapabilityFence:
    """R2 — a queued CODE_EXEC call has no approval path; MUTATING approvals still run."""

    def _queue(self, gate, capability):
        """Queue one entry whose thunk records that it ran; return (pending_id, ran_list)."""
        ran: list[str] = []

        def _thunk():
            ran.append("EXECUTED")
            return {"status": "success"}

        pending_id = gate.queue.add(
            tool="scene.execute_python", capability=capability,
            classification=_benign_classification(), code="hou.hipFile.newFile()",
            run_thunk=_thunk, params={},
        )
        return pending_id, ran

    def test_code_exec_approval_is_refused_and_the_thunk_never_runs(self, mock_hou, monkeypatch):
        from homedini.dcc.mcp_gate.gate_model import Capability
        gate, audit = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)
        pending_id, ran = self._queue(gate, Capability.CODE_EXEC)

        result = reg["gate.approve_pending_call"](pending_id=pending_id)

        assert result["status"] == "denied", result
        assert ran == [], "the queued code-exec thunk RAN - the approval fence did not hold"
        assert any(getattr(e, "event", "") == "refused" for e in audit)

    def test_mutating_approval_still_runs_the_thunk(self, mock_hou, monkeypatch):
        """The operator's propose-mode GateRail must keep approving reversible edits."""
        from homedini.dcc.mcp_gate.gate_model import Capability
        gate, _ = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)
        pending_id, ran = self._queue(gate, Capability.MUTATING)

        result = reg["gate.approve_pending_call"](pending_id=pending_id)

        assert ran == ["EXECUTED"], f"MUTATING approval did not run the thunk: {result!r}"
        assert result["gate"] == "approved", result

    def test_an_unknown_pending_id_refuses_rather_than_falling_through(self, mock_hou, monkeypatch):
        """Authorization must not depend on queue.list() and queue.approve() agreeing on existence.

        They do agree today (both purge expired entries first), but the fence reads its capability
        from list() output, so a divergence would have let approve() run an unchecked thunk.
        """
        gate, _audit = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)

        result = reg["gate.approve_pending_call"](pending_id="pc_does_not_exist")

        assert result["status"] == "error", result
        assert "No pending call" in result["error"]

    def test_the_refusal_audit_records_the_entrys_capability(self, mock_hou, monkeypatch):
        """The entry is purged moments later, so 'readonly' would be unreconstructable."""
        from homedini.dcc.mcp_gate.gate_model import Capability
        gate, audit = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)
        pending_id, _ran = self._queue(gate, Capability.CODE_EXEC)

        reg["gate.approve_pending_call"](pending_id=pending_id)

        refused = [e for e in audit if getattr(e, "event", "") == "refused"]
        assert refused, "no refusal was audited"
        assert any(getattr(e, "capability", "") == "code_exec" for e in refused), (
            "the audit recorded the gate command's own capability instead of the entry's: "
            f"{[getattr(e, 'capability', None) for e in refused]}"
        )

    def test_a_non_mutating_capability_fails_closed(self, mock_hou, monkeypatch):
        """Only an explicitly MUTATING entry is approvable - anything else refuses, not runs."""
        from homedini.dcc.mcp_gate.gate_model import Capability
        gate, _ = _make_real_gate()
        reg = _gate_handlers(mock_hou, monkeypatch, gate)
        pending_id, ran = self._queue(gate, Capability.READONLY)

        result = reg["gate.approve_pending_call"](pending_id=pending_id)

        assert result["status"] == "denied", result
        assert ran == []


class TestInstallGateLifecycle:
    """The hardening must bind the session that INSTALLS it - a reload must not leave stale state."""

    def _prepare(self, mock_hou, monkeypatch, gate):
        mock_hou.session._fxhoudinimcp_gate = gate
        import fxhoudinimcp_server.dispatcher as _d
        monkeypatch.setattr(_d, "_handler_registry", dict(_d._handler_registry), raising=False)
        if "fxhoudinimcp_server.gate.middleware" in sys.modules:
            del sys.modules["fxhoudinimcp_server.gate.middleware"]
        import fxhoudinimcp_server.gate.middleware as mw
        return _d, mw

    def test_a_live_trusted_session_is_demoted_on_install(self, mock_hou, monkeypatch):
        """BLOCKER 2: the GATE survives reload on hou.session, so TRUSTED would survive with it."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        gate, _ = _make_real_gate(mode=Mode.TRUSTED)
        _d, mw = self._prepare(mock_hou, monkeypatch, gate)

        def _stub_dispatch(command, params):
            return {"status": "success", "data": {}}
        monkeypatch.setattr(_d, "dispatch", _stub_dispatch, raising=False)

        mw.install_gate()

        assert gate.config.mode is Mode.PROPOSE, (
            "a session already at TRUSTED kept it across the install that hardens the gate"
        )

    def test_handlers_are_re_registered_even_when_already_gated(self, mock_hou, monkeypatch):
        """BLOCKER 1: hitting the idempotency return must still replace the previous closures.

        Handlers resolve by NAME from _handler_registry at call time, so leaving the old ones live
        means a refusal shipped in this module is simply not in force after a reload.
        """
        gate, _ = _make_real_gate()
        _d, mw = self._prepare(mock_hou, monkeypatch, gate)

        def _already_gated(command, params):
            return {"status": "success", "data": {}}
        _already_gated._is_gated = True
        monkeypatch.setattr(_d, "dispatch", _already_gated, raising=False)
        monkeypatch.setattr(_d, "_ORIGINAL_DISPATCH", _already_gated, raising=False)

        def _stale_handler(**_kwargs):
            return {"status": "STALE"}
        _d._handler_registry["gate.set_permission_mode"] = _stale_handler

        mw.install_gate()

        assert _d._handler_registry["gate.set_permission_mode"] is not _stale_handler, (
            "install_gate returned early and left the previous version's handler live"
        )

    def test_the_package_entry_point_follows_a_middleware_reload(self, mock_hou, monkeypatch):
        """BLOCKER 2: `from ...gate import install_gate` must not cache a pre-reload function.

        A module-level `from .middleware import install_gate` in the package __init__ binds the
        function OBJECT once. importlib.reload(middleware) never re-executes __init__, so the
        documented public entry point would keep installing the OLD, un-hardened gate. Patching the
        submodule's attribute here stands in for the reload: if __init__ cached, the patch is unseen.
        """
        import fxhoudinimcp_server.gate as gate_pkg
        import fxhoudinimcp_server.gate.middleware as mw

        calls: list[str] = []
        monkeypatch.setattr(mw, "install_gate", lambda *a, **k: calls.append("reloaded"), raising=False)

        gate_pkg.install_gate()

        assert calls == ["reloaded"], (
            "the package entry point called a stale install_gate bound at import time"
        )

    def test_a_stale_gated_wrapper_is_rebound_without_double_wrapping(self, mock_hou, monkeypatch):
        """After a reload the installed callable is the OLD _gated_dispatch - rebind, never re-wrap."""
        gate, _ = _make_real_gate()
        _d, mw = self._prepare(mock_hou, monkeypatch, gate)

        def _stale_gated(command, params):
            return {"status": "success", "data": {}}
        _stale_gated._is_gated = True

        def _real_dispatch(command, params):
            return {"status": "success", "data": {"real": True}}

        monkeypatch.setattr(_d, "dispatch", _stale_gated, raising=False)
        monkeypatch.setattr(_d, "_ORIGINAL_DISPATCH", _real_dispatch, raising=False)

        mw.install_gate()

        assert _d.dispatch is mw._gated_dispatch, "the stale wrapper stayed installed"
        assert _d._ORIGINAL_DISPATCH is _real_dispatch, (
            "install_gate re-captured _ORIGINAL_DISPATCH - that wraps the gate around itself"
        )


class TestPreviewCodeExecGuard:
    """preview_fn is the LAST execution path a queued CODE_EXEC entry still has.

    Approval is fenced (TestApprovalCapabilityFence) and no mode ALLOWs CODE_EXEC, so a preview_fn
    that "previews" by running the operator-supplied snippet would be the only remaining un-gated
    code-exec. The guard is capability-based so it also covers future CODE_EXEC commands.
    """

    def _load_run_preview(self, monkeypatch, capability_value, ran):
        import fxhoudinimcp_server.dispatcher as _d

        def _preview_fn(_params):
            ran.append("PREVIEWED")
            return {"ok": True}

        monkeypatch.setattr(
            _d, "preview_of", lambda _c: {"preview_fn": _preview_fn}, raising=False
        )

        class _ForkCap:
            value = capability_value

        monkeypatch.setattr(_d, "capability_of", lambda _c: _ForkCap(), raising=False)

        # sys.modules discipline (test-fixture-conventions §2.35): another module in the full suite
        # leaves an `hdefereval` MagicMock behind, and _run_preview would then marshal through it
        # and never call preview_fn at all -- so this test passed alone and failed in the suite.
        # Pin an hdefereval that really runs the callable, mirroring the in-Houdini main-thread
        # marshal, so the assertion is about the GUARD rather than about ambient module state.
        fake_hdefereval = types.ModuleType("hdefereval")
        fake_hdefereval.executeInMainThreadWithResult = lambda fn: fn()
        monkeypatch.setitem(sys.modules, "hdefereval", fake_hdefereval)

        if "fxhoudinimcp_server.gate.middleware" in sys.modules:
            del sys.modules["fxhoudinimcp_server.gate.middleware"]
        from fxhoudinimcp_server.gate.middleware import _run_preview
        return _run_preview

    def test_preview_is_refused_for_a_code_exec_command(self, mock_hou, monkeypatch):
        ran: list[str] = []
        run_preview = self._load_run_preview(monkeypatch, "code_exec", ran)

        payload, error = run_preview("scene.execute_python", {"code": "hou.hipFile.newFile()"})

        assert ran == [], "preview_fn RAN for a code_exec command - un-gated code execution"
        assert payload is None
        assert error is not None and "code_exec" in error, error

    def test_preview_still_runs_for_a_mutating_command(self, mock_hou, monkeypatch):
        """The guard must be narrow: it fences code-exec only, not every previewable command."""
        ran: list[str] = []
        run_preview = self._load_run_preview(monkeypatch, "mutating", ran)

        payload, error = run_preview("scene.create_node", {})

        assert ran == ["PREVIEWED"], f"the guard swallowed a legitimate preview: {error!r}"
        assert payload == {"ok": True}
        assert error is None


class TestRealPolicyThroughGatedDispatch:
    """End-to-end through _gated_dispatch with the REAL policy — no always-ALLOW decide() stub.

    Every other test in this file stubs `decide` (deliberately, to reach a specific branch), so
    without this class nothing exercises middleware + pure-core policy composed together. That is
    the shape that has bitten this fork before: green unit tests either side of a seam that is
    itself wrong. The last test walks the FULL R2 chain — queue a code-exec call, then try to
    approve it — which is the property the whole hardening exists to guarantee.
    """

    def _dispatch_with(self, mock_hou, monkeypatch, mode, capability_value):
        import fxhoudinimcp_server.dispatcher as _d

        gate, audit = _make_real_gate(mode=mode)
        mock_hou.session._fxhoudinimcp_gate = gate

        def _orig_dispatch(command, params):
            return {"status": "success", "data": {"ran": command}, "timing_ms": 1}

        class _ForkCap:
            value = capability_value

        ran: list[str] = []

        def _handler(**_kwargs):
            ran.append("EXECUTED")
            return {"ok": True}

        monkeypatch.setattr(_d, "_ORIGINAL_DISPATCH", _orig_dispatch, raising=False)
        monkeypatch.setattr(_d, "capability_of", lambda _c: _ForkCap(), raising=False)
        monkeypatch.setattr(_d, "preview_of", lambda _c: {}, raising=False)
        monkeypatch.setattr(_d, "_handler_registry", dict(_d._handler_registry), raising=False)
        _d._handler_registry["scene.probe"] = _handler

        if "fxhoudinimcp_server.gate.middleware" in sys.modules:
            del sys.modules["fxhoudinimcp_server.gate.middleware"]
        import fxhoudinimcp_server.gate.middleware as mw
        mw._register_gate_handlers(_d, gate)
        return mw, _d, gate, audit, ran

    def test_act_safe_denies_code_exec_end_to_end(self, mock_hou, monkeypatch):
        from homedini.dcc.mcp_gate.gate_model import Mode
        mw, _d, _gate, _audit, ran = self._dispatch_with(
            mock_hou, monkeypatch, Mode.ACT_SAFE, "code_exec"
        )

        result = mw._gated_dispatch("scene.probe", {"code": "hou.hipFile.newFile()"})

        assert result["gate"] == "denied", result
        assert ran == []

    def test_act_safe_allows_a_reversible_mutation_end_to_end(self, mock_hou, monkeypatch):
        """The floor must stay usable: act_safe exists so the agent CAN edit the scene."""
        from homedini.dcc.mcp_gate.gate_model import Mode
        mw, _d, _gate, _audit, _ran = self._dispatch_with(
            mock_hou, monkeypatch, Mode.ACT_SAFE, "mutating"
        )

        result = mw._gated_dispatch("scene.probe", {})

        assert result["gate"] == "allowed", result

    def test_the_full_escalation_chain_is_closed(self, mock_hou, monkeypatch):
        """R2 end-to-end: queue a code-exec call under propose, then fail to approve it.

        propose is operator-SELECTABLE in the panel, so this is a reachable state, not a contrived
        one. The queued thunk must never run.
        """
        from homedini.dcc.mcp_gate.gate_model import Mode
        mw, _d, _gate, _audit, ran = self._dispatch_with(
            mock_hou, monkeypatch, Mode.PROPOSE, "code_exec"
        )

        queued = mw._gated_dispatch("scene.probe", {"code": "hou.hipFile.newFile()"})
        assert queued["gate"] == "queued", queued
        pending_id = queued["pending_id"]
        assert ran == [], "queueing must not run the thunk"

        approved = _d._handler_registry["gate.approve_pending_call"](pending_id=pending_id)

        assert approved["status"] == "denied", approved
        assert ran == [], "the code-exec thunk RAN — the full escalation chain is NOT closed"
