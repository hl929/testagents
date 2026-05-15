from test_agents.config import config


def test_config_has_v3_fields():
    assert hasattr(config, "MAX_PLAN_ITERATIONS")
    assert config.MAX_PLAN_ITERATIONS == 1
    assert hasattr(config, "MAX_CONFIRM_RETRIES")
    assert config.MAX_CONFIRM_RETRIES == 3
    assert hasattr(config, "MAX_WORKER_REFLECTIONS")
    assert config.MAX_WORKER_REFLECTIONS == 0
    assert hasattr(config, "EXPERIENCE_FILE")
