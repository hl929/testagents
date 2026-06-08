"""Full lifecycle integration test for the scheduler module."""
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from test_agents.scheduler.cli import main


@pytest.fixture
def temp_env():
    fd_tasks, tasks_path = tempfile.mkstemp(suffix=".json")
    os.close(fd_tasks)
    # mkstemp creates an empty file; initialize with valid JSON envelope so
    # TaskStore.load() does not choke on an empty file.
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tasks": []}, f)
    fd_out, out_path = tempfile.mkstemp(suffix=".md")
    os.close(fd_out)
    yield {"tasks": tasks_path, "output": out_path}
    os.unlink(tasks_path)
    os.unlink(out_path)


def test_full_lifecycle(temp_env):
    tasks_file = temp_env["tasks"]
    output_file = temp_env["output"]

    # Add task
    with patch("sys.argv", [
        "scheduler", "--tasks-file", tasks_file,
        "add",
        "--name", "集成测试任务",
        "--cron", "* * * * *",
        "--prompt", "测试 prompt",
        "--output", output_file,
    ]):
        assert main() == 0

    # List
    with patch("sys.argv", ["scheduler", "--tasks-file", tasks_file, "list"]):
        assert main() == 0

    # Verify store
    with open(tasks_file, "r") as f:
        data = json.load(f)
    assert len(data["tasks"]) == 1
    task_id = data["tasks"][0]["id"]

    # Simulate execution by calling executor directly
    from test_agents.scheduler.executor import TaskExecutor
    from test_agents.scheduler.models import ScheduledTask
    from test_agents.scheduler.store import TaskStore

    store = TaskStore(tasks_file)
    task = store.get(task_id)
    executor = TaskExecutor()

    with patch("test_agents.scheduler.executor.run_test_agents") as mock_run:
        mock_run.return_value = {"final_answer": "集成测试结果"}
        executor.execute(task)
        store.save_all([task])

    # Verify output file
    with open(output_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "集成测试任务" in content
    assert "集成测试结果" in content
    assert "success" in content

    # Remove
    with patch("sys.argv", ["scheduler", "--tasks-file", tasks_file, "remove", "--id", task_id]):
        assert main() == 0

    with open(tasks_file, "r") as f:
        data = json.load(f)
    assert len(data["tasks"]) == 0