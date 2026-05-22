"""ContextVar lifecycle + span_id format tests (spec §7)."""
import re
from test_agents.observability.context import (
    new_trace, get_trace_id, _new_span_id, reset_trace,
)

def test_get_trace_id_default_none():
    reset_trace()
    assert get_trace_id() is None

def test_new_trace_sets_id():
    reset_trace()
    tid = new_trace("hello world")
    assert isinstance(tid, str)
    assert re.fullmatch(r"tr_[0-9a-f]{8}", tid)
    assert get_trace_id() == tid

def test_reset_trace_clears():
    new_trace("any")
    reset_trace()
    assert get_trace_id() is None

def test_new_trace_overwrites_previous():
    reset_trace()
    t1 = new_trace("first")
    t2 = new_trace("second")
    assert t1 != t2
    assert get_trace_id() == t2

def test_new_span_id_format_and_uniqueness():
    a = _new_span_id()
    b = _new_span_id()
    assert re.fullmatch(r"sp_[0-9a-f]{8}", a)
    assert re.fullmatch(r"sp_[0-9a-f]{8}", b)
    assert a != b
