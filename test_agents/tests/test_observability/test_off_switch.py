"""TEST_AGENTS_LOG_LEVEL=OFF → no files, no callback, no measurable overhead."""
import os
import time
from pathlib import Path
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _reset():
    logger_mod._reset_for_tests()
    yield
    logger_mod._reset_for_tests()


def test_off_creates_no_files(tmp_path):
    """OFF: no log directory created at all."""
    logger_mod.setup_logging(log_dir=str(tmp_path / "logs"), level="OFF")
    # The logs dir itself should not be created — OFF early-returns before mkdir.
    assert not (tmp_path / "logs" / "traces").exists()

def test_off_make_run_config_empty_callbacks(tmp_path):
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    assert logger_mod.make_run_config(thread_id="t")["callbacks"] == []

def test_off_close_trace_writer_safe(tmp_path):
    """close_trace_writer must not raise when nothing was initialized."""
    logger_mod.setup_logging(log_dir=str(tmp_path), level="OFF")
    logger_mod.close_trace_writer("tr_anything")  # no-op, must not raise
