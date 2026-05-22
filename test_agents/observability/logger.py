"""setup_logging entry + make_run_config helper (spec §9).

OFF: register nothing, return empty callbacks list — zero overhead.
INFO/DEBUG/TRACE: register Filter + JsonlMultiHandler + callback factory.
"""
import logging
import sys
from pathlib import Path

from test_agents.config import config
from test_agents.observability import callback as callback_mod
from test_agents.observability.callback import ObservabilityCallback
from test_agents.observability.filters import ContextInjectFilter
from test_agents.observability.handlers import JsonlMultiHandler
from test_agents.observability.metrics import MetricsCollector

_LOGGER_NAME = "test_agents"
_INITIALIZED = False
_ACTIVE_LEVEL: str = "OFF"
_HANDLER: JsonlMultiHandler | None = None

# Register custom TRACE level.
logging.addLevelName(5, "TRACE")


def setup_logging(
    log_dir: str | None = None, level: str | None = None,
) -> None:
    """Configure logging once at process start. Idempotent.

    OFF: no handlers registered, no metrics collector, no callback factory.
    """
    global _INITIALIZED, _ACTIVE_LEVEL, _HANDLER
    if _INITIALIZED:
        return

    chosen_level = (level or config.LOG_LEVEL).upper()
    chosen_dir = log_dir or config.LOG_DIR

    if chosen_level == "OFF":
        _ACTIVE_LEVEL = "OFF"
        _INITIALIZED = True
        return

    try:
        Path(chosen_dir).mkdir(parents=True, exist_ok=True)
        (Path(chosen_dir) / "traces").mkdir(parents=True, exist_ok=True)
    except Exception as e:
        try:
            sys.__stderr__.write(
                f"[observability] cannot create log dir {chosen_dir}: {e}. "
                f"Degrading to OFF.\n"
            )
        except Exception:
            pass
        _ACTIVE_LEVEL = "OFF"
        _INITIALIZED = True
        return

    py_level = {
        "TRACE": 5, "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
    }.get(chosen_level, logging.INFO)

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(py_level)
    root.propagate = False

    _HANDLER = JsonlMultiHandler(
        log_dir=chosen_dir,
        trace_handles=config.LOG_TRACE_HANDLES,
        write_per_trace=config.LOG_TRACE_FILES,
        retain_days=config.LOG_RETAIN_DAYS,
    )
    _HANDLER.addFilter(ContextInjectFilter())
    root.addHandler(_HANDLER)

    callback_mod.metrics = MetricsCollector(
        metrics_path=str(Path(chosen_dir) / "metrics.jsonl"),
    )

    _ACTIVE_LEVEL = chosen_level
    _INITIALIZED = True


def make_run_config(thread_id: str) -> dict:
    """Build the LangGraph invoke config (spec §6).

    OFF mode: empty callbacks list, no observability cost.
    """
    callbacks = [] if _ACTIVE_LEVEL == "OFF" else [ObservabilityCallback()]
    return {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
    }


def close_trace_writer(trace_id: str | None = None) -> None:
    """Called from main.py finally. Closes per-trace handle + cleans callback state."""
    if _HANDLER and trace_id:
        try:
            _HANDLER.close_trace(trace_id)
        except Exception:
            pass
        try:
            ObservabilityCallback.cleanup_trace(trace_id)
        except Exception:
            pass


def _reset_for_tests() -> None:
    """Test-only: clear singleton state so setup_logging can run again."""
    global _INITIALIZED, _ACTIVE_LEVEL, _HANDLER
    if _HANDLER:
        try:
            _HANDLER.close()
        except Exception:
            pass
    _HANDLER = None
    _ACTIVE_LEVEL = "OFF"
    _INITIALIZED = False
    root = logging.getLogger(_LOGGER_NAME)
    for h in list(root.handlers):
        root.removeHandler(h)
    callback_mod.metrics = None
