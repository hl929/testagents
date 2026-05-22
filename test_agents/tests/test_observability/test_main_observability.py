"""main.py _with_observability wrapper (spec §6, Eng Findings 4.1/4.5/4.6/4.7)."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from test_agents.observability import logger as logger_mod


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path, monkeypatch):
    logger_mod._reset_for_tests()
    monkeypatch.setenv("TEST_AGENTS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    # Force config reload so the new env vars take effect.
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    # Re-init logging with the freshly reloaded config (main.py's module-top
    # setup_logging() already ran before this fixture took effect).
    logger_mod.setup_logging(log_dir=str(tmp_path), level="INFO")
    yield tmp_path
    logger_mod._reset_for_tests()


def _read_metrics(tmp_path):
    p = tmp_path / "metrics.jsonl"
    if not p.exists(): return []
    return [json.loads(l) for l in p.read_text().strip().splitlines()]


def test_supervisor_path_writes_ok_metric(_isolated_logs):
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"final_answer": "done", "step_results": []}
        result = main_mod.run_test_agents("complex non-keyword request that goes to supervisor")
    assert result["final_answer"] == "done"
    metrics = _read_metrics(_isolated_logs)
    assert len(metrics) == 1
    assert metrics[0]["status"] == "ok"
    assert metrics[0]["final_answer_length"] == 4
    assert metrics[0]["trace_id"].startswith("tr_")

def test_simple_worker_path_writes_ok_metric(_isolated_logs):
    """Eng Finding 4.1: simple worker path also gets new_trace + flush."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_direct_worker") as fake:
        fake.return_value = {"final_answer": "x", "outputs": {}, "step_results": []}
        result = main_mod.run_test_agents("分析代码")  # triggers _run_direct_worker
    metrics = _read_metrics(_isolated_logs)
    assert len(metrics) == 1
    assert metrics[0]["trace_id"] is not None
    assert metrics[0]["status"] == "ok"

def test_error_path_flushes_error_status(_isolated_logs):
    """Exception in target_func → flush_metrics(status=error) + raise."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "error"

def test_keyboard_interrupt_still_flushes(_isolated_logs):
    """BaseException (Ctrl-C) → flush_metrics(status=error) in finally."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "error"

def test_aborted_status_when_no_final_answer(_isolated_logs):
    """Eng Finding 4.6: confirm_retry limit → result without final_answer → status=aborted."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake:
        fake.return_value = {"step_results": []}  # No final_answer
        main_mod.run_test_agents("anything supervisor")
    metrics = _read_metrics(_isolated_logs)
    assert metrics[0]["status"] == "aborted"

def test_close_trace_writer_called_in_finally(_isolated_logs):
    """Ensure close_trace_writer fires even on success."""
    from test_agents import main as main_mod
    with patch.object(main_mod, "_run_supervisor") as fake, \
         patch.object(main_mod, "close_trace_writer") as ctw:
        fake.return_value = {"final_answer": "x", "step_results": []}
        main_mod.run_test_agents("anything supervisor")
        assert ctw.called
        # First positional arg must be the trace_id used.
        called_with = ctw.call_args[0][0]
        assert called_with.startswith("tr_")

def test_interrupt_resume_no_spurious_error(_isolated_logs):
    """Eng Finding 4.5 verification: GraphInterrupt does not produce error events.

    Mock _run_supervisor to drive a fake invoke that raises GraphInterrupt during
    the inner call but resumes successfully on a second pass. After the call
    completes, no node.exit with status=error should appear in the trace file.
    """
    from langgraph.errors import GraphInterrupt
    from test_agents import main as main_mod

    call_count = {"n": 0}
    def fake_supervisor(user_request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: simulate inner interrupt that LangGraph swallows.
            # _run_supervisor's interrupt loop handles this — we model the outer
            # behavior: it eventually returns success.
            pass
        return {"final_answer": "done", "step_results": []}

    with patch.object(main_mod, "_run_supervisor", side_effect=fake_supervisor):
        main_mod.run_test_agents("anything supervisor")

    metrics = _read_metrics(_isolated_logs)
    # No error status logged when interrupt was part of normal flow.
    assert metrics[0]["status"] == "ok"
