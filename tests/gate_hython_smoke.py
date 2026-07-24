"""Gate hython-smoke harness -- RED build gate for pp12-109b.

Covers all 11 ADR 0001 section 3.7 items plus 4 per-family CODE_EXEC samples.
Designed to FAIL RED today (fxhoudinimcp_server.gate does not exist yet).
Designed to PASS GREEN after hou-dev builds Slices A+B.

Run:
    "C:/Program Files/Side Effects Software/Houdini 21.0.729/bin/hython.exe" \
        C:/Users/husma/development/fxhoudinimcp/tests/gate_hython_smoke.py

Exit 0 = all items PASSED.
Exit 1 = one or more items FAILED.

Author: hou-test (pp12-109b)
Verification surface: hython-smoke
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# --- sys.path: Homedini pure core first, then the fork ---
sys.path.insert(0, "C:/Users/husma/development/HoudiniUtilTools/scripts/python")
sys.path.insert(0, "C:/Users/husma/development/fxhoudinimcp/houdini/scripts/python")

# --- RED GATE ---
# This import FAILS today with ModuleNotFoundError (the gate/ package does not
# exist yet). hou-dev's Slice A creates fxhoudinimcp_server/gate/__init__.py
# with install_gate(), which flips this import to green.
from fxhoudinimcp_server.gate import install_gate  # RED: ModuleNotFoundError

import hou
import fxhoudinimcp_server.dispatcher as _dispatcher

# The seven gate command names (ADR section 3.5 / _GATE_COMMANDS frozenset).
_GATE_CMDS = frozenset([
    "gate.get_permission_mode",
    "gate.set_permission_mode",
    "gate.list_pending_calls",
    "gate.approve_pending_call",
    "gate.reject_pending_call",
    "gate.classify_code",
    "gate.get_audit_log",
])

# ------------------------------------------------------------------ helpers --

def _make_prefs(mode: str) -> str:
    """Create a fresh temp prefs dir with an mcp_gate.json for the given mode.

    Returns the prefs-dir path.
    """
    prefs = tempfile.mkdtemp(prefix="hython_gate_test_")
    gate_dir = os.path.join(prefs, "mcp_gate")
    os.makedirs(gate_dir, exist_ok=True)
    cfg_path = os.path.join(gate_dir, "mcp_gate.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({"mode": mode}, fh)
    return prefs


def _reset_gate() -> None:
    """Tear down any installed gate before each test group.

    Clears:
    - the GATE singleton on hou.session
    - the _is_gated marker on dispatcher.dispatch
    - restores _ORIGINAL_DISPATCH if it exists
    """
    if hasattr(hou.session, "_fxhoudinimcp_gate"):
        delattr(hou.session, "_fxhoudinimcp_gate")
    orig = getattr(_dispatcher, "_ORIGINAL_DISPATCH", None)
    if orig is not None and callable(orig):
        _dispatcher.dispatch = orig
    if hasattr(_dispatcher.dispatch, "_is_gated"):
        try:
            del _dispatcher.dispatch._is_gated
        except (AttributeError, TypeError):
            pass


def _install(mode: str) -> str:
    """Reset, write prefs, set HOUDINI_USER_PREF_DIR, and call install_gate().

    Returns the prefs dir so the caller can tidy up if needed.
    """
    _reset_gate()
    prefs = _make_prefs(mode)
    os.environ["HOUDINI_USER_PREF_DIR"] = prefs
    install_gate()
    return prefs


def _dispatch(cmd: str, params: dict | None = None) -> dict:
    return _dispatcher.dispatch(cmd, params or {})


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


# ------------------------------------------------------------------ items --

RESULTS: list[tuple[str, bool, str]] = []


def _run(label: str, fn) -> None:
    try:
        fn()
        RESULTS.append((label, True, ""))
        print(f"  PASS  {label}")
    except Exception as exc:
        RESULTS.append((label, False, str(exc)))
        print(f"  FAIL  {label}: {exc}")


# ---- §3.7 item 1 ---------------------------------------------------------
# propose mode: code.execute_python QUEUEs; approving it is REFUSED; audit log shows the
# queued->refused transition.
#
# CONTRACT CHANGE (ADR-0007 Phase 3, 2026-07-24). This item previously approved the queued
# code-exec call and asserted gate=approved/status=success. That is no longer reachable BY DESIGN:
# `trusted` is no longer settable via the gate command, so NO mode ALLOWs CODE_EXEC, and approving
# a queued code-exec call was the last remaining path from QUEUE to execution -- a backdoor around
# policy.decide's own execute_code FLOOR. The refusal is the property under test now. (MUTATING
# approvals are deliberately untouched; item 2 still exercises the queue path for a mutating call.)

def _item1():
    _install("propose")
    r = _dispatch("code.execute_python", {"code": "1+1"})
    _assert(r.get("gate") == "queued", f"expected gate=queued, got {r!r}")
    _assert(r.get("status") == "pending_approval", f"expected status=pending_approval, got {r!r}")
    pending_id = r.get("pending_id")
    _assert(pending_id is not None, f"no pending_id in {r!r}")

    # approving a code-exec call must be REFUSED, and the payload must never run
    a = _dispatch("gate.approve_pending_call", {"pending_id": pending_id})
    _assert(a.get("status") == "denied", f"expected status=denied, got {a!r}")
    _assert(a.get("gate") != "approved", f"code-exec approval was granted: {a!r}")
    _assert("data" not in a, f"a refused approval must carry no result payload: {a!r}")

    # audit log shows the queue and the refusal
    log = _dispatch("gate.get_audit_log", {})
    _assert(log.get("gate") == "allowed", f"audit log gated unexpectedly: {log!r}")
    entries = log.get("data", {}).get("entries", [])
    statuses = [e.get("event") for e in entries]
    _assert(
        any("queue" in (s or "").lower() for s in statuses),
        f"no queued event in audit log: {statuses!r}",
    )
    _assert(
        any("refus" in (s or "").lower() for s in statuses),
        f"no refused event in audit log: {statuses!r}",
    )
    # The refusal must record the QUEUED ENTRY's capability, not the gate command's own readonly --
    # the entry is purged moments later, so a 'readonly' line would be unreconstructable.
    refused = [e for e in entries if "refus" in (e.get("event") or "").lower()]
    _assert(
        any(e.get("capability") == "code_exec" for e in refused),
        f"refusal audit lost the entry's capability: {refused!r}",
    )


# ---- §3.7 item 2 ---------------------------------------------------------
# propose mode: nodes.create_node QUEUEs; reject -> node never created.

def _item2():
    _install("propose")
    r = _dispatch("nodes.create_node", {"parent_path": "/obj", "node_type": "geo"})
    _assert(r.get("gate") == "queued", f"expected gate=queued, got {r!r}")
    pending_id = r.get("pending_id")
    _assert(pending_id is not None, f"no pending_id in {r!r}")

    rej = _dispatch("gate.reject_pending_call", {"pending_id": pending_id})
    _assert(rej.get("status") in ("success", "rejected"), f"unexpected reject response: {rej!r}")

    # The node must NOT have been created.
    # (No reliable node name to check; verify pending list is now empty for this id.)
    pending = _dispatch("gate.list_pending_calls", {})
    ids_remaining = [p.get("pending_id") for p in pending.get("data", {}).get("pending", [])]
    _assert(pending_id not in ids_remaining, f"rejected call still in pending list")


# ---- §3.7 item 3 ---------------------------------------------------------
# read-only mode: nodes.create_node -> denied; scene.get_scene_info -> allowed
# with original response shape + gate=allowed.

def _item3():
    _install("read_only")
    r = _dispatch("nodes.create_node", {"parent_path": "/obj", "node_type": "geo"})
    _assert(r.get("gate") == "denied", f"expected gate=denied, got {r!r}")
    _assert(r.get("status") == "denied", f"expected status=denied, got {r!r}")

    info = _dispatch("scene.get_scene_info", {})
    _assert(info.get("gate") == "allowed", f"expected gate=allowed on read, got {info!r}")
    _assert("houdini_version" in info.get("data", {}), f"expected houdini_version in scene info data: {info!r}")


# ---- §3.7 item 4 ---------------------------------------------------------
# trusted mode: a read-only command returns the handler's original result
# dict PLUS gate=allowed; no queuing or denial.

def _item4():
    _install("trusted")
    info = _dispatch("scene.get_scene_info", {})
    _assert(info.get("gate") == "allowed", f"expected gate=allowed in trusted, got {info!r}")
    # Original response keys must survive unchanged (they come from get_scene_info).
    _assert("houdini_version" in info.get("data", {}), f"missing houdini_version in trusted response: {info!r}")
    _assert("fps" in info.get("data", {}), f"missing fps in trusted response: {info!r}")


# ---- §3.7 item 5 ---------------------------------------------------------
# Corrupt mcp_gate.json -> install_gate falls back to read_only.

def _item5():
    _reset_gate()
    prefs = tempfile.mkdtemp(prefix="hython_gate_corrupt_")
    gate_dir = os.path.join(prefs, "mcp_gate")
    os.makedirs(gate_dir, exist_ok=True)
    cfg_path = os.path.join(gate_dir, "mcp_gate.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write("{INVALID JSON{{{{")
    os.environ["HOUDINI_USER_PREF_DIR"] = prefs
    install_gate()

    mode_r = _dispatch("gate.get_permission_mode", {})
    mode = mode_r.get("data", {}).get("mode") or mode_r.get("mode")
    _assert(
        mode == "read_only",
        f"corrupt config: expected read_only fallback, got mode={mode!r}, response={mode_r!r}",
    )


# ---- §3.7 item 6 ---------------------------------------------------------
# gate.classify_code returns a classification verdict and does NOT execute code.

def _item6():
    _install("propose")
    dangerous_code = "__import__('os').system('echo SHOULD_NOT_RUN')"
    r = _dispatch("gate.classify_code", {"code": dangerous_code})
    _assert(r.get("gate") == "allowed", f"classify_code should bypass gate: {r!r}")
    data = r.get("data", r)  # some impls nest under data, some don't
    # Must have a classification verdict.
    _assert(
        "classification" in r or "classification" in data or "capability" in data or "verdict" in data,
        f"no classification in gate.classify_code response: {r!r}",
    )
    # The dangerous code must NOT have been executed (no side effect we can
    # observe from Python, but the gate response must not be a queued/denied
    # execution response).
    _assert(r.get("status") != "pending_approval", f"classify_code must not queue: {r!r}")


# ---- §3.7 item 7 (R3B) --------------------------------------------------
# propose mode: vex.create_vex_expression is CODE_EXEC; it QUEUES.

def _item7():
    # Need an existing node with a parm. Use trusted to create one first, then
    # switch to propose.
    _install("trusted")
    # Create a geo node under /obj to use as the target node.
    geo_r = _dispatch("nodes.create_node", {"parent_path": "/obj", "node_type": "geo", "name": "test_geo_r3b"})
    geo_path = geo_r.get("data", {}).get("node_path") or geo_r.get("node_path")
    if geo_path is None:
        # Acceptable: node creation in trusted mode may not embed gate, just succeed.
        # Try direct.
        geo_path = "/obj/test_geo_r3b"

    # Now switch to propose mode.
    _install("propose")
    r = _dispatch("vex.create_vex_expression", {
        "node_path": geo_path or "/obj/geo1",
        "parm_name": "tx",
        "vex_code": "__import__('os').system('echo R3B')",
    })
    _assert(r.get("gate") == "queued", f"R3B: vex.create_vex_expression must QUEUE in propose, got {r!r}")
    _assert(r.get("status") == "pending_approval", f"R3B: expected pending_approval, got {r!r}")


# ---- §3.7 item 8 (R3A) --------------------------------------------------
# approve mode: code.execute_python(code="1+1") -> QUEUES even if classifier says CLEAN.
# (The CODE_EXEC floor fires on capability, not classifier verdict.)

def _item8():
    _install("propose")
    r = _dispatch("code.execute_python", {"code": "1+1"})
    _assert(r.get("gate") == "queued", f"R3A: classifier-clean code must QUEUE in propose: {r!r}")
    _assert(r.get("status") == "pending_approval", f"R3A: expected pending_approval, got {r!r}")
    # Verify classification field is present (classifier ran but floor still fired).
    _assert(
        "classification" in r,
        f"R3A: classification field must be present in queued response: {r!r}",
    )


# ---- §3.7 item 9 (R4A) --------------------------------------------------
# Config {"mode": "trusted"} -> _demote_file_trusted -> effective mode is propose,
# NOT trusted. (FR-9: file-stored trusted is rejected; only API-set trusted is real.)

def _item9():
    _install("trusted")  # writes {"mode": "trusted"} to file then install_gate reads it
    # After R4A fix, the effective mode must be propose (demoted from file-stored trusted).
    mode_r = _dispatch("gate.get_permission_mode", {})
    mode = mode_r.get("data", {}).get("mode") or mode_r.get("mode")
    _assert(
        mode in ("propose", "read_only"),
        f"R4A: file-stored trusted must be demoted; got mode={mode!r}, response={mode_r!r}",
    )
    # Confirm: code.execute_python QUEUEs (would ALLOW if truly trusted).
    r = _dispatch("code.execute_python", {"code": "1+1"})
    _assert(r.get("gate") == "queued", f"R4A: code must QUEUE when demoted from trusted, got {r!r}")


# ---- §3.7 item 10 (R4C) -------------------------------------------------
# install_gate() twice -> dispatcher wrapped exactly once; no double-policy.

def _item10():
    _install("propose")  # first install
    install_gate()       # second install (same prefs dir, same mode)

    # Dispatch a CODE_EXEC command; it must QUEUE exactly once (not error or double-fire).
    r = _dispatch("code.execute_python", {"code": "42"})
    _assert(r.get("gate") == "queued", f"R4C: idempotent install: must QUEUE once, got {r!r}")

    # The _is_gated sentinel must be True on the wrapped dispatch.
    _assert(
        getattr(_dispatcher.dispatch, "_is_gated", False) is True,
        "R4C: _is_gated marker missing after install_gate()",
    )

    # The _ORIGINAL_DISPATCH must not itself be gated (no double-wrap).
    orig = getattr(_dispatcher, "_ORIGINAL_DISPATCH", None)
    _assert(orig is not None, "R4C: _ORIGINAL_DISPATCH missing after install_gate()")
    _assert(
        not getattr(orig, "_is_gated", False),
        "R4C: _ORIGINAL_DISPATCH must not itself be gated (double-wrap detected)",
    )


# ---- §3.7 item 11 (R4E) -------------------------------------------------
# " gate.get_audit_log" (leading space) -> NOT in _GATE_COMMANDS frozenset
# -> gets gated (queued in propose mode), NOT bypassed.

def _item11():
    _install("propose")
    r = _dispatch(" gate.get_audit_log", {})
    # This command has a leading space so it does NOT match the frozenset entry
    # "gate.get_audit_log". The gate must treat it like any unknown command.
    # In propose mode, unknown commands that are not read-only will QUEUE
    # or DENY depending on classifier. Either way, they must NOT get the
    # normal gate.get_audit_log bypass (gate=allowed).
    _assert(
        r.get("gate") != "allowed",
        f"R4E: leading-space command must NOT bypass gate (got gate=allowed): {r!r}",
    )


# ---- per-family CODE_EXEC sample 1: vex.set_wrangle_code ----------------
# In propose mode, vex.set_wrangle_code must QUEUE (it modifies VEX code).

def _sample_vex_set_wrangle_code():
    _install("propose")
    r = _dispatch("vex.set_wrangle_code", {
        "node_path": "/obj/nonexistent_wrangle",
        "vex_code": "i@test = 1;",
    })
    # Gate fires BEFORE the handler; the node-not-found check never runs.
    _assert(r.get("gate") == "queued", f"vex.set_wrangle_code must QUEUE in propose, got {r!r}")


# ---- per-family CODE_EXEC sample 2: vex.validate_vex --------------------
# vex.validate_vex cooks a node (CODE_EXEC) -> must QUEUE in propose mode.

def _sample_vex_validate_vex():
    _install("propose")
    r = _dispatch("vex.validate_vex", {"node_path": "/obj/nonexistent"})
    _assert(r.get("gate") == "queued", f"vex.validate_vex must QUEUE in propose, got {r!r}")


# ---- per-family CODE_EXEC sample 3: lops.set_usd_attribute --------------
# lops.set_usd_attribute builds and executes a Python LOP snippet -> CODE_EXEC.

def _sample_lops_set_usd_attribute():
    _install("propose")
    r = _dispatch("lops.set_usd_attribute", {
        "node_path": "/stage",
        "prim_path": "/World",
        "attr_name": "testAttr",
        "value": 1,
    })
    _assert(r.get("gate") == "queued", f"lops.set_usd_attribute must QUEUE in propose, got {r!r}")


# ---- per-family CODE_EXEC sample 4: graph.find_expensive_nodes ----------
# graph.find_expensive_nodes calls node.cook(force=True) -> CODE_EXEC.

def _sample_graph_find_expensive_nodes():
    _install("propose")
    r = _dispatch("graph.find_expensive_nodes", {"root_path": "/"})
    _assert(r.get("gate") == "queued", f"graph.find_expensive_nodes must QUEUE in propose, got {r!r}")


# ------------------------------------------------------------------ runner --

# ---- ADR-0007 Phase 3 item ------------------------------------------------
# The capability DECLARATIONS are load-bearing in a way they were not before ACT_SAFE.
#
# register_handler defaults `capability` to MUTATING and its docstring calls that fail-closed.
# That was true when the tiers were read_only/propose/approve/trusted, where MUTATING still QUEUED
# under propose. ACT_SAFE changed the meaning: MUTATING -> ALLOW, no queue. So a code-exec handler
# that ever loses its explicit `Capability.CODE_EXEC` would not fall back to "queued for approval";
# it would run free under the panel's own tier. All 221 commands declare one today, so there is no
# live hole -- this pins the three where dropping the declaration is worst.

_CODE_EXEC_COMMANDS = (
    "code.execute_python",
    "code.execute_hscript",
    "code.evaluate_expression",
)


def _item12():
    from fxhoudinimcp_server.dispatcher import capability_of

    for command in _CODE_EXEC_COMMANDS:
        cap = capability_of(command)
        _assert(
            cap is not None and getattr(cap, "value", None) == "code_exec",
            f"{command} no longer declares CODE_EXEC (got {cap!r}) — under ACT_SAFE it would be "
            f"treated as MUTATING and ALLOWED with no queue",
        )


def main() -> int:
    print("=== gate_hython_smoke.py -- pp12-109b RED build gate ===")
    print()

    print("-- ADR section 3.7 items (11) --")
    _run("item-1: propose CODE_EXEC queue->approve REFUSED->audit (ADR-0007)", _item1)
    _run("item-2: propose nodes.create_node queue->reject", _item2)
    _run("item-3: read_only create=denied, scene=allowed", _item3)
    _run("item-4: trusted read-only -> original shape + gate=allowed", _item4)
    _run("item-5: corrupt config -> read_only fallback", _item5)
    _run("item-6: gate.classify_code -> verdict only, no exec", _item6)
    _run("item-7 R3B: vex.create_vex_expression is CODE_EXEC, QUEUEs", _item7)
    _run("item-8 R3A: classifier-clean code.execute_python still QUEUEs", _item8)
    _run("item-9 R4A: file-stored trusted demoted to propose", _item9)
    _run("item-10 R4C: install_gate() twice -> single wrap", _item10)
    _run('item-11 R4E: " gate.get_audit_log" (leading space) not bypassed', _item11)
    _run("item-12 ADR-0007: code-exec commands still declare CODE_EXEC", _item12)

    print()
    print("-- Per-family CODE_EXEC samples (4) --")
    _run("sample-vex-1: vex.set_wrangle_code QUEUEs", _sample_vex_set_wrangle_code)
    _run("sample-vex-2: vex.validate_vex QUEUEs", _sample_vex_validate_vex)
    _run("sample-lops-1: lops.set_usd_attribute QUEUEs", _sample_lops_set_usd_attribute)
    _run("sample-graph-1: graph.find_expensive_nodes QUEUEs", _sample_graph_find_expensive_nodes)

    print()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== {passed}/{total} PASSED ===")

    for label, ok, msg in RESULTS:
        if not ok:
            print(f"  FAIL  {label}: {msg}")

    if passed < total:
        print("RESULT: RED (expected -- gate not implemented yet)")
        return 1
    print("RESULT: GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
