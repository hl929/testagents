"""MetricsCollector — global singleton, dict[trace_id, counters] (spec §4).

Why not on ObservabilityCallback.self? Eng Finding 4.7: each app.invoke
creates a fresh callback instance. For traces that span multiple invokes
(confirm_plan interrupt → resume), per-instance state would lose half
the counters. We key by trace_id (from ContextVar) instead.
"""
import json
import sys
from datetime import datetime, timezone


class MetricsCollector:
    def __init__(self, metrics_path: str):
        self._path = metrics_path
        self._traces: dict[str, dict] = {}

    def new_trace(self, trace_id: str, user_request: str) -> None:
        self._traces[trace_id] = {
            "trace_id": trace_id,
            "ts_start": _iso_now(),
            "user_request": user_request,
            "node_count": 0,
            "llm_call_count": 0,
            "tool_call_count": 0,
            "replan_count": 0,
        }

    def incr(self, trace_id: str, key: str) -> None:
        snap = self._traces.get(trace_id)
        if snap is None:
            return
        snap[key] = snap.get(key, 0) + 1

    def flush(self, trace_id: str, status: str,
              final_answer_length: int = 0, error: str | None = None) -> None:
        snap = self._traces.pop(trace_id, None)
        if snap is None:
            return  # Unknown trace; nothing to flush.
        snap["ts_end"] = _iso_now()
        snap["status"] = status
        snap["final_answer_length"] = final_answer_length
        snap["error"] = error
        snap["duration_ms"] = _duration_ms(snap["ts_start"], snap["ts_end"])
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        except Exception as e:
            try:
                sys.__stderr__.write(f"[observability] metrics flush failed: {e}\n")
            except Exception:
                pass


def _iso_now() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _duration_ms(start_iso: str, end_iso: str) -> int:
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    try:
        s = datetime.strptime(start_iso, fmt)
        e = datetime.strptime(end_iso, fmt)
        return int((e - s).total_seconds() * 1000)
    except Exception:
        return 0
