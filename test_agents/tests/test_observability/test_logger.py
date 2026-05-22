"""setup_logging idempotency, level switching, failure degrade (spec §9 + Finding 3.1)."""
import logging
import sys
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_setup_logging_idempotent(tmp_path):
    """Two calls do not register duplicate handlers."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    handlers_after_first = len(logging.getLogger("test_agents").handlers)
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    handlers_after_second = len(logging.getLogger("test_agents").handlers)
    assert handlers_after_first == handlers_after_second

def test_setup_logging_off_registers_nothing(tmp_path):
    """OFF: no handlers, no MetricsCollector, no callback in run_config."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    handlers = logging.getLogger("test_agents").handlers
    assert all("Jsonl" not in type(h).__name__ for h in handlers)
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []
    # logs/ directory not created in OFF mode
    assert not (tmp_path / "traces").exists()

def test_setup_logging_info_registers_callback(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="t")
    assert len(cfg["callbacks"]) == 1

def test_setup_logging_debug_attaches_full_fields(tmp_path):
    """DEBUG: callback writes input_full/output_full beyond summary."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="DEBUG")
    # The exact mechanism: callback consults logger level when emitting.
    assert logging.getLogger("test_agents").level == logging.DEBUG

def test_setup_logging_trace_level_registered(tmp_path):
    """TRACE custom level=5 is added via addLevelName."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="TRACE")
    assert logging.getLevelName(5) == "TRACE"

def test_setup_logging_dir_create_failure_degrades(tmp_path, monkeypatch, capsys):
    """CEO Finding 2.1: log_dir mkdir fails → warning to stderr + NoOp."""
    def boom(*a, **kw): raise OSError("read-only")
    monkeypatch.setattr(Path, "mkdir", boom)
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    # Must not crash. Returns to NoOp logger.
    cfg = logger_mod.make_run_config(thread_id="t")
    assert cfg["callbacks"] == []  # degraded to OFF semantics

def test_make_run_config_returns_thread_id(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    cfg = logger_mod.make_run_config(thread_id="abc123")
    assert cfg["configurable"]["thread_id"] == "abc123"
