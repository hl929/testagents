import pytest
from pydantic import ValidationError
from test_agents.scheduler.models import ScheduledTask


def test_scheduled_task_defaults():
    task = ScheduledTask(
        name="test",
        cron="0 9 * * *",
        prompt="hello",
    )
    assert task.enabled is True
    assert task.timezone == "Asia/Shanghai"
    assert task.agent_hint == ""
    assert task.output_file.endswith("scheduled_reports.md")
    assert task.run_count == 0


def test_scheduled_task_invalid_cron():
    with pytest.raises(ValidationError) as exc_info:
        ScheduledTask(name="test", cron="not-a-cron", prompt="hello")
    assert "cron" in str(exc_info.value)


def test_scheduled_task_valid_agent_hint():
    task = ScheduledTask(name="test", cron="0 9 * * *", prompt="hello", agent_hint="code_analyzer")
    assert task.agent_hint == "code_analyzer"


def test_scheduled_task_invalid_agent_hint():
    with pytest.raises(ValidationError) as exc_info:
        ScheduledTask(name="test", cron="0 9 * * *", prompt="hello", agent_hint="invalid_agent")
    assert "agent_hint" in str(exc_info.value)
