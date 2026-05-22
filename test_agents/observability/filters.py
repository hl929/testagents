"""LogRecord enrichment filter (spec §4).

Injects trace_id from ContextVar into every record so handlers can
route per-trace files without business code passing it manually.
"""
import logging

from test_agents.observability.context import get_trace_id


class ContextInjectFilter(logging.Filter):
    """Inject trace_id from ContextVar into LogRecord.

    span_id / parent_span_id are NOT injected here (spec §4): the
    callback emits them via the logger.info(..., extra={"span_id": ...})
    path, since they're known at emit time and not via ContextVar.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id") or record.trace_id is None:
            record.trace_id = get_trace_id()
        # Always allow the record through.
        return True
