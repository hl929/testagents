"""ObservabilityCallback behavior (spec §5, §13)."""
import logging
import uuid
import pytest

from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.context import new_trace, reset_trace
from test_agents.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def _reset_state():
    ObservabilityCallback._spans.clear()
    ObservabilityCallback._last_node_per_trace.clear()
    reset_trace()
    yield
    ObservabilityCallback._spans.clear()
    ObservabilityCallback._last_node_per_trace.clear()
    reset_trace()


def _uuid(): return uuid.uuid4()


def test_filter_non_langgraph_chain(caplog):
    """Sub-item 1: on_chain_start without metadata.langgraph_node returns silently."""
    cb = ObservabilityCallback()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"x": 1}, run_id=_uuid(), metadata={})
    # No node.enter event logged for non-langgraph chains.
    msgs = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
    assert msgs == []


def test_node_enter_records_span_and_parent(caplog):
    """on_chain_start with metadata.langgraph_node records node.enter with span."""
    cb = ObservabilityCallback()
    parent_id, child_id = _uuid(), _uuid()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"x": 1}, run_id=parent_id,
                          metadata={"langgraph_node": "planner"})
        cb.on_chain_start({}, {"y": 2}, run_id=child_id, parent_run_id=parent_id,
                          metadata={"langgraph_node": "dispatch"})
    enters = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
    assert len(enters) == 2
    assert enters[0].node == "planner"
    assert enters[1].node == "dispatch"
    assert enters[1].parent_span_id == enters[0].span_id


def test_replan_inference(tmp_path, monkeypatch):
    """Sub-item 2: reflect → planner transition increments replan_count."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "metrics.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("x")
    tid = "tr_x"
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: tid)
    metrics.new_trace(tid, user_request="t")

    cb = ObservabilityCallback()
    rid1, rid2 = _uuid(), _uuid()
    cb.on_chain_start({}, {}, run_id=rid1, metadata={"langgraph_node": "reflect"})
    cb.on_chain_end({}, run_id=rid1)
    cb.on_chain_start({}, {}, run_id=rid2, metadata={"langgraph_node": "planner"})
    cb.on_chain_end({}, run_id=rid2)
    assert metrics._traces[tid]["replan_count"] == 1


def test_serialization_three_kinds(caplog):
    """Sub-item 3: dict / chat / str event sources summarized correctly."""
    cb = ObservabilityCallback()
    class M:
        def __init__(self, c): self.content = c
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chain_start({}, {"k": "v"}, run_id=_uuid(),
                          metadata={"langgraph_node": "planner"})
        cb.on_chat_model_start({"id": ["openai", "ChatOpenAI"],
                                "kwargs": {"model_name": "gpt-4o"}},
                               [[M("hello"), M("world")]],
                               run_id=_uuid())
        cb.on_tool_start({}, "some tool input", run_id=_uuid())
    sums = {r.event: getattr(r, "input_summary", "") for r in caplog.records}
    assert "k" in sums.get("node.enter", "") and "v" in sums.get("node.enter", "")
    assert "hello" in sums.get("llm.call", "") or \
           "hello" in (caplog.records[1].input_summary)
    assert "some tool input" in sums.get("tool.call", "")


def test_callback_exception_not_propagating(caplog, monkeypatch):
    """Sub-item 4: internal callback bug never propagates to LangGraph."""
    cb = ObservabilityCallback()
    monkeypatch.setattr(
        "test_agents.observability.callback._new_span_id",
        lambda: 1 / 0,  # Inject an exception inside the callback.
    )
    with caplog.at_level(logging.WARNING):
        cb.on_chain_start({}, {"k": "v"}, run_id=_uuid(),
                          metadata={"langgraph_node": "planner"})
    # Must NOT raise. Warning must be logged.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("callback.failed" in m for m in msgs)


def test_tokens_extraction_present_and_missing(caplog, monkeypatch, tmp_path):
    """Sub-item 5: tokens from response.usage_metadata; missing → field absent."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t")
    metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")
    cb = ObservabilityCallback()
    class Resp:
        usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    class NoMeta: pass
    rid1, rid2 = _uuid(), _uuid()
    with caplog.at_level(logging.INFO, logger="test_agents.observability.callback"):
        cb.on_chat_model_start({"id": ["x"], "kwargs": {}}, [[]], run_id=rid1)
        cb.on_chat_model_end(Resp(), run_id=rid1)
        cb.on_chat_model_start({"id": ["x"], "kwargs": {}}, [[]], run_id=rid2)
        cb.on_chat_model_end(NoMeta(), run_id=rid2)
    ends = [r for r in caplog.records
            if getattr(r, "event", "") == "llm.call"
            and getattr(r, "phase", "") == "end"]
    assert len(ends) == 2
    assert ends[0].tokens["total"] == 15
    assert not hasattr(ends[1], "tokens") or ends[1].tokens is None


def test_chat_model_and_llm_both_implemented():
    """Sub-item 6 + Eng Finding 1.1: both on_chat_model_start AND on_llm_start."""
    cb = ObservabilityCallback()
    assert hasattr(cb, "on_chat_model_start")
    assert hasattr(cb, "on_llm_start")
    assert hasattr(cb, "on_chat_model_end")
    assert hasattr(cb, "on_llm_end")
    assert hasattr(cb, "on_chat_model_error")
    assert hasattr(cb, "on_llm_error")


def test_debug_level_emits_full_fields(caplog, monkeypatch, tmp_path):
    """Spec §9: DEBUG level adds input_full/output_full on top of summary."""
    import logging as _logging
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t"); metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")

    cb = ObservabilityCallback()
    rid = _uuid()
    cb_logger = _logging.getLogger("test_agents.observability.callback")
    # Force callback logger to DEBUG so isEnabledFor(DEBUG) returns True
    orig_level = cb_logger.level
    cb_logger.setLevel(_logging.DEBUG)
    try:
        with caplog.at_level(_logging.DEBUG, logger="test_agents.observability.callback"):
            cb.on_chain_start({}, {"big": "x" * 5000}, run_id=rid,
                              metadata={"langgraph_node": "planner"})
        records = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
        assert len(records) == 1
        # At DEBUG, input_full present and capped at 2000 chars (per spec §8)
        assert hasattr(records[0], "input_full")
        assert len(records[0].input_full) <= 2000
        # input_summary still present and capped at 200
        assert hasattr(records[0], "input_summary")
        assert len(records[0].input_summary) <= 200
    finally:
        cb_logger.setLevel(orig_level)


def test_info_level_omits_full_fields(caplog, monkeypatch, tmp_path):
    """Sanity: INFO level produces summary but NOT input_full."""
    import logging as _logging
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t"); metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")

    cb = ObservabilityCallback()
    rid = _uuid()
    cb_logger = _logging.getLogger("test_agents.observability.callback")
    orig_level = cb_logger.level
    cb_logger.setLevel(_logging.INFO)
    try:
        with caplog.at_level(_logging.INFO, logger="test_agents.observability.callback"):
            cb.on_chain_start({}, {"big": "x" * 5000}, run_id=rid,
                              metadata={"langgraph_node": "planner"})
        records = [r for r in caplog.records if getattr(r, "event", "") == "node.enter"]
        assert len(records) == 1
        # At INFO, input_full must NOT be set (or be absent)
        assert not hasattr(records[0], "input_full") or records[0].input_full is None
    finally:
        cb_logger.setLevel(orig_level)


def test_run_id_cleanup_on_all_eight_exits(monkeypatch, tmp_path):
    """Eng Finding 4.3: _spans dict has no leftovers after any end/error."""
    metrics = MetricsCollector(metrics_path=str(tmp_path / "m.jsonl"))
    monkeypatch.setattr("test_agents.observability.callback.metrics", metrics)
    new_trace("t"); metrics.new_trace("t", user_request="x")
    monkeypatch.setattr("test_agents.observability.callback.get_trace_id",
                        lambda: "t")
    cb = ObservabilityCallback()
    R = type("R", (), {})
    # 8 exits: chain_end, chain_error, chat_model_end, llm_end,
    # chat_model_error, llm_error, tool_end, tool_error
    for trigger in (
        lambda r: cb.on_chain_end({}, run_id=r),
        lambda r: cb.on_chain_error(Exception("x"), run_id=r),
        lambda r: cb.on_chat_model_end(R(), run_id=r),
        lambda r: cb.on_llm_end(R(), run_id=r),
        lambda r: cb.on_chat_model_error(Exception("x"), run_id=r),
        lambda r: cb.on_llm_error(Exception("x"), run_id=r),
        lambda r: cb.on_tool_end("out", run_id=r),
        lambda r: cb.on_tool_error(Exception("x"), run_id=r),
    ):
        rid = _uuid()
        cb.on_chain_start({}, {}, run_id=rid, metadata={"langgraph_node": "x"})
        assert rid in cb._spans
        trigger(rid)
        assert rid not in cb._spans  # cleanup on every exit path
