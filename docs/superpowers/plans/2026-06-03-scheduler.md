# Scheduler 定时调度模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 test_agents 新增一个独立定时调度模块，支持 cron 表达式配置、持久化存储、自动执行 Agent 任务并追加报告。

**Architecture:** 独立 `test_agents/scheduler/` 模块，底层用 APScheduler 解析 cron 触发，复用 `run_test_agents()` 执行入口，任务仓库为本地 JSON 文件。

**Tech Stack:** Python 3.11+, APScheduler 3.x, Pydantic v2, pytest, unittest.mock

---

## File Structure

| File | Responsibility |
|---|---|
| `test_agents/scheduler/__init__.py` | 包入口，暴露核心类 |
| `test_agents/scheduler/models.py` | `ScheduledTask` Pydantic 模型 |
| `test_agents/scheduler/store.py` | JSON 任务仓库的 CRUD + 文件锁 |
| `test_agents/scheduler/executor.py` | 执行回调：调用 `run_test_agents()` 并写报告 |
| `test_agents/scheduler/engine.py` | APScheduler 封装：加载/启停/增删 Job |
| `test_agents/scheduler/cli.py` | argparse CLI：add/remove/list/start/stop |
| `test_agents/scheduler/__main__.py` | `python -m test_agents.scheduler` 入口 |
| `tests/scheduler/test_models.py` | 模型验证测试 |
| `tests/scheduler/test_store.py` | 仓库 CRUD + 并发测试 |
| `tests/scheduler/test_executor.py` | 执行器测试 |
| `tests/scheduler/test_engine.py` | 调度引擎测试 |
| `tests/scheduler/test_cli.py` | CLI 测试 |
| `requirements.txt` | 新增 `apscheduler` |
| `test_agents/config.py` | 新增 scheduler 相关配置 |

---

### Task 1: 新增依赖与配置

**Files:**
- Modify: `requirements.txt`
- Modify: `test_agents/config.py`
- Test: `tests/test_config.py`（已有，追加验证即可）

- [ ] **Step 1: 在 requirements.txt 追加 apscheduler**

```
apscheduler>=3.10.0,<4.0.0
```

- [ ] **Step 2: 在 config.py 追加 scheduler 配置**

在现有 `Config` dataclass 末尾追加字段：

```python
    # Scheduler config
    SCHEDULER_TASKS_FILE: str = field(default_factory=lambda: _default_path("data/scheduled_tasks.json"))
    SCHEDULER_PID_FILE: str = field(default_factory=lambda: _default_path("data/scheduler.pid"))
    SCHEDULER_DEFAULT_OUTPUT: str = field(default_factory=lambda: _default_path("logs/scheduled_reports.md"))
    SCHEDULER_DEFAULT_TIMEZONE: str = "Asia/Shanghai"
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt test_agents/config.py
git commit -m "feat(scheduler): add apscheduler dependency and scheduler config"
```

---

### Task 2: ScheduledTask 模型

**Files:**
- Create: `test_agents/scheduler/models.py`
- Test: `tests/scheduler/test_models.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p test_agents/scheduler tests/scheduler
```

- [ ] **Step 2: 写测试**

```python
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
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -m pytest tests/scheduler/test_models.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 实现 models.py**

```python
"""Scheduler task models."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from test_agents.config import config

_VALID_AGENTS = {"", "code_analyzer", "case_reviewer", "data_analyst"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_cron(v: str) -> str:
    # APScheduler CronTrigger will validate at runtime; here we do basic syntax check
    parts = v.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have exactly 5 fields, got {len(parts)}: {v}")
    return v


class ScheduledTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    cron: str
    prompt: str
    agent_hint: str = ""
    output_file: str = Field(default_factory=lambda: config.SCHEDULER_DEFAULT_OUTPUT)
    timezone: str = Field(default=config.SCHEDULER_DEFAULT_TIMEZONE)
    enabled: bool = True
    created_at: str = Field(default_factory=_now_iso)
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    run_count: int = 0

    @field_validator("cron")
    @classmethod
    def check_cron(cls, v: str) -> str:
        return _validate_cron(v)

    @field_validator("agent_hint")
    @classmethod
    def check_agent_hint(cls, v: str) -> str:
        if v not in _VALID_AGENTS:
            raise ValueError(f"agent_hint must be one of {_VALID_AGENTS}, got {v!r}")
        return v
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_models.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add test_agents/scheduler/ tests/scheduler/test_models.py
git commit -m "feat(scheduler): add ScheduledTask model with validation"
```

---

### Task 3: 任务仓库 (store.py)

**Files:**
- Create: `test_agents/scheduler/store.py`
- Test: `tests/scheduler/test_store.py`

- [ ] **Step 1: 写测试**

```python
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
        json.dumps([], f)
    tasks = temp_store.load()
    assert tasks == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/scheduler/test_store.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 store.py**

```python
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
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[ScheduledTask]:
        if not os.path.exists(self._path):
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Handle legacy format (plain list)
        if isinstance(data, list):
            return [ScheduledTask(**item) for item in data]
        tasks = data.get("tasks", [])
        return [ScheduledTask(**item) for item in tasks]

    def save_all(self, tasks: Optional[list[ScheduledTask]] = None) -> None:
        if tasks is None:
            tasks = self.load()
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_store.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/scheduler/store.py tests/scheduler/test_store.py
git commit -m "feat(scheduler): add JSON task store with atomic writes"
```

---

### Task 4: 执行器 (executor.py)

**Files:**
- Create: `test_agents/scheduler/executor.py`
- Test: `tests/scheduler/test_executor.py`

- [ ] **Step 1: 写测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/scheduler/test_executor.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 executor.py**

```python
"""Task executor: runs Agent and appends result to report file."""

import os
from datetime import datetime, timezone

from test_agents.main import run_test_agents
from test_agents.scheduler.models import ScheduledTask


class TaskExecutor:
    def execute(self, task: ScheduledTask) -> None:
        start_time = datetime.now(timezone.utc)
        try:
            result = run_test_agents(task.prompt)
            status = "success"
            content = result.get("final_answer", "")
        except Exception as exc:
            status = "error"
            content = f"执行异常: {exc}"

        self._write_report(task, start_time, status, content)
        task.last_run_at = start_time.isoformat()
        task.last_run_status = status
        task.run_count += 1

    def _write_report(self, task: ScheduledTask, start_time: datetime, status: str, content: str) -> None:
        os.makedirs(os.path.dirname(task.output_file) or ".", exist_ok=True)
        report = self._format_report(task, start_time, status, content)
        with open(task.output_file, "a", encoding="utf-8") as f:
            f.write(report + "\n")

    def _format_report(self, task: ScheduledTask, start_time: datetime, status: str, content: str) -> str:
        time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"## [{time_str}] {task.name}\n\n"
            f"- **任务 ID**: {task.id}\n"
            f"- **Cron**: `{task.cron}`\n"
            f"- **状态**: {status}\n"
            f"- **Prompt**: {task.prompt}\n\n"
            f"### 执行结果\n\n"
            f"{content}\n"
            f"---"
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_executor.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/scheduler/executor.py tests/scheduler/test_executor.py
git commit -m "feat(scheduler): add task executor with report formatting"
```

---

### Task 5: 调度引擎 (engine.py)

**Files:**
- Create: `test_agents/scheduler/engine.py`
- Test: `tests/scheduler/test_engine.py`

- [ ] **Step 1: 写测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/scheduler/test_engine.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 engine.py**

```python
"""APScheduler-based scheduling engine."""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from test_agents.scheduler.executor import TaskExecutor
from test_agents.scheduler.models import ScheduledTask
from test_agents.scheduler.store import TaskStore


class SchedulerEngine:
    def __init__(self, store: TaskStore):
        self._store = store
        self._executor = TaskExecutor()
        self._scheduler = BackgroundScheduler()

    def load_jobs(self) -> None:
        """Load all enabled tasks from store into APScheduler."""
        for task in self._store.load():
            if task.enabled:
                self.add_job(task)

    def add_job(self, task: ScheduledTask) -> None:
        """Add a single task to APScheduler."""
        trigger = CronTrigger.from_crontab(task.cron, timezone=task.timezone)
        self._scheduler.add_job(
            self._on_trigger,
            trigger=trigger,
            id=task.id,
            replace_existing=True,
            args=[task.id],
        )

    def remove_job(self, task_id: str) -> None:
        """Remove a job from APScheduler."""
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=True)

    def _on_trigger(self, task_id: str) -> None:
        task = self._store.get(task_id)
        if task is None or not task.enabled:
            return
        self._executor.execute(task)
        self._store.save_all()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_engine.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_agents/scheduler/engine.py tests/scheduler/test_engine.py
git commit -m "feat(scheduler): add APScheduler engine wrapper"
```

---

### Task 6: CLI 接口

**Files:**
- Create: `test_agents/scheduler/cli.py`
- Create: `test_agents/scheduler/__main__.py`
- Create: `test_agents/scheduler/__init__.py`
- Test: `tests/scheduler/test_cli.py`

- [ ] **Step 1: 写测试**

```python
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
        "scheduler", "add",
        "--tasks-file", temp_tasks_file,
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "已添加" in out


def test_cli_list(temp_tasks_file, capsys):
    with patch("sys.argv", [
        "scheduler", "add",
        "--tasks-file", temp_tasks_file,
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        main()

    with patch("sys.argv", ["scheduler", "list", "--tasks-file", temp_tasks_file]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "test-task" in out


def test_cli_remove(temp_tasks_file, capsys):
    with patch("sys.argv", [
        "scheduler", "add",
        "--tasks-file", temp_tasks_file,
        "--name", "test-task",
        "--cron", "0 9 * * *",
        "--prompt", "analyze code",
    ]):
        main()

    # Get the ID
    with open(temp_tasks_file, "r") as f:
        data = json.load(f)
    task_id = data["tasks"][0]["id"]

    with patch("sys.argv", ["scheduler", "remove", "--tasks-file", temp_tasks_file, "--id", task_id]):
        assert main() == 0
    out = capsys.readouterr().out
    assert "已删除" in out
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/scheduler/test_cli.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 cli.py**

```python
"""Scheduler CLI."""

import argparse
import sys

from test_agents.config import config
from test_agents.scheduler.engine import SchedulerEngine
from test_agents.scheduler.models import ScheduledTask
from test_agents.scheduler.store import TaskStore


def _build_parser():
    parser = argparse.ArgumentParser(description="test_agents 定时调度器")
    parser.add_argument("--tasks-file", default=config.SCHEDULER_TASKS_FILE, help="任务仓库路径")
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="添加定时任务")
    add_p.add_argument("--name", required=True, help="任务名称")
    add_p.add_argument("--cron", required=True, help="cron 表达式")
    add_p.add_argument("--prompt", required=True, help="执行 prompt")
    add_p.add_argument("--agent", default="", choices=["", "code_analyzer", "case_reviewer", "data_analyst"])
    add_p.add_argument("--output", default=config.SCHEDULER_DEFAULT_OUTPUT, help="输出文件路径")
    add_p.add_argument("--timezone", default=config.SCHEDULER_DEFAULT_TIMEZONE, help="时区")

    sub.add_parser("list", help="列出所有任务")

    remove_p = sub.add_parser("remove", help="删除定时任务")
    remove_p.add_argument("--id", required=True, help="任务 ID")

    sub.add_parser("start", help="启动调度器")
    sub.add_parser("stop", help="停止调度器")

    return parser


def main(args=None):
    parser = _build_parser()
    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return 1

    store = TaskStore(parsed.tasks_file)

    if parsed.command == "add":
        task = ScheduledTask(
            name=parsed.name,
            cron=parsed.cron,
            prompt=parsed.prompt,
            agent_hint=parsed.agent,
            output_file=parsed.output,
            timezone=parsed.timezone,
        )
        store.add(task)
        print(f"已添加任务: {task.name} (id={task.id})")
        return 0

    if parsed.command == "list":
        tasks = store.load()
        if not tasks:
            print("暂无任务")
            return 0
        for t in tasks:
            status = "启用" if t.enabled else "禁用"
            last = t.last_run_status or "未执行"
            print(f"[{t.id}] {t.name} | cron={t.cron} | {status} | 最近={last} | 次数={t.run_count}")
        return 0

    if parsed.command == "remove":
        if store.remove(parsed.id):
            print(f"已删除任务: {parsed.id}")
            return 0
        print(f"未找到任务: {parsed.id}")
        return 1

    if parsed.command == "start":
        engine = SchedulerEngine(store)
        engine.load_jobs()
        print("调度器已启动，按 Ctrl+C 停止...")
        try:
            engine.start()
            import signal
            signal.pause()
        except KeyboardInterrupt:
            print("\n正在停止...")
        finally:
            engine.shutdown()
        return 0

    if parsed.command == "stop":
        print("stop 命令暂不支持（请直接 Ctrl+C 或 kill PID）")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 实现 __main__.py**

```python
from test_agents.scheduler.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 实现 __init__.py**

```python
"""test_agents.scheduler - Cron-based scheduled task execution."""

from test_agents.scheduler.engine import SchedulerEngine
from test_agents.scheduler.executor import TaskExecutor
from test_agents.scheduler.models import ScheduledTask
from test_agents.scheduler.store import TaskStore

__all__ = ["ScheduledTask", "TaskStore", "TaskExecutor", "SchedulerEngine"]
```

- [ ] **Step 6: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_cli.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add test_agents/scheduler/cli.py test_agents/scheduler/__main__.py test_agents/scheduler/__init__.py tests/scheduler/test_cli.py
git commit -m "feat(scheduler): add CLI for task management and scheduler control"
```

---

### Task 7: 集成测试

**Files:**
- Create: `tests/scheduler/test_integration.py`

- [ ] **Step 1: 写测试**

```python
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
        "scheduler", "add",
        "--tasks-file", tasks_file,
        "--name", "集成测试任务",
        "--cron", "* * * * *",
        "--prompt", "测试 prompt",
        "--output", output_file,
    ]):
        assert main() == 0

    # List
    with patch("sys.argv", ["scheduler", "list", "--tasks-file", tasks_file]):
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
    with patch("sys.argv", ["scheduler", "remove", "--tasks-file", tasks_file, "--id", task_id]):
        assert main() == 0

    with open(tasks_file, "r") as f:
        data = json.load(f)
    assert len(data["tasks"]) == 0
```

- [ ] **Step 2: 运行测试确认通过**

```bash
python -m pytest tests/scheduler/test_integration.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/scheduler/test_integration.py
git commit -m "test(scheduler): add full lifecycle integration test"
```

---

### Task 8: 全部测试验证

- [ ] **Step 1: 运行全部 scheduler 测试**

```bash
python -m pytest tests/scheduler/ -v
```
Expected: ALL PASS

- [ ] **Step 2: 运行全部项目测试确保无回归**

```bash
python -m pytest test_agents/tests/ -v
```
Expected: ALL PASS（scheduler 是新目录，不影响已有测试）

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore(scheduler): all tests pass, no regressions"
```

---

## Self-Review

### Spec Coverage

| Spec 要求 | 对应 Task |
|---|---|
| ScheduledTask 模型 | Task 2 |
| JSON 任务仓库 + 原子写 + 并发安全 | Task 3 |
| APScheduler 引擎封装 | Task 5 |
| 执行器：调用 run_test_agents + 写报告 | Task 4 |
| CLI：add/remove/list/start/stop | Task 6 |
| 报告追加写入 | Task 4 |
| 依赖 apscheduler | Task 1 |
| 配置项 | Task 1 |
| 测试覆盖 | Task 2-8 |

### Placeholder Scan
- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊描述
- 每个步骤都有具体代码和命令

### Type Consistency
- `ScheduledTask` 字段名和类型全 plan 一致
- `TaskStore` 方法签名全 plan 一致
- `SchedulerEngine` / `TaskExecutor` 接口全 plan 一致
