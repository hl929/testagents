import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from test_agents.scheduler.executor import TaskExecutor
from test_agents.scheduler.models import ScheduledTask


@pytest.fixture
def temp_output():
    fd, path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    yield path
    os.unlink(path)


def test_execute_success(temp_output):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="hello", output_file=temp_output)
    executor = TaskExecutor()

    with patch("test_agents.scheduler.executor.run_test_agents") as mock_run:
        mock_run.return_value = {"final_answer": "result content"}
        executor.execute(task)

    mock_run.assert_called_once_with("hello")
    with open(temp_output, "r", encoding="utf-8") as f:
        content = f.read()
    assert "t1" in content
    assert "result content" in content
    assert "success" in content
    assert task.last_run_status == "success"
    assert task.run_count == 1


def test_execute_failure(temp_output):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="hello", output_file=temp_output)
    executor = TaskExecutor()

    with patch("test_agents.scheduler.executor.run_test_agents") as mock_run:
        mock_run.side_effect = RuntimeError("boom")
        executor.execute(task)

    with open(temp_output, "r", encoding="utf-8") as f:
        content = f.read()
    assert "error" in content
    assert "boom" in content
    assert task.last_run_status == "error"
    assert task.run_count == 1
