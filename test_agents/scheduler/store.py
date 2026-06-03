"""Task repository backed by JSON file with atomic writes."""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from test_agents.scheduler.models import ScheduledTask


class TaskStore:
    def __init__(self, path: str):
        self._path = path
        self._tasks: list[ScheduledTask] = []
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[ScheduledTask]:
        if not os.path.exists(self._path):
            self._tasks = []
            return self._tasks
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Handle legacy format (plain list)
        if isinstance(data, list):
            self._tasks = [ScheduledTask(**item) for item in data]
            return self._tasks
        tasks = data.get("tasks", [])
        self._tasks = [ScheduledTask(**item) for item in tasks]
        return self._tasks

    def save_all(self, tasks: Optional[list[ScheduledTask]] = None) -> None:
        if tasks is None:
            tasks = self._tasks
        else:
            self._tasks = tasks
        data = {"version": 1, "tasks": [t.model_dump() for t in tasks]}
        self._atomic_write(data)

    def add(self, task: ScheduledTask) -> None:
        tasks = self.load()
        tasks.append(task)
        self.save_all(tasks)

    def remove(self, task_id: str) -> bool:
        tasks = self.load()
        for i, t in enumerate(tasks):
            if t.id == task_id:
                tasks.pop(i)
                self.save_all(tasks)
                return True
        return False

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        for t in self.load():
            if t.id == task_id:
                return t
        return None

    def _atomic_write(self, data: dict) -> None:
        dir_name = os.path.dirname(self._path) or "."
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, self._path)
        except Exception:
            os.unlink(tmp)
            raise
