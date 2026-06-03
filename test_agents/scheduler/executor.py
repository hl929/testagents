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
