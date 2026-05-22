"""Public observability API (spec §4)."""
from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.context import (
    new_trace, get_trace_id, reset_trace,
)
from test_agents.observability.logger import (
    setup_logging, make_run_config, close_trace_writer,
)
from test_agents.observability import callback as _cb_mod


def flush_metrics(trace_id: str, status: str,
                  final_answer_length: int = 0, error: str | None = None) -> None:
    """Forward to the active MetricsCollector. No-op if logging is OFF."""
    if _cb_mod.metrics is None:
        return
    _cb_mod.metrics.flush(
        trace_id, status=status,
        final_answer_length=final_answer_length, error=error,
    )


def new_trace_metrics(trace_id: str, user_request: str) -> None:
    if _cb_mod.metrics is None:
        return
    _cb_mod.metrics.new_trace(trace_id, user_request=user_request)


__all__ = [
    "setup_logging", "make_run_config", "close_trace_writer",
    "new_trace", "get_trace_id", "reset_trace",
    "flush_metrics", "new_trace_metrics", "ObservabilityCallback",
]
