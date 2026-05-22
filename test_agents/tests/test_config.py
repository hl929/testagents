from test_agents.config import config


def test_config_has_v3_fields():
    assert hasattr(config, "MAX_PLAN_ITERATIONS")
    assert config.MAX_PLAN_ITERATIONS == 1
    assert hasattr(config, "MAX_CONFIRM_RETRIES")
    assert config.MAX_CONFIRM_RETRIES == 1
    assert hasattr(config, "MAX_WORKER_REFLECTIONS")
    assert config.MAX_WORKER_REFLECTIONS == 0
    assert hasattr(config, "EXPERIENCE_FILE")


def test_observability_config_defaults(monkeypatch):
    """Observability config keys exist with documented defaults."""
    for k in (
        "TEST_AGENTS_LOG_LEVEL", "TEST_AGENTS_LOG_DIR",
        "TEST_AGENTS_LOG_TRACE_FILES", "TEST_AGENTS_LOG_TRACES_KEEP",
        "TEST_AGENTS_LOG_RETAIN_DAYS", "TEST_AGENTS_LOG_TRACE_HANDLES",
    ):
        monkeypatch.delenv(k, raising=False)
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    cfg = cfg_mod.config
    assert cfg.LOG_LEVEL == "INFO"
    assert cfg.LOG_DIR == "logs"
    assert cfg.LOG_TRACE_FILES is True
    assert cfg.LOG_TRACES_KEEP == 1000
    assert cfg.LOG_RETAIN_DAYS == 30
    assert cfg.LOG_TRACE_HANDLES == 64


def test_observability_config_overrides(monkeypatch):
    monkeypatch.setenv("TEST_AGENTS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TEST_AGENTS_LOG_DIR", "/tmp/x")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACE_FILES", "false")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACES_KEEP", "500")
    monkeypatch.setenv("TEST_AGENTS_LOG_RETAIN_DAYS", "7")
    monkeypatch.setenv("TEST_AGENTS_LOG_TRACE_HANDLES", "32")
    import importlib, test_agents.config as cfg_mod
    importlib.reload(cfg_mod)
    cfg = cfg_mod.config
    assert cfg.LOG_LEVEL == "DEBUG"
    assert cfg.LOG_DIR == "/tmp/x"
    assert cfg.LOG_TRACE_FILES is False
    assert cfg.LOG_TRACES_KEEP == 500
    assert cfg.LOG_RETAIN_DAYS == 7
    assert cfg.LOG_TRACE_HANDLES == 32
