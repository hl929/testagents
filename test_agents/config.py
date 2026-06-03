"""全局配置"""

import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Config:
    """配置类"""

    # LLM 配置
    LLM_MODEL: str = os.getenv("TEST_AGENTS_MODEL", "kimi-k2.6")
    LLM_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    LLM_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL")

    # Claude CLI 配置
    CLAUDE_TIMEOUT: int = int(os.getenv("TEST_AGENTS_CLAUDE_TIMEOUT", "1200"))
    CLAUDE_MAX_RETRIES: int = int(os.getenv("TEST_AGENTS_CLAUDE_RETRIES", "1"))

    # 业务知识库路径
    KNOWLEDGE_DIR: str = os.getenv("TEST_AGENTS_KNOWLEDGE_DIR", "")

    # v3 Plan-and-Solve + Reflection 配置
    MAX_PLAN_ITERATIONS: int = int(os.getenv("TEST_AGENTS_MAX_PLAN_ITERATIONS", "1"))
    MAX_CONFIRM_RETRIES: int = int(os.getenv("TEST_AGENTS_MAX_CONFIRM_RETRIES", "1"))
    MAX_WORKER_REFLECTIONS: int = int(os.getenv("TEST_AGENTS_MAX_WORKER_REFLECTIONS", "0"))
    EXPERIENCE_FILE: str = os.getenv(
        "TEST_AGENTS_EXPERIENCE_FILE",
        os.path.join(os.path.dirname(__file__), "data", "reflection_experience.md"),
    )

    # 数据库配置（data_analyst Worker）
    DB_URL: str = os.getenv("TEST_AGENTS_DB_URL", "")
    DB_QUERY_TIMEOUT: int = int(os.getenv("TEST_AGENTS_DB_QUERY_TIMEOUT", "30"))
    DB_MAX_ROWS: int = int(os.getenv("TEST_AGENTS_DB_MAX_ROWS", "500"))
    SCHEMA_DIR: str = os.getenv(
        "TEST_AGENTS_SCHEMA_DIR",
        os.path.join(os.path.dirname(__file__), "data", "schema"),
    )

    # 可观测体系配置（spec §6）
    LOG_LEVEL: str = os.getenv("TEST_AGENTS_LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("TEST_AGENTS_LOG_DIR", "logs")
    LOG_TRACE_FILES: bool = os.getenv("TEST_AGENTS_LOG_TRACE_FILES", "true").lower() == "true"
    LOG_TRACES_KEEP: int = int(os.getenv("TEST_AGENTS_LOG_TRACES_KEEP", "1000"))
    LOG_RETAIN_DAYS: int = int(os.getenv("TEST_AGENTS_LOG_RETAIN_DAYS", "30"))
    LOG_TRACE_HANDLES: int = int(os.getenv("TEST_AGENTS_LOG_TRACE_HANDLES", "64"))

    # Scheduler config
    SCHEDULER_TASKS_FILE: str = os.path.join(os.path.dirname(__file__), "data", "scheduled_tasks.json")
    SCHEDULER_PID_FILE: str = os.path.join(os.path.dirname(__file__), "data", "scheduler.pid")
    SCHEDULER_DEFAULT_OUTPUT: str = os.path.join(os.path.dirname(__file__), "logs", "scheduled_reports.md")
    SCHEDULER_DEFAULT_TIMEZONE: str = "Asia/Shanghai"


config = Config()
