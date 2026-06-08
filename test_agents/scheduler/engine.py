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
