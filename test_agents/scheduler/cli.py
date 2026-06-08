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
