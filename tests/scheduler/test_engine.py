from unittest.mock import MagicMock, patch

import pytest

from test_agents.scheduler.engine import SchedulerEngine
from test_agents.scheduler.models import ScheduledTask


@pytest.fixture
def mock_store(tmp_path):
    store = MagicMock()
    store.load.return_value = []
    store._path = str(tmp_path / "tasks.json")
    return store


def test_load_jobs(mock_store):
    engine = SchedulerEngine(mock_store)
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="hello")
    mock_store.load.return_value = [task]

    with patch.object(engine._scheduler, "add_job") as mock_add:
        engine.load_jobs()
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args.kwargs
        assert "trigger" in call_kwargs


def test_add_job(mock_store):
    engine = SchedulerEngine(mock_store)
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="hello")

    with patch.object(engine._scheduler, "add_job") as mock_add:
        engine.add_job(task)
        mock_add.assert_called_once()


def test_remove_job(mock_store):
    engine = SchedulerEngine(mock_store)
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="hello")

    with patch.object(engine._scheduler, "remove_job") as mock_remove:
        engine.remove_job(task.id)
        mock_remove.assert_called_once_with(task.id)


def test_start_shutdown(mock_store):
    engine = SchedulerEngine(mock_store)
    with patch.object(engine._scheduler, "start") as mock_start, \
         patch.object(engine._scheduler, "shutdown") as mock_shutdown:
        engine.start()
        mock_start.assert_called_once()
        engine.shutdown()
        mock_shutdown.assert_called_once()
