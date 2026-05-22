"""ObservabilityCallback — wraps LangGraph events into JSON logs (spec §5).

Class-level dicts (not self.) because each app.invoke creates a fresh
callback instance, but state must survive across invokes (interrupt → resume).

All callback methods are wrapped in try/except. A bug in observability
must NEVER propagate into the business graph (CEO Finding 4.1).
"""
import logging
import traceback
from time import perf_counter
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from test_agents.observability.context import get_trace_id, _new_span_id
from test_agents.observability.metrics import MetricsCollector
from test_agents.observability.serializer import summarize, full

logger = logging.getLogger("test_agents.observability.callback")

# Set by setup_logging(); tests inject directly.
metrics: MetricsCollector | None = None  # type: ignore[assignment]


class ObservabilityCallback(BaseCallbackHandler):
    # Class-level: shared across invokes within the same process.
    _spans: dict[UUID, dict] = {}  # run_id → {"span_id", "node", "t0"}
    _last_node_per_trace: dict[str, str] = {}  # trace_id → last node name

    # ---- chain (node) events ----

    def on_chain_start(self, serialized, inputs, *, run_id,
                       parent_run_id=None, metadata=None, **kw):
        try:
            node_name = (metadata or {}).get("langgraph_node")
            if not node_name:
                return  # Filter non-langgraph runnables.
            span_id = _new_span_id()
            parent_span = (self._spans.get(parent_run_id) or {}).get("span_id")
            self._spans[run_id] = {
                "span_id": span_id, "node": node_name, "t0": perf_counter(),
            }
            logger.info("node.enter", extra={
                "event": "node.enter",
                "node": node_name,
                "span_id": span_id,
                "parent_span_id": parent_span,
                "input_summary": summarize(inputs, kind="dict"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_start",
                "error": traceback.format_exc()[:500],
            })

    def on_chain_end(self, outputs, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            # Replan inference: reflect → planner transition (Eng Finding 2.2/4.2).
            last = self._last_node_per_trace.get(tid)
            if last == "reflect" and entry["node"] == "planner" and metrics and tid:
                metrics.incr(tid, "replan_count")
            if tid:
                self._last_node_per_trace[tid] = entry["node"]
            if metrics and tid:
                metrics.incr(tid, "node_count")
            logger.info("node.exit", extra={
                "event": "node.exit",
                "node": entry["node"],
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
                "output_summary": summarize(outputs, kind="dict"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_end",
                "error": traceback.format_exc()[:500],
            })

    def on_chain_error(self, error, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("node.exit", extra={
                "event": "node.exit",
                "node": entry["node"],
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "error",
                "error": {
                    "type": type(error).__name__,
                    "message": str(error)[:500],
                },
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed",
                "callback": "on_chain_error",
                "error": traceback.format_exc()[:500],
            })

    # ---- LLM events (Eng Finding 1.1: both chat + completion) ----

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._on_llm_start(serialized, messages, run_id, kind="chat")

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self._on_llm_start(serialized, prompts, run_id, kind="list")

    def _on_llm_start(self, serialized, payload, run_id, kind):
        try:
            span_id = _new_span_id()
            t0 = perf_counter()
            self._spans[run_id] = {"span_id": span_id, "node": "_llm", "t0": t0}
            model = (
                (serialized or {}).get("kwargs", {}).get("model_name")
                or ((serialized or {}).get("id") or [None])[-1]
            )
            logger.info("llm.call", extra={
                "event": "llm.call",
                "phase": "start",
                "span_id": span_id,
                "model": model,
                "input_summary": summarize(payload, kind=kind),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "_on_llm_start",
                "error": traceback.format_exc()[:500],
            })

    def on_chat_model_end(self, response, *, run_id, **kw):
        self._on_llm_end(response, run_id)

    def on_llm_end(self, response, *, run_id, **kw):
        self._on_llm_end(response, run_id)

    def _on_llm_end(self, response, run_id):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            if metrics and tid:
                metrics.incr(tid, "llm_call_count")
            tokens = getattr(response, "usage_metadata", None)
            extra = {
                "event": "llm.call",
                "phase": "end",
                "span_id": entry["span_id"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
            }
            if tokens:
                extra["tokens"] = {
                    "prompt": tokens.get("input_tokens"),
                    "completion": tokens.get("output_tokens"),
                    "total": tokens.get("total_tokens"),
                }
            logger.info("llm.call", extra=extra)
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "_on_llm_end",
                "error": traceback.format_exc()[:500],
            })

    def on_llm_error(self, error, *, run_id, **kw):
        self._on_llm_error(error, run_id)

    def on_chat_model_error(self, error, *, run_id, **kw):
        self._on_llm_error(error, run_id)

    def _on_llm_error(self, error, run_id):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("llm.call", extra={
                "event": "llm.call", "phase": "end",
                "span_id": entry["span_id"], "status": "error",
                "error": {"type": type(error).__name__, "message": str(error)[:500]},
            })
        except Exception:
            pass

    # ---- tool events ----

    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        try:
            span_id = _new_span_id()
            t0 = perf_counter()
            tool = (serialized or {}).get("name") or "_tool"
            self._spans[run_id] = {"span_id": span_id, "node": tool, "t0": t0}
            logger.info("tool.call", extra={
                "event": "tool.call", "phase": "start",
                "span_id": span_id, "tool": tool,
                "input_summary": summarize(input_str, kind="str"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "on_tool_start",
                "error": traceback.format_exc()[:500],
            })

    def on_tool_end(self, output, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            tid = get_trace_id()
            if metrics and tid:
                metrics.incr(tid, "tool_call_count")
            logger.info("tool.call", extra={
                "event": "tool.call", "phase": "end",
                "span_id": entry["span_id"], "tool": entry["node"],
                "duration_ms": int((perf_counter() - entry["t0"]) * 1000),
                "status": "ok",
                "output_summary": summarize(output, kind="str"),
            })
        except Exception:
            logger.warning("callback.failed", extra={
                "event": "callback.failed", "callback": "on_tool_end",
                "error": traceback.format_exc()[:500],
            })

    def on_tool_error(self, error, *, run_id, **kw):
        try:
            entry = self._spans.pop(run_id, None)
            if entry is None:
                return
            logger.error("tool.call", extra={
                "event": "tool.call", "phase": "end",
                "span_id": entry["span_id"], "tool": entry["node"],
                "status": "error",
                "error": {"type": type(error).__name__, "message": str(error)[:500]},
            })
        except Exception:
            pass

    # ---- trace teardown hook ----

    @classmethod
    def cleanup_trace(cls, trace_id: str) -> None:
        """Called from close_trace_writer to evict per-trace state (Eng Finding 4.3)."""
        cls._last_node_per_trace.pop(trace_id, None)
