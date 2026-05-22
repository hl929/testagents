import importlib

import pytest

from test_agents.config import config


@pytest.fixture
def reload_config():
    """Reload config module after the test so module-level singleton state
    doesn't leak to other tests."""
    import test_agents.config as cfg_mod
    yield cfg_mod
    # Restore module to env-at-teardown state (monkeypatch has already restored env).
    importlib.reload(cfg_mod)


def test_config_has_v3_fields():
    assert hasattr(config, "MAX_PLAN_ITERATIONS")
    assert config.MAX_PLAN_ITERATIONS == 1
    assert hasattr(config, "MAX_CONFIRM_RETRIES")
    assert config.MAX_CONFIRM_RETRIES == 1
    assert hasattr(config, "MAX_WORKER_REFLECTIONS")
    assert config.MAX_WORKER_REFLECTIONS == 0
    assert hasattr(config, "EXPERIENCE_FILE")


def test_observability_config_defaults(monkeypatch, reload_config):
    """Observability config keys exist with documented defaults."""
    for k in (
        "TEST_AGENTS_LOG_LEVEL", "TEST_AGENTS_LOG_DIR",
        "TEST_AGENTS_LOG_TRACE_FILES", "TEST_AGENTS_LOG_TRACES_KEEP",
        "TEST_AGENTS_LOG_RETAIN_DAYS", "TEST_AGENTS_LOG_TRACE_HANDLES",
    ):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(reload_config)
    cfg = reload_config.config
    assert cfg.LOG_LEVEL == "INFO"
    assert cfg.LOG_DIR == "logs"
    assert cfg.LOG_TRACE_FILES is True
    assert cfg.LOG_TRACES_KEEP == 1000
    assert cfg.LOG_RETAIN_DAYS == 30
    assert cfg.LOG_TRACE_HANDLES == 64


def test_observability_config_overrides(monkeypatch, reload_config):
    monkeypatch.setenv("TEST_AGENTS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TEST_AGENTS_LOG_DIR", "/tmp/x")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACE_FILES", "false")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACES_KEEP", "500")
    monkeypatch.setenv("TEST_AGENTS_LOG_RETAIN_DAYS", "7")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACE_HANDLES", "32")
    importlib.reload(reload_config)
    cfg = reload_config.config
    assert cfg.LOG_LEVEL == "DEBUG"
    assert cfg.LOG_DIR == "/tmp/x"
    assert cfg.LOG_TRACE_FILES is False
    assert cfg.LOG_TRACES_KEEP == 500
    assert cfg.LOG_RETAIN_DAYS == 7
    assert cfg.LOG_TRACE_HANDLES == 32
