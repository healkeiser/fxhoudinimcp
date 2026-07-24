"""MCP tools for the security gate — permission mode, pending queue, audit log.

Exposes the 7 gate control commands as FastMCP tools so the AI client can
inspect and manage the gate without bypassing it.  These tools call the
gate command handlers that are registered by install_gate() on the Houdini
side; they bypass the gate policy by design (gate commands are in _GATE_COMMANDS).
"""

from __future__ import annotations

from mcp.server.fastmcp import Context

from fxhoudinimcp.server import mcp, _get_bridge


###### gate.get_permission_mode


@mcp.tool()
async def get_permission_mode(ctx: Context) -> dict:
    """Get the current MCP gate permission mode.

    Returns the active permission mode: 'trusted', 'propose', or 'read_only'.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("gate.get_permission_mode", {})


# NOTE (Homedini ADR-0007 Phase 2): the agent-facing `set_permission_mode` and
# `approve_pending_call` tools are DELIBERATELY NOT exposed. They are authority-escalation
# surfaces — an agent that can change its own permission tier, or approve its own queued call,
# defeats the gate. The in-Houdini agent panel sets the mode via a DIRECT bridge call
# (`homedini.ai.agent_panel.mcp_read.bridge_call` -> the `gate.set_permission_mode` dispatch
# command, which is still registered in middleware._register_gate_handlers), NOT through this
# FastMCP wrapper, so the panel is unaffected. Operator approval of a queued call likewise uses a
# direct bridge call, not an agent tool. The dispatch commands still exist; only the AGENT-reachable
# tool wrappers are withheld — the fence that lets a Codex child (which has no CLI --disallowed-tools)
# be added to the panel safely.


###### gate.list_pending_calls


@mcp.tool()
async def list_pending_calls(ctx: Context) -> dict:
    """List all pending calls awaiting operator approval.

    Returns a list of pending call summaries including their id, tool name,
    capability, and creation time.  Expired entries are excluded.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("gate.list_pending_calls", {})


# gate.approve_pending_call is intentionally NOT exposed as an agent tool (ADR-0007 Phase 2, see the
# note above): self-approving a queued call is the operator's decision, driven by a direct bridge
# call, never by the agent.


###### gate.reject_pending_call


@mcp.tool()
async def reject_pending_call(ctx: Context, pending_id: str, reason: str = "") -> dict:
    """Reject a queued call and discard it without running.

    Args:
        pending_id: The pending_id returned when the call was queued.
        reason: Optional human-readable reason for rejection.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "gate.reject_pending_call",
        {"pending_id": pending_id, "reason": reason},
    )


###### gate.classify_code


@mcp.tool()
async def classify_code(
    ctx: Context,
    code: str,
    language: str = "python",
) -> dict:
    """Classify code for security risk without executing it.

    Runs the gate's classifier and returns the danger classification.
    Does NOT execute the code or queue it for approval.

    Args:
        code: Source code string to classify.
        language: 'python' (default) or 'hscript'.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "gate.classify_code",
        {"code": code, "language": language},
    )


###### gate.get_audit_log


@mcp.tool()
async def get_audit_log(ctx: Context, n: int = 50) -> dict:
    """Retrieve the most recent gate audit log entries.

    Args:
        n: Number of most recent entries to return (default 50).

    Returns a list of audit event dicts with timestamp, event type, tool,
    mode, capability, danger classification, and pending_id where applicable.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("gate.get_audit_log", {"n": n})
