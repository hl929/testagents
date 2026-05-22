"""trace_id ContextVar + span_id generator (spec §7).

Spec §7 removed span_id_var on purpose — span_id is held in
ObservabilityCallback._spans (dict[run_id, span_id]). Only trace_id
is propagated via ContextVar across the call stack.
"""
import secrets
from contextvars import ContextVar

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

def new_trace(user_request: str) -> str:
    """Generate a new trace_id and store it in the ContextVar.

    Caller (main.py:_with_observability) owns trace lifecycle (spec §7).
    user_request kept in signature so MetricsCollector.new_trace_metrics
    can be called with the same value at the same site.
    """
    tid = "tr_" + secrets.token_hex(4)
    trace_id_var.set(tid)
    return tid

def get_trace_id() -> str | None:
    return trace_id_var.get()

def reset_trace() -> None:
    """Clear the trace_id. Idempotent."""
    trace_id_var.set(None)

def _new_span_id() -> str:
    return "sp_" + secrets.token_hex(4)
