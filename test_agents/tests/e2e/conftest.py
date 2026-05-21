"""E2E 共享 fixture"""

import os
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

PYTHON = "/mnt/c/Users/root/python-sdk/python3.13.2/python.exe"


def _to_win_path(wsl_path: str) -> str:
    m = re.match(r"^/mnt/([a-z])/(.*)$", wsl_path)
    if m:
        drive = m.group(1).upper()
        rest = m.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"
    return wsl_path


def run_cli(args: list[str], stdin: str = "", timeout: int = 180) -> subprocess.CompletedProcess:
    """运行 test_agents CLI，返回 CompletedProcess

    stdin: 传入 piped input（如 "y\\n" 用于确认计划）
    """
    return subprocess.run(
        [PYTHON] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PROJECT_ROOT),
        input=stdin,
        timeout=timeout,
    )


def _has_api_key() -> bool:
    """检查 .env 或环境中是否有 OPENAI_API_KEY"""
    if os.getenv("OPENAI_API_KEY"):
        return True
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY=") and len(line) > 20:
                return True
    return False


def skip_if_no_api_key():
    """如果没有 OPENAI_API_KEY 则跳过"""
    if not _has_api_key():
        pytest.skip("OPENAI_API_KEY not set, skipping e2e test")
