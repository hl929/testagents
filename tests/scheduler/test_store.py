import json
import os
import tempfile

import pytest

from test_agents.scheduler.models import ScheduledTask
from test_agents.scheduler.store import TaskStore


@pytest.fixture
def temp_store():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(json.dumps({"version": 1, "tasks": []}))
        path = f.name
    store = TaskStore(path)
    yield store
    os.unlink(path)


def test_load_empty(temp_store):
    tasks = temp_store.load()
    assert tasks == []


def test_add_and_load(temp_store):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="p1")
    temp_store.add(task)
    loaded = temp_store.load()
    assert len(loaded) == 1
    assert loaded[0].name == "t1"


def test_remove(temp_store):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="p1")
    temp_store.add(task)
    assert temp_store.remove(task.id) is True
    assert temp_store.load() == []
    assert temp_store.remove("nonexistent") is False


def test_get(temp_store):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="p1")
    temp_store.add(task)
    assert temp_store.get(task.id).name == "t1"
    assert temp_store.get("nonexistent") is None


def test_save_updates_existing(temp_store):
    task = ScheduledTask(name="t1", cron="0 9 * * *", prompt="p1")
    temp_store.add(task)
    task.run_count = 5
    temp_store.save_all()
    loaded = temp_store.load()
    assert loaded[0].run_count == 5


def test_migration_from_no_version(temp_store):
    # Simulate old file without version
    with open(temp_store._path, "w") as f:
        json.dump([], f)
    tasks = temp_store.load()
    assert tasks == []
