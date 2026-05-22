"""MetricsCollector singleton + per-trace counters (spec §4, §11)."""
import json
from pathlib import Path
import pytest

from test_agents.observability.metrics import MetricsCollector


def test_new_trace_metrics_initialises_counters(tmp_path):
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.new_trace("tr_abc", user_request="hello")
    snap = m._traces["tr_abc"]
    assert snap["node_count"] == 0
    assert snap["llm_call_count"] == 0
    assert snap["tool_call_count"] == 0
    assert snap["replan_count"] == 0
    assert snap["user_request"] == "hello"
    assert "ts_start" in snap

def test_incr_increments_named_counter(tmp_path):
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.new_trace("tr_abc", user_request="x")
    m.incr("tr_abc", "node_count")
    m.incr("tr_abc", "node_count")
    m.incr("tr_abc", "llm_call_count")
    assert m._traces["tr_abc"]["node_count"] == 2
    assert m._traces["tr_abc"]["llm_call_count"] == 1

def test_flush_appends_one_line_and_removes(tmp_path):
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    m.new_trace("tr_abc", user_request="x")
    m.incr("tr_abc", "node_count")
    m.flush("tr_abc", status="ok", final_answer_length=42)
    assert "tr_abc" not in m._traces
    line = p.read_text().strip()
    payload = json.loads(line)
    assert payload["trace_id"] == "tr_abc"
    assert payload["status"] == "ok"
    assert payload["node_count"] == 1
    assert payload["final_answer_length"] == 42

def test_flush_three_statuses(tmp_path):
    """Eng Finding 4.6: status ∈ {ok, error, aborted}."""
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    for tid, st in [("tr_a", "ok"), ("tr_b", "error"), ("tr_c", "aborted")]:
        m.new_trace(tid, user_request="x")
        m.flush(tid, status=st)
    statuses = [json.loads(l)["status"] for l in p.read_text().splitlines()]
    assert statuses == ["ok", "error", "aborted"]

def test_flush_missing_trace_safe(tmp_path):
    """Flushing an unknown trace_id must not raise."""
    m = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    m.flush("tr_never", status="ok")  # must not raise

def test_flush_write_failure_silent(tmp_path, monkeypatch, capsys):
    """CEO Finding 1.2: metrics write failure degrades to stderr."""
    p = tmp_path / "metrics.jsonl"
    m = MetricsCollector(metrics_path=str(p))
    m.new_trace("tr_abc", user_request="x")
    def boom(*a, **kw): raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)
    m.flush("tr_abc", status="ok")  # must not raise
