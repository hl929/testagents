"""ContextInjectFilter injects trace_id into LogRecord (spec §4)."""
import logging
from test_agents.observability.context import new_trace, reset_trace
from test_agents.observability.filters import ContextInjectFilter


def _make_record():
    return logging.LogRecord(
        "test", logging.INFO, "f.py", 1, "msg", None, None,
    )


def test_filter_injects_trace_id_when_set():
    new_trace("x")
    rec = _make_record()
    ContextInjectFilter().filter(rec)
    assert rec.trace_id is not None
    assert rec.trace_id.startswith("tr_")
    reset_trace()


def test_filter_injects_none_when_unset():
    reset_trace()
    rec = _make_record()
    ContextInjectFilter().filter(rec)
    assert rec.trace_id is None


def test_filter_returns_true_always():
    """Filter must allow record through; this is an enricher, not a gate."""
    new_trace("x")
    assert ContextInjectFilter().filter(_make_record()) is True
    reset_trace()
    assert ContextInjectFilter().filter(_make_record()) is True


def test_filter_preserves_existing_extra():
    """If caller already supplied trace_id via extra=, do not overwrite."""
    new_trace("x")
    rec = _make_record()
    rec.trace_id = "tr_caller01"
    ContextInjectFilter().filter(rec)
    assert rec.trace_id == "tr_caller01"
    reset_trace()
