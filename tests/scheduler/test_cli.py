import json
import os
import tempfile
from unittest.mock import patch

import pytest

from test_agents.scheduler.cli import main


@pytest.fixture
def temp_tasks_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({"version": 1, "tasks": []}, f)
    yield path
    os.unlink(path)


def test_cli_add(temp_tasks_file, capsys):
    with patch("sys.argv", [
        "scheduler", "--tasks-file", temp_tasks_file,
        "add",
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "已添加" in out


def test_cli_list(temp_tasks_file, capsys):
    with patch("sys.argv", [
        "scheduler", "--tasks-file", temp_tasks_file,
        "add",
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        main()

    with patch("sys.argv", ["scheduler", "--tasks-file", temp_tasks_file, "list"]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "test-task" in out


def test_cli_remove(temp_tasks_file, capsys):
    with patch("sys.argv", [
        "scheduler", "--tasks-file", temp_tasks_file,
        "add",
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        main()

    # Get the ID
    with open(temp_tasks_file, "r") as f:
        data = json.load(f)
    task_id = data["tasks"][0]["id"]

    with patch("sys.argv", ["scheduler", "--tasks-file", temp_tasks_file, "remove", "--id", task_id]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "已删除" in out
