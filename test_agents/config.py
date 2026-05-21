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


config = Config()
