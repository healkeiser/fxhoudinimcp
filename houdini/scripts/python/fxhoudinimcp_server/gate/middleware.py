"""Gate middleware: wraps dispatcher.dispatch() with security gate logic.

install_gate() swaps dispatcher.dispatch for _gated_dispatch exactly once
(idempotent — double-wrap guarded via _is_gated sentinel + hou.session stash).

Architecture notes:
- GATE singleton is stashed on hou.session._fxhoudinimcp_gate, NOT on this
  module, so it survives importlib.reload() (which re-executes the module body
  but never touches hou.session).  See CL-005/CL-011.
- Gate commands bypass the outer hdefereval marshal in _gated_dispatch via
  _ORIGINAL_DISPATCH.  The gate command handlers run directly so that approve/
  reject paths do not create a worker that blocks waiting for main-thread that
  is already servicing the outer dispatch — the rev-1 deadlock pattern.
- PendingQueue thunks are bare lambdas: lambda h=handler, p=captured: h(**p).
  No nested dispatcher.dispatch call, no worker/join.  See rev-1 deadlock fix.
- No off-main-thread hou.* access.  See CL-016.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import threading
from typing import Any, Callable

log = logging.getLogger("fxhoudinimcp_server.gate.middleware")

# ---------------------------------------------------------------------------
# The exact set of gate command names that bypass the gate (exact-match only).
# R4E: startswith("gate.") is NOT used — a leading-space typo must not bypass.
# ---------------------------------------------------------------------------

_GATE_COMMANDS: frozenset[str] = frozenset({
    "gate.get_permission_mode",
    "gate.set_permission_mode",
    "gate.list_pending_calls",
    "gate.approve_pending_call",
    "gate.reject_pending_call",
    "gate.classify_code",
    "gate.get_audit_log",
})

# Keys whose values contain operator-supplied code that the classifier must see.
# D5 fix: covers all injection surfaces across all 12 CODE_EXEC commands.
_CODE_KEYS: tuple[str, ...] = (
    "code",
    "command",
    "expression",
    "vex_code",
    "snippet",
    "python",
    "return_expression",
)


def _mode_str(mode) -> str:
    """Normalize a Mode enum value to the underscore form for external responses.

    The pure-core Mode.READ_ONLY.value is "read-only" (hyphen, PEP-8 enum
    value convention).  The smoke harness and FastMCP tools surface mode names
    with underscores ("read_only") for consistency with Python identifier style.
    This helper is the bridge between the two representations so the pure core
    stays unmodified.
    """
    return mode.value.replace("-", "_")


def _extract_code(params: dict[str, Any]) -> str | None:
    """Extract operator-supplied code from params for classifier input.

    Returns the first non-empty string value found under any key in _CODE_KEYS,
    or None if params contains no code payload.
    """
    for key in _CODE_KEYS:
        val = params.get(key)
        if val and isinstance(val, str):
            return val
    return None


# Preview timeout — shorter than the full command timeout so a stuck preview_fn
# does not block the operator's queue indefinitely. (ADV-002 worker+join pattern)
_PREVIEW_TIMEOUT = 30  # seconds


def _readonly_dispatch(command: str, params: dict[str, Any]) -> dict[str, Any]:
    """Local capability check for READONLY sub-operations within preview.

    This is NOT re-entry into the hdefereval gate dispatcher.  It performs a
    pure capability assertion: if the command is not READONLY, it raises
    ValueError.  Callers use this to guard sub-operations that preview_fn may
    internally invoke (ADV-004).

    Args:
        command: the sub-command name to check.
        params: ignored by this check; passed through to the real dispatcher if
            capability passes.

    Raises:
        ValueError: when the command's declared capability is not READONLY.
    """
    import fxhoudinimcp_server.dispatcher as _d
    cap = _d.capability_of(command)
    if cap is None or cap.value != "readonly":
        raise ValueError(
            f"_readonly_dispatch: command {command!r} is not READONLY "
            f"(capability={cap!r}); only READONLY sub-ops allowed in preview."
        )
    # For the verified-READONLY path, delegate to the original (unwrapped) dispatch.
    return _ORIGINAL_DISPATCH(command, params)


def _run_preview(command: str, params: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Run the registered preview_fn for *command* on the main thread.

    Returns (preview_dict, error_str):
        - (payload, None)  -- preview succeeded; payload is the fn's return value.
        - (None, error_str) -- preview_fn raised or timed out.
        - (None, None)     -- no preview_fn registered; caller queues normally.

    The preview_fn runs via hdefereval.executeInMainThreadWithResult so it can
    safely call hou.* on the main thread (CL-016 / ADV-002).
    Uses a worker+join with _PREVIEW_TIMEOUT so a stuck fn does not block forever.
    The preview_fn body is wrapped in hou.undos.disabler() so no undo history is
    recorded (ADV-004 / B1).  The result is json.dumps-validated to ensure it is
    serializable before being stored in the queue (ADV-011).
    """
    import fxhoudinimcp_server.dispatcher as _d

    reg = _d.preview_of(command)
    preview_fn = reg.get("preview_fn")
    if preview_fn is None:
        return None, None

    # ADR-0007 Phase 3: never run a preview_fn for a CODE_EXEC command.  A queued CODE_EXEC call
    # can no longer be approved (see _approve_pending_call), which leaves preview_fn as the ONLY
    # code path such an entry could still execute — a preview_fn that "previews" by running the
    # operator-supplied snippet would be an un-gated code-exec.  Guarded on capability rather than
    # command name so it also holds for any future CODE_EXEC command that registers a preview.
    from homedini.dcc.mcp_gate.gate_model import Capability as CoreCap
    if _cap_from_dispatcher(command) is CoreCap.CODE_EXEC:
        # Recoverable-suspicious, not expected-absence: no shipped CODE_EXEC handler registers a
        # preview, so reaching here means an unusual registration the operator should see rather
        # than a routine skip (fail-loud-discipline's WARNING tier).
        log.warning(
            "_run_preview: refusing to run a preview_fn registered on CODE_EXEC command %r "
            "(ADR-0007) — a preview that executes the payload would be un-gated code execution",
            command,
        )
        return None, "preview is not run for code_exec commands (ADR-0007)"

    container: dict[str, Any] = {}

    def _run() -> None:
        try:
            import hdefereval  # type: ignore[import-untyped]
            def _on_main():
                # Wrap preview_fn in undos.disabler so preview reads leave no
                # undo history in the scene (ADV-004 / B1).
                try:
                    import hou  # type: ignore[import-untyped]
                    with hou.undos.disabler():
                        return preview_fn(params)
                except ImportError:
                    # hou not available (unlikely in hdefereval path) — run bare.
                    return preview_fn(params)
            container["result"] = hdefereval.executeInMainThreadWithResult(_on_main)
        except ImportError:
            # Off-DCC (plain hython without hdefereval) — call directly.
            # This covers the hython-smoke test environment.
            try:
                try:
                    import hou  # type: ignore[import-untyped]
                    with hou.undos.disabler():
                        container["result"] = preview_fn(params)
                except ImportError:
                    # hython path without hou.undos — run bare (B1 / ADV-004).
                    container["result"] = preview_fn(params)
            except Exception as exc:  # noqa: BLE001
                container["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            container["error"] = str(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=_PREVIEW_TIMEOUT)

    if worker.is_alive():
        # Preview timed out — treat as a preview failure.
        return None, f"preview_fn timed out after {_PREVIEW_TIMEOUT}s"

    if "error" in container:
        return None, container["error"]

    result = container.get("result")
    if not isinstance(result, dict):
        return None, f"preview_fn returned non-dict: {type(result).__name__!r}"

    # ADV-011: validate JSON-serializability before storing in queue.
    # A preview_fn that returns non-serializable objects would cause list_pending
    # to crash later when the result is serialized for the MCP client.
    try:
        import json
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        return None, f"preview_fn result is not JSON-serializable: {exc}"

    return result, None


def _get_gate():
    """Return the GATE singleton from hou.session, or None if not installed."""
    try:
        import hou  # noqa: PLC0415
        return getattr(hou.session, "_fxhoudinimcp_gate", None)
    except ImportError:
        return None


def _set_gate(gate_obj) -> None:
    """Stash GATE on hou.session so it survives importlib.reload()."""
    try:
        import hou  # noqa: PLC0415
        hou.session._fxhoudinimcp_gate = gate_obj
    except ImportError:
        # hython with no session support — fall through; gate lives on module only
        pass


def _build_gate(config_path: str):
    """Build a new GateInstance (wrapping pure-core objects) from config_path."""
    from homedini.dcc.mcp_gate.config import load_config
    from homedini.dcc.mcp_gate.pending_queue import PendingQueue
    from homedini.dcc.mcp_gate.audit import AuditLog

    cfg = load_config(config_path)
    # Expand $HOUDINI_USER_PREF_DIR in audit_log path.
    audit_path = cfg.audit_log
    if "$HOUDINI_USER_PREF_DIR" in audit_path:
        pref_dir = os.environ.get("HOUDINI_USER_PREF_DIR", "")
        audit_path = audit_path.replace("$HOUDINI_USER_PREF_DIR", pref_dir)

    return _GateInstance(
        config=cfg,
        queue=PendingQueue(ttl_seconds=cfg.queue_ttl_seconds),
        audit=AuditLog(path=audit_path),
    )


class _GateInstance:
    """Holds the runtime gate state: config, pending queue, and audit log."""

    def __init__(self, config, queue, audit):
        self.config = config   # GateConfig
        self.queue = queue     # PendingQueue
        self.audit = audit     # AuditLog


def _cap_from_dispatcher(command: str):
    """Return pure-core Capability matching the fork dispatcher's Capability for command.

    Converts the fork Capability enum to pure-core Capability by .value string.
    Both enums share identical string values ("readonly"/"mutating"/"code_exec").
    Returns pure-core Capability.MUTATING as safe default if undeclared.
    """
    from homedini.dcc.mcp_gate.gate_model import Capability as CoreCap

    import fxhoudinimcp_server.dispatcher as _d
    fork_cap = _d.capability_of(command)
    if fork_cap is None:
        return CoreCap.MUTATING
    return CoreCap(fork_cap.value)


def _gated_dispatch(command: str, params: dict[str, Any]) -> dict[str, Any]:
    """Security-gated replacement for dispatcher.dispatch().

    Gate commands bypass directly to _ORIGINAL_DISPATCH (no hdefereval marshal).
    All other commands are evaluated through the pure-core decision pipeline.
    """
    import fxhoudinimcp_server.dispatcher as _d

    # --- Gate command bypass (exact-match only, R4E) ---
    if command in _GATE_COMMANDS:
        # Gate commands run via _ORIGINAL_DISPATCH to avoid nested hdefereval.
        # _ORIGINAL_DISPATCH wraps handler results in {"status":"success","data":handler_result}.
        # We surface the handler result directly (it already has gate=allowed, status, data keys)
        # so callers see a flat response: {gate, status, data, ...}.
        orig = getattr(_d, "_ORIGINAL_DISPATCH", None)
        if orig is None:
            return {"status": "error", "error": {"code": "GATE_NOT_INSTALLED", "message": "Gate not properly installed"}}
        outer = orig(command, params)
        # Unwrap the dispatcher envelope: surface the inner handler dict directly.
        if isinstance(outer, dict) and outer.get("status") == "success" and "data" in outer:
            inner = outer["data"]
            if isinstance(inner, dict):
                result = dict(inner)
                # Preserve timing_ms from the outer envelope if helpful.
                if "timing_ms" in outer:
                    result.setdefault("timing_ms", outer["timing_ms"])
                return result
        # Dispatch-level error (e.g. timeout, unknown command) — return as-is.
        return outer

    gate = _get_gate()
    if gate is None:
        # Fail closed: gate not installed -> deny everything non-gate.
        log.error("_gated_dispatch: GATE singleton missing — denying command %r (fail-closed)", command)
        return {
            "gate": "denied",
            "status": "denied",
            "reason": "Security gate not initialized — all commands denied until install_gate() is called.",
        }

    from homedini.dcc.mcp_gate.gate_model import (
        Mode, Capability as CoreCap, AuditEvent, Decision,
    )
    from homedini.dcc.mcp_gate.policy import decide
    from homedini.dcc.mcp_gate.classifier import classify_python, classify_hscript

    cfg = gate.config

    # --- Resolve capability ---
    capability = _cap_from_dispatcher(command)

    # --- Classify code payload (if present) ---
    code = _extract_code(params)
    if code is not None:
        classification = classify_python(code, cfg.danger_classes)
    else:
        # Non-code commands: produce a benign classification.
        from homedini.dcc.mcp_gate.gate_model import Classification, Severity
        classification = Classification(
            danger=False,
            classes=[],
            severity=Severity.NONE,
            reasons=[],
        )

    # --- ADR-0007 Seam 1: never-list hard DENY ---
    # scene.new_scene / scene.load_scene / cache.clear_cache destroy state that neither Houdini
    # undo nor a saved .hip recovers. Denied regardless of mode (the floor below ACT_SAFE/TRUSTED),
    # checked here because this is where the dispatch command string is known (decide() is
    # tool-name-blind). Sound only alongside the ACT_SAFE CODE_EXEC DENY in policy.decide: without
    # it, execute_python walks around any command-name list (review finding B1).
    from homedini.dcc.mcp_gate.never_list import is_irreversible_command
    if is_irreversible_command(command):
        _emit_audit(gate, command, params, "denied", classification)
        return {
            "gate": "denied",
            "status": "denied",
            "reason": (
                f"Command '{command}' is never allowed: it destroys scene or cache state that "
                f"neither Houdini undo nor a saved .hip can recover."
            ),
            "mode": _mode_str(cfg.mode),
            "capability": capability.value,
        }

    # --- Policy decision ---
    decision = decide(cfg.mode, capability, classification)

    # --- Act on decision ---
    if decision == Decision.ALLOW:
        # Emit audit event then call original dispatch.
        _emit_audit(gate, command, params, "allowed", classification)
        orig = getattr(_d, "_ORIGINAL_DISPATCH", None)
        if orig is None:
            log.error("_gated_dispatch: _ORIGINAL_DISPATCH missing on allow — failing closed")
            return {"gate": "denied", "status": "denied", "reason": "Gate internal error: original dispatch missing"}
        outer = orig(command, params)
        # Unwrap the dispatcher envelope ({"status":"success","data":handler_result})
        # so callers see the handler's keys directly + gate=allowed.
        # This matches the smoke harness expectations:
        #   info.get("gate") == "allowed" AND "houdini_version" in info (item3/4).
        if isinstance(outer, dict) and outer.get("status") == "success" and "data" in outer:
            inner = outer["data"]
            if isinstance(inner, dict):
                # ADR-0002 Option A: preserve the {status, gate, data} envelope so
                # bridge.execute()'s result.get("data", {}) resolves to the handler
                # payload rather than {}.  The old dict(inner) flattening dropped
                # the "data" key, breaking every non-gate tool over the live bridge.
                result = {"status": "success", "gate": "allowed", "data": inner}
                if "timing_ms" in outer:
                    result["timing_ms"] = outer["timing_ms"]
                return result
        # Non-standard response (e.g. error or timeout) — surface as-is + gate.
        outer["gate"] = "allowed"
        return outer

    elif decision == Decision.DENY:
        _emit_audit(gate, command, params, "denied", classification)
        mode_str = _mode_str(cfg.mode)
        return {
            "gate": "denied",
            "status": "denied",
            "reason": (
                f"Command '{command}' denied in mode '{cfg.mode.value}'. "
                f"Capability: {capability.value}."
            ),
            "mode": mode_str,
            "capability": capability.value,
        }

    elif decision == Decision.QUEUE:
        # Capture handler and params for the bare thunk — no nested dispatch.
        handler = _d._handler_registry.get(command)
        if handler is None:
            return {
                "status": "error",
                "error": {"code": "UNKNOWN_COMMAND", "message": f"No handler for: {command}"},
            }
        captured = dict(params)
        # Bare thunk: lambda with default captures, NO nested dispatcher.dispatch.
        # This is the rev-1 deadlock fix — no worker/join nesting.
        thunk: Callable = lambda h=handler, p=captured: h(**p)  # noqa: E731

        # --- ADR 0005 preview hook ---
        # Run preview_fn on the main thread (via _run_preview / hdefereval).
        # result shape: (payload|None, error_str|None)
        preview_payload: dict | None
        preview_error: str | None
        preview_payload, preview_error = _run_preview(command, params)

        reg = _d.preview_of(command)
        preview_required: bool = reg.get("preview_required", False)

        if preview_error is not None and preview_required:
            # ADV-007: preview_fn raised/timed-out AND preview_required=True -> DENY.
            _emit_audit(gate, command, params, "denied", classification)
            return {
                "gate": "denied",
                "status": "denied",
                "reason": (
                    f"Command '{command}' denied: preview validation failed and "
                    f"preview_required=True. Error: {preview_error}"
                ),
                "preview_error": preview_error,
            }

        # Degrade case: preview_fn raised but preview_required=False — store
        # {"preview_error": <str>} as the opaque preview blob so list() can
        # surface preview_error as a top-level field in the PRESENTATION SPLIT.
        stored_preview: dict | None
        if preview_error is not None:
            # Degrade: queue with error marker; no valid preview payload.
            stored_preview = {"preview_error": preview_error}
        else:
            # Success or no preview_fn (preview_payload may be None).
            stored_preview = preview_payload

        pending_id = gate.queue.add(
            tool=command,
            capability=capability,
            classification=classification,
            code=code or "",
            run_thunk=thunk,
            preview=stored_preview,
            # B3 fix: store params for approve-time re-validate (ADR 0005 rev2 §3.4f).
            params=params,
        )
        _emit_audit(gate, command, params, "queued", classification, pending_id=pending_id)

        # Build the queue response, surfacing the preview payload for check-1.
        queue_resp: dict[str, Any] = {
            "gate": "queued",
            "status": "pending_approval",
            "pending_id": pending_id,
            "command": command,
            "capability": capability.value,
            "mode": _mode_str(cfg.mode),
            "classification": {
                "danger": classification.danger,
                "classes": classification.classes,
                "severity": classification.severity.name,
                "reasons": classification.reasons,
            },
            "message": (
                f"Command '{command}' queued for approval (mode={cfg.mode.value}, "
                f"cap={capability.value}). Use gate.approve_pending_call or "
                f"gate.reject_pending_call with pending_id={pending_id!r}."
            ),
        }
        if preview_payload is not None:
            # Successful preview: surface the payload directly in the queue response.
            queue_resp["preview"] = preview_payload
        if preview_error is not None:
            # Degrade: surface the error string in the queue response.
            queue_resp["preview_error"] = preview_error
        return queue_resp

    else:
        # Unknown decision variant — fail closed.
        log.error("_gated_dispatch: unexpected Decision %r for command %r — denying", decision, command)
        return {"gate": "denied", "status": "denied", "reason": f"Unexpected policy decision: {decision!r}"}


def _emit_audit(
    gate, command: str, params: dict, event_type: str, classification,
    pending_id: str | None = None, capability_override: str | None = None,
) -> None:
    """Append an AuditEvent to the gate's audit log.  Errors are logged, not raised.

    AuditEvent expects a 'classification' field (serialised dict) and
    a 'code_sha256' field (hex digest or None) — NOT raw danger/classes/etc.
    """
    try:
        import hashlib
        from homedini.dcc.mcp_gate.gate_model import AuditEvent
        # Compute SHA-256 of the code payload if present (FR-7: never store raw code).
        code = _extract_code(params)
        code_sha256 = hashlib.sha256(code.encode("utf-8", errors="replace")).hexdigest() if code else None
        # Serialise the Classification into the format AuditEvent expects.
        cl_dict: dict = {
            "danger": classification.danger,
            "classes": list(classification.classes),
            "severity": (
                classification.severity.name
                if hasattr(classification.severity, "name")
                else str(classification.severity)
            ),
            "reasons": list(classification.reasons),
        }
        ev = AuditEvent(
            ts=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            event=event_type,
            tool=command,
            capability=(
                capability_override
                if capability_override is not None
                else str(_cap_from_dispatcher(command).value)
            ),
            mode=gate.config.mode.value,
            classification=cl_dict,
            code_sha256=code_sha256,
            pending_id=pending_id,
        )
        gate.audit.append(ev)
    except Exception as exc:  # noqa: BLE001
        log.warning("_emit_audit: failed to write audit event for %r: %s", command, exc)


def _emit_refusal_audit(
    gate, command: str, pending_id: str | None = None, capability: str | None = None
) -> None:
    """Record a refused gate-control attempt (ADR-0007 Phase 3) in the audit log.

    A refusal is the tripwire that something tried to escalate its own authority — the single most
    interesting event in the log — so it is recorded even though nothing ran.  Errors are logged,
    never raised: failing to write the audit line must not turn a refusal into an exception.

    Args:
        gate: the live _GateInstance whose audit log receives the event.
        command: the gate-control command that was refused.
        pending_id: linked PendingCall id, when the refusal concerned a queued call.
        capability: the capability that was actually refused, when it differs from `command`'s own.
            Refusing an approval is the case that matters: the interesting capability belongs to
            the QUEUED ENTRY (e.g. code_exec), while the gate command itself is readonly, and the
            entry is purged moments later — so without this the log could never be reconstructed.
    """
    try:
        from homedini.dcc.mcp_gate.gate_model import Classification, Severity
        benign = Classification(danger=False, classes=[], severity=Severity.NONE, reasons=[])
        _emit_audit(
            gate, command, {}, "refused", benign,
            pending_id=pending_id, capability_override=capability,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("_emit_refusal_audit: failed to record refusal of %r: %s", command, exc)


def _demote_live_non_settable_mode(gate) -> None:
    """Demote a live gate whose mode is no longer command-settable (ADR-0007 Phase 3).

    The GATE singleton lives on hou.session so it survives importlib.reload().  A session that had
    already reached TRUSTED before this hardening landed would therefore carry TRUSTED straight
    through the reload that installs the hardening — the refusal in _set_permission_mode blocks
    only NEW escalations, not one already in effect.  Demoting here makes the hardening apply to
    the session that installs it, not merely to sessions started afterwards.  PROPOSE is the target
    because it is the same safe tier config._demote_file_trusted falls back to.

    Args:
        gate: the live _GateInstance; its .config is replaced in place when demotion applies.
    """
    from dataclasses import replace

    from homedini.dcc.mcp_gate.gate_model import Mode
    from homedini.dcc.mcp_gate.policy import is_mode_command_settable

    # Capture the mode's display value INSIDE the guard too. Re-reading gate.config.mode below to
    # log it would be a second unguarded access on exactly the malformed object the guard just
    # caught -- and this runs BEFORE the wrap, so raising here would leave dispatch UNGATED.
    try:
        mode = gate.config.mode
        settable = is_mode_command_settable(mode)
        mode_label = getattr(mode, "value", mode)
    except Exception as exc:  # noqa: BLE001
        # Fail closed: a mode we cannot evaluate must not be left in force.
        log.error(
            "install_gate: could not evaluate live gate mode (%s); demoting to PROPOSE", exc
        )
        settable = False
        mode_label = "<unreadable>"
    if settable:
        return

    log.warning(
        "install_gate: live gate mode %r is no longer command-settable; demoting to %r (ADR-0007).",
        mode_label,
        Mode.PROPOSE.value,
    )
    gate.config = replace(gate.config, mode=Mode.PROPOSE)


def _warn_undeclared_commands() -> None:
    """FR-11 backstop: log a warning for any registered command with no declared capability.

    Iterates dispatcher.list_commands() and warns for any command where
    dispatcher.capability_of(cmd) returns None.  Such commands will be treated
    as MUTATING (fail-closed per ADR §3.3.4), but the missing declaration is
    a configuration smell worth surfacing at install time.
    """
    try:
        import fxhoudinimcp_server.dispatcher as _d
        if not (hasattr(_d, "list_commands") and hasattr(_d, "capability_of")):
            return
        for cmd in _d.list_commands():
            if _d.capability_of(cmd) is None:
                log.warning(
                    "install_gate: command %r has no declared capability — "
                    "will be treated as MUTATING (fail-closed)",
                    cmd,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("install_gate: _warn_undeclared_commands failed: %s", exc)


def install_gate() -> None:
    """Install the security gate on dispatcher.dispatch(), idempotent.

    Loads all fxhoudinimcp_server handlers (if not already loaded), then
    wraps dispatcher.dispatch with _gated_dispatch.  Safe to call multiple
    times — idempotent via the _is_gated sentinel (R4C).

    The GATE singleton is stashed on hou.session so it survives reload().
    Config is read from $HOUDINI_USER_PREF_DIR/mcp_gate/mcp_gate.json.

    Re-install ordering (ADR §3.4.4 D4, revised by ADR-0007 Phase 3):
    1. RESTORE existing GATE from hou.session FIRST — preserves the live
       PendingQueue across a Python-module reload.
    2. Demote a live mode that is no longer command-settable (ADR-0007).
    3. Register gate handlers on EVERY install — BEFORE the wrap idempotency
       check, so a reload actually replaces the previous version's closures.
    4. Check wrap idempotency, rebinding a stale wrapper if one is installed.
    5. Warn undeclared commands and wire the wrap only on first install.
    """
    import fxhoudinimcp_server.dispatcher as _d

    # Ensure all command handlers are registered before the gate wraps dispatch.
    # This makes install_gate() callable from standalone tests (the smoke harness)
    # without a separate 'from fxhoudinimcp_server import handlers' call.
    try:
        from fxhoudinimcp_server import handlers  # noqa: F401
    except ImportError as exc:
        log.warning("install_gate: could not import handlers: %s", exc)

    # Step 1: RESTORE GATE from hou.session FIRST (ADR §3.4.4 D4).
    # This must happen before the idempotency check so that a re-install after
    # a module reload re-attaches the live PendingQueue rather than discarding it.
    existing = _get_gate()
    if existing is not None:
        gate = existing  # REUSE — preserves the live PendingQueue
        log.debug("install_gate: re-attaching existing GATE from hou.session (queue preserved)")
    else:
        # First install — build a fresh gate and stash it on hou.session.
        pref_dir = os.environ.get("HOUDINI_USER_PREF_DIR", "")
        config_path = os.path.join(pref_dir, "mcp_gate", "mcp_gate.json")
        gate = _build_gate(config_path)
        _set_gate(gate)
        log.debug("install_gate: built fresh GATE from config %r", config_path)

    # Step 2 (ADR-0007 Phase 3): demote a live tier that is no longer command-settable, so this
    # hardening binds the session that installs it rather than only later ones.
    _demote_live_non_settable_mode(gate)

    # Step 3 (ADR-0007 Phase 3): register gate handlers on EVERY install, BEFORE the wrap
    # idempotency check.  Handlers are resolved by name from _handler_registry at CALL time, so a
    # reload that re-executes this module but hits the idempotency return below would otherwise
    # leave the PREVIOUS module version's closures live — meaning a refusal shipped in this file
    # would not actually be in force in the session that installed it.  register_handler overwrites
    # by name, so re-registering is idempotent and cheap.
    _register_gate_handlers(_d, gate)

    # Step 4: Wrap idempotency is SEPARATE from the GATE restore (R4C) and from handler
    # registration.  Check only after GATE is resolved so we never drop the live queue.
    if getattr(_d.dispatch, "_is_gated", False) is True:
        # The wrap is applied — but after importlib.reload() the installed callable is the PREVIOUS
        # module version's _gated_dispatch, so fork-side changes to the gated path are not in force.
        # Rebind to the current wrapper WITHOUT re-capturing _ORIGINAL_DISPATCH: it still points at
        # the real dispatch, and re-capturing here would wrap the gate around itself — the
        # double-wrap this guard exists to prevent.
        if _d.dispatch is not _gated_dispatch:
            _d.dispatch = _gated_dispatch
            _gated_dispatch._is_gated = True  # type: ignore[attr-defined]
            log.info("install_gate: rebound a stale gated dispatch to the reloaded wrapper")
        else:
            log.debug(
                "install_gate: gate wrap already applied (idempotent no-op); queue preserved"
            )
        return

    # Step 5: backstop-warn undeclared commands, wire wrap.
    _warn_undeclared_commands()

    # Preserve _ORIGINAL_DISPATCH before wrapping.
    _d._ORIGINAL_DISPATCH = _d.dispatch

    # Install the gated wrapper.
    _d.dispatch = _gated_dispatch
    _gated_dispatch._is_gated = True  # type: ignore[attr-defined]

    log.info(
        "install_gate: security gate installed (mode=%s)",
        gate.config.mode.value,
    )


# ---------------------------------------------------------------------------
# Gate command handlers
# ---------------------------------------------------------------------------

def _register_gate_handlers(_d, gate_ref) -> None:
    """Register the 7 gate control commands into the dispatcher.

    These are registered with READONLY capability so they are never themselves
    gated (they bypass via _GATE_COMMANDS frozenset in _gated_dispatch).
    Thunks use a late-binding lambda to _get_gate() so that if the gate
    singleton is replaced (e.g. in tests), handlers see the live object.
    """
    from homedini.dcc.mcp_gate.gate_model import Capability as CoreCap
    from homedini.dcc.mcp_gate.gate_model import Mode
    from homedini.dcc.mcp_gate.policy import is_mode_command_settable

    # --- gate.get_permission_mode ---
    def _get_permission_mode() -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        return {"gate": "allowed", "status": "success", "data": {"mode": _mode_str(g.config.mode)}}

    # --- gate.set_permission_mode ---
    def _set_permission_mode(mode: str) -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        # Normalize underscore → hyphen so both "read_only" and "read-only" are
        # accepted.  The pure-core Mode enum stores values with hyphens
        # (Mode.READ_ONLY.value == "read-only").  _mode_str() converts hyphens
        # back to underscores on OUTPUT; this is the symmetric INPUT path.
        _normalized = mode.replace("_", "-")
        try:
            new_mode = Mode(_normalized)
        except (ValueError, AttributeError):
            return {
                "gate": "allowed",
                "status": "error",
                "error": f"Unknown mode {mode!r}. Valid: {[m.value for m in Mode]}",
            }
        # ADR-0007 Phase 3: refuse any mode that is not command-settable.  TRUSTED is the only mode
        # whose decide() ALLOWs CODE_EXEC, so whoever can set it owns the scene.  The HTTP bridge
        # carries NO caller identity — the panel's own bridge_call and an agent shelling out to
        # curl are indistinguishable here — so the refusal is unconditional rather than
        # identity-based.  The panel only ever sets ACT_SAFE, which stays settable, so nothing
        # legitimate is lost.  Checked on the RESOLVED Mode enum, so string variants can't slip past.
        if not is_mode_command_settable(new_mode):
            log.warning(
                "gate.set_permission_mode: REFUSED escalation to %r (not command-settable)",
                new_mode.value,
            )
            _emit_refusal_audit(g, "gate.set_permission_mode")
            _settable = sorted(m.value for m in Mode if is_mode_command_settable(m))
            return {
                "gate": "allowed",
                "status": "denied",
                "error": (
                    f"Mode {new_mode.value!r} cannot be set through the gate-control command "
                    f"(ADR-0007). Settable modes: {_settable}."
                ),
            }
        from dataclasses import replace
        g.config = replace(g.config, mode=new_mode)
        log.info("gate.set_permission_mode: mode changed to %r", new_mode.value)
        return {"gate": "allowed", "status": "success", "data": {"mode": _mode_str(g.config.mode)}}

    # --- gate.list_pending_calls ---
    def _list_pending_calls() -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        raw_pending = g.queue.list()
        # PRESENTATION SPLIT (ADR 0005 rev2 §3.4e):
        # The pending_queue stores the preview blob as an opaque dict.
        # For the degrade case, the stored blob is {"preview_error": <str>},
        # which must be split into top-level preview_error and preview=None.
        # For the success case, the stored blob IS the payload -> keep as preview.
        presented: list[dict] = []
        for entry in raw_pending:
            e = dict(entry)  # shallow copy — don't mutate the queue
            stored = e.get("preview")
            # M-03: use structural envelope check instead of fragile len()==1.
            # A degrade marker is identified by having a "preview_error" key with
            # a string value.  This is robust to extra fields being present and
            # does not confuse a success payload that happens to contain
            # "preview_error" as a field name in its own schema (the string-value
            # check distinguishes: a real error is always a str from str(exc)).
            if (
                isinstance(stored, dict)
                and isinstance(stored.get("preview_error"), str)
            ):
                # Degrade marker: lift preview_error to top level; preview is None.
                e["preview_error"] = stored["preview_error"]
                e["preview"] = None
            # else: preview stays as-is (success payload or None)
            presented.append(e)
        return {"gate": "allowed", "status": "success", "data": {"pending": presented}}

    # --- gate.approve_pending_call ---
    def _approve_pending_call(pending_id: str) -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}

        # Peek at the pending entry BEFORE approving to capture the stored
        # preview payload (needed for re-validate divergence check).
        # peek_entry may be None if expired/not-found — we'll catch that below.
        pending_entries = g.queue.list()
        peek_entry = next(
            (e for e in pending_entries if e.get("id") == pending_id), None
        )

        # ADR-0007 Phase 3: refuse to approve anything that is not MUTATING.  With TRUSTED no
        # longer settable (see _set_permission_mode), NO mode ALLOWs CODE_EXEC — so approving a
        # queued CODE_EXEC call was the last remaining path from QUEUE to execution, i.e. a
        # backdoor around the execute_code FLOOR in policy.decide.  Refused for everyone because
        # the bridge has no caller identity.  MUTATING approvals are deliberately untouched: the
        # operator's propose-mode GateRail still approves reversible edits, which is what it is for.
        # Fail closed — only an explicitly MUTATING entry is approvable, so a missing or
        # unparseable capability refuses rather than runs.
        if peek_entry is None:
            # Refuse HERE rather than falling through to queue.approve()'s KeyError path. Both purge
            # expired entries first, so list() and approve() agree today — but authorization must
            # not depend on that staying true. Presentation output is not an authorization source,
            # and if the two ever diverged this branch would run an unchecked thunk.
            return {
                "gate": "allowed",
                "status": "error",
                "error": f"No pending call with id {pending_id!r} (expired or already handled).",
            }

        _entry_cap = str(peek_entry.get("capability", ""))
        if _entry_cap != CoreCap.MUTATING.value:
            log.warning(
                "gate.approve_pending_call: REFUSED approval of %r (capability=%r)",
                pending_id, _entry_cap,
            )
            # Audit the PENDING ENTRY's capability, not this gate command's own (readonly). The
            # entry is purged moments later, so recording "readonly" would leave a log from which
            # the actual refused attempt could never be reconstructed.
            _emit_refusal_audit(g, "gate.approve_pending_call", pending_id, capability=_entry_cap)
            return {
                "gate": "allowed",
                "status": "denied",
                "error": (
                    f"Pending call {pending_id!r} has capability {_entry_cap!r} and cannot be "
                    f"approved (ADR-0007). Only {CoreCap.MUTATING.value!r} calls are "
                    f"approvable — code execution has no approval path. Use "
                    f"gate.reject_pending_call to discard it."
                ),
            }

        # B3 / ADR 0005 rev2 §3.4f: retrieve original call params BEFORE the
        # approve() call removes the entry from the queue.  params_of() returns
        # None once the entry is gone (approve purges it), so we must capture
        # here while the entry is still present.
        stored_params_pre: dict = g.queue.params_of(pending_id) or {}  # type: ignore[attr-defined]

        # First check: is the pending_id known (raises KeyError if not)?
        try:
            raw_handler_result = g.queue.approve(pending_id)
        except KeyError:
            return {
                "gate": "allowed",
                "status": "error",
                "error": f"No pending call with id {pending_id!r} (expired or already handled).",
            }
        except Exception as exc:  # noqa: BLE001 — handler itself raised
            log.error("gate.approve_pending_call: handler raised: %s", exc, exc_info=True)
            wrapped = {
                "status": "error",
                "gate": "approved",
                "error": {
                    "code": type(exc).__name__,
                    "message": str(exc),
                },
            }
            return wrapped

        # Wrap the raw handler result the same way dispatcher._execute would.
        if isinstance(raw_handler_result, dict) and "status" in raw_handler_result:
            # Handler already returned a status-keyed dict — pass through.
            wrapped = dict(raw_handler_result)
        else:
            wrapped = {"status": "success", "data": raw_handler_result}

        # ADR 0005 rev2 §3.4f — Re-validate preview at approve time.
        # Run the preview_fn DIRECTLY (no _run_preview / no hdefereval) since
        # approve_pending_call is already running on the main thread — nesting
        # hdefereval here would deadlock (M-02 / B3).
        # Use stored params from the queue so the re-validate result matches the
        # original queue-time call (B3 fix: empty {} produced spurious divergence).
        if peek_entry is not None:
            command = peek_entry.get("tool", "")
            # Use params captured PRE-approve (stored_params_pre); the entry has
            # already been removed from the queue by g.queue.approve() above so
            # calling params_of() again would return None (B3 bug root cause).
            stored_params: dict = stored_params_pre
            if command:
                import fxhoudinimcp_server.dispatcher as _d2
                reg2 = _d2.preview_of(command)
                preview_fn2 = reg2.get("preview_fn")
                if preview_fn2 is not None:
                    stored_preview = peek_entry.get("preview")
                    # Stored preview may be the degrade marker; treat it as None
                    # for divergence purposes (we compare real payloads only).
                    stored_real = (
                        stored_preview
                        if isinstance(stored_preview, dict) and "preview_error" not in stored_preview
                        else None
                    )
                    # Call preview_fn directly — already on main thread (§3.4f ADR).
                    # Wrap in undos.disabler for consistency with _run_preview (ADV-004).
                    try:
                        try:
                            import hou  # type: ignore[import-untyped]
                            with hou.undos.disabler():
                                revalidate_payload = preview_fn2(stored_params)
                        except ImportError:
                            revalidate_payload = preview_fn2(stored_params)
                        revalidate_error = None
                    except Exception as exc:  # noqa: BLE001
                        revalidate_payload = None
                        revalidate_error = str(exc)
                    if revalidate_error is None and revalidate_payload is not None:
                        # Compare the re-validate result with the stored queue-time result.
                        if revalidate_payload != stored_real:
                            wrapped["divergence_warning"] = (
                                f"Preview verdict changed between queue time and approve time "
                                f"for command '{command}'. Queue-time: {stored_real!r}. "
                                f"Approve-time: {revalidate_payload!r}. "
                                "The operator should verify the current state before proceeding."
                            )

        # Emit approved audit event.
        g2 = _get_gate()
        if g2 is not None:
            try:
                from homedini.dcc.mcp_gate.gate_model import Severity, Classification
                cl = Classification(danger=False, classes=[], severity=Severity.NONE, reasons=[])
                _emit_audit_raw(g2, pending_id, "approved", cl)
            except Exception as exc2:  # noqa: BLE001
                log.warning("gate.approve_pending_call: audit emit failed: %s", exc2)

        wrapped["gate"] = "approved"
        wrapped["status"] = wrapped.get("status", "success")
        return wrapped

    # --- gate.reject_pending_call ---
    def _reject_pending_call(pending_id: str, reason: str = "") -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        try:
            g.queue.reject(pending_id, reason)
        except KeyError:
            return {
                "gate": "allowed",
                "status": "error",
                "error": f"No pending call with id {pending_id!r} (expired or already handled).",
            }
        return {"gate": "allowed", "status": "rejected", "pending_id": pending_id}

    # --- gate.classify_code ---
    def _classify_code(code: str, language: str = "python") -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        from homedini.dcc.mcp_gate.classifier import classify_python, classify_hscript
        if language == "hscript":
            cl = classify_hscript(code)
        else:
            cl = classify_python(code, g.config.danger_classes)
        return {
            "gate": "allowed",
            "status": "success",
            "data": {
                "classification": {
                    "danger": cl.danger,
                    "classes": cl.classes,
                    "severity": cl.severity.name,
                    "reasons": cl.reasons,
                    "capability": "code_exec",
                },
            },
        }

    # --- gate.get_audit_log ---
    def _get_audit_log(n: int = 50) -> dict:
        g = _get_gate()
        if g is None:
            return {"status": "error", "error": "Gate not installed"}
        entries = g.audit.tail(n)
        return {"gate": "allowed", "status": "success", "data": {"entries": entries}}

    # Register gate commands with explicit capability declarations.
    # gate.set_permission_mode is MUTATING — it changes operator-intent state
    # (the gate enforcement mode).  All others are READONLY introspection.
    # All 7 bypass the gate itself via _GATE_COMMANDS frozenset in _gated_dispatch.
    from fxhoudinimcp_server.dispatcher import Capability as ForkCap, register_handler
    for name, fn, cap in [
        ("gate.get_permission_mode",  _get_permission_mode,  ForkCap.READONLY),
        ("gate.set_permission_mode",  _set_permission_mode,  ForkCap.MUTATING),  # FIX-3: operator-intent state change
        ("gate.list_pending_calls",   _list_pending_calls,   ForkCap.READONLY),
        ("gate.approve_pending_call", _approve_pending_call, ForkCap.READONLY),
        ("gate.reject_pending_call",  _reject_pending_call,  ForkCap.READONLY),
        ("gate.classify_code",        _classify_code,        ForkCap.READONLY),
        ("gate.get_audit_log",        _get_audit_log,        ForkCap.READONLY),
    ]:
        register_handler(name, fn, capability=cap)


def _emit_audit_raw(gate, pending_id: str, event_type: str, classification) -> None:
    """Emit an audit event with a pending_id reference (approve/reject path)."""
    try:
        from homedini.dcc.mcp_gate.gate_model import AuditEvent
        cl_dict: dict = {
            "danger": classification.danger,
            "classes": list(classification.classes),
            "severity": (
                classification.severity.name
                if hasattr(classification.severity, "name")
                else str(classification.severity)
            ),
            "reasons": list(classification.reasons),
        }
        ev = AuditEvent(
            ts=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            event=event_type,
            tool="<approved>",
            capability="",
            mode=gate.config.mode.value,
            classification=cl_dict,
            code_sha256=None,
            pending_id=pending_id,
        )
        gate.audit.append(ev)
    except Exception as exc:  # noqa: BLE001
        log.warning("_emit_audit_raw: failed: %s", exc)
