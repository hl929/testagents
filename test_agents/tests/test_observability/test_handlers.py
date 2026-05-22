"""JsonlMultiHandler emits to main + per-trace files (spec §5, §10, §12)."""
import json
import logging
from pathlib import Path
import pytest

from test_agents.observability.handlers import JsonlMultiHandler


def _make_record(trace_id=None, msg="hi"):
    rec = logging.LogRecord("t", logging.INFO, "f", 1, msg, None, None)
    rec.trace_id = trace_id
    return rec


def test_main_log_written(tmp_path):
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id="tr_abc01234"))
    h.close()
    files = list(tmp_path.glob("app-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["trace_id"] == "tr_abc01234"
    assert payload["message"] == "hi"


def test_per_trace_file_written(tmp_path):
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id="tr_abc01234", msg="event1"))
    h.emit(_make_record(trace_id="tr_abc01234", msg="event2"))
    h.close()
    trace_file = tmp_path / "traces" / "tr_abc01234.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "event1"
    assert json.loads(lines[1])["message"] == "event2"


def test_trace_id_none_skips_per_trace(tmp_path):
    """Eng Finding 4.1 + spec §12: trace_id=None → main log only."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    h.emit(_make_record(trace_id=None))
    h.close()
    assert not (tmp_path / "traces").exists() or \
           not any((tmp_path / "traces").iterdir())


def test_lru_evicts_oldest_handle(tmp_path):
    """Eng Finding 4.3: per-trace handle LRU evicts oldest beyond cap."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=2, write_per_trace=True)
    for i in range(5):
        h.emit(_make_record(trace_id=f"tr_{i:08x}", msg=f"m{i}"))
    # Only 2 handles open at any moment, but all 5 files exist on disk.
    files = sorted((tmp_path / "traces").glob("tr_*.jsonl"))
    assert len(files) == 5
    # Re-emitting an evicted trace must still work (re-open the file).
    h.emit(_make_record(trace_id="tr_00000000", msg="reopened"))
    h.close()
    content = (tmp_path / "traces" / "tr_00000000.jsonl").read_text()
    assert "m0" in content and "reopened" in content


def test_unserializable_object_marked(tmp_path):
    """CEO Finding 2.1: emit must not crash on unserializable extra."""
    import socket
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    rec = _make_record(trace_id="tr_abc01234")
    rec.extra_payload = {"sock": socket.socket()}
    h.emit(rec)  # must not raise
    h.close()
    files = list(tmp_path.glob("app-*.jsonl"))
    text = files[0].read_text()
    assert "___unserializable___" in text


def test_write_failure_silent_degrade(tmp_path, monkeypatch, capsys):
    """CEO Finding 1.2: emit OSError → stderr warning, no exception."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=4, write_per_trace=True)
    # Force underlying write to fail
    def boom(*a, **kw): raise OSError("disk full")
    monkeypatch.setattr(h, "_write_line", boom)
    h.emit(_make_record(trace_id="tr_abc01234"))  # must not raise
    # Spec: degrade to sys.__stderr__, do not re-raise.
