"""Claude CLI 封装工具"""

import subprocess

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.config import config


class ClaudeCliTool(TestAgentTool):
    name: str = "claude_cli"
    description: str = "调用 Claude CLI 执行分析任务。prompt 为完整提示词，model 为可选模型名。"

    class InputSchema(BaseModel):
        prompt: str = Field(description="传递给 Claude CLI 的完整提示词")
        model: str = Field(default="", description="指定模型（可选）")

    args_schema: type = InputSchema

    def _run(self, prompt: str, model: str = "") -> str:
        if not prompt:
            return "错误: prompt 不能为空"

        cmd = ["claude", "--dangerously-skip-permissions", "-p", prompt]
        if model:
            cmd.extend(["--model", model])

        last_error = ""
        for attempt in range(config.CLAUDE_MAX_RETRIES):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=config.CLAUDE_TIMEOUT,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
                last_error = result.stderr.strip() or f"返回码: {result.returncode}"
            except subprocess.TimeoutExpired:
                last_error = f"Claude CLI 超时（{config.CLAUDE_TIMEOUT}秒）"
            except FileNotFoundError:
                return "错误: Claude CLI 未找到。请确认已安装并配置到 PATH 中。"
            except Exception as e:
                last_error = str(e)

        return f"错误: Claude CLI 调用失败（重试{config.CLAUDE_MAX_RETRIES}次）- {last_error}"
