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
