"""Error path coverage (spec §12 — combined verification)."""
import logging
import socket
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod
from test_agents.observability.handlers import JsonlMultiHandler


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_setup_with_unwritable_dir(monkeypatch, tmp_path, capfd):
    """log_dir mkdir raises OSError → degrade silently."""
    def boom(*a, **kw): raise PermissionError("read-only fs")
    monkeypatch.setattr(Path, "mkdir", boom)
    logger_mod.setup_logging(log_dir=str(tmp_path / "x"), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []  # degraded to OFF
    err = capfd.readouterr().err
    assert "cannot create log dir" in err

def test_emit_with_unserializable_extra(tmp_path):
    """Logger.info with extra containing socket must not raise."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    log = logging.getLogger("test_agents.errortest")
    log.info("test", extra={"sock": socket.socket()})  # must not raise

def test_emit_with_circular_reference(tmp_path):
    """Circular dict must not raise (json marks as unserializable)."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    log = logging.getLogger("test_agents.errortest")
    d = {}
    d["self"] = d
    log.info("test", extra={"loop": d})  # must not raise

def test_lru_handle_eviction_does_not_crash_on_close_error(tmp_path, monkeypatch):
    """If an old per-trace file errored on close, eviction continues."""
    h = JsonlMultiHandler(log_dir=str(tmp_path), trace_handles=2)
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    rec.trace_id = "tr_a"
    h.emit(rec)
    # Force close to fail for the first file.
    fp = h._per_trace_handles["tr_a"]
    orig_close = fp.close
    fp.close = lambda: (_ for _ in ()).throw(OSError("flaky"))
    rec.trace_id = "tr_b"; h.emit(rec)
    rec.trace_id = "tr_c"; h.emit(rec)  # evicts tr_a, swallows OSError
    h.close()
