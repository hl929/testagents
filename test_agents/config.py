"""全局配置"""

import os
from typing import Optional


class Config:
    """配置类"""

    # LLM 配置
    LLM_MODEL: str = os.getenv("TEST_AGENTS_MODEL", "gpt-4o")
    LLM_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

    # Claude CLI 配置
    CLAUDE_TIMEOUT: int = int(os.getenv("TEST_AGENTS_CLAUDE_TIMEOUT", "120"))
    CLAUDE_MAX_RETRIES: int = int(os.getenv("TEST_AGENTS_CLAUDE_RETRIES", "2"))

    # Git 配置
    GIT_TIMEOUT: int = int(os.getenv("TEST_AGENTS_GIT_TIMEOUT", "30"))

    # Diff 配置
    MAX_DIFF_SIZE: int = int(os.getenv("TEST_AGENTS_MAX_DIFF_SIZE", "100000"))

    # 业务知识库路径
    KNOWLEDGE_DIR: str = os.getenv("TEST_AGENTS_KNOWLEDGE_DIR", "")


config = Config()
