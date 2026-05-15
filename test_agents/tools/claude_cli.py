"""Claude CLI 封装工具"""

import subprocess
from typing import Dict, Any


class ClaudeCliTool:
    """通过 claude -p 调用 Claude CLI"""

    def __init__(self, timeout_seconds: int = 120, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.name = "claude_cli"
        self.description = "调用 Claude CLI 执行分析任务"

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 claude -p 命令"""
        prompt = parameters.get("prompt", "")
        model = parameters.get("model", "")

        if not prompt:
            return "错误: prompt 不能为空"

        cmd = ["claude", "-p", prompt]
        if model:
            cmd.extend(["--model", model])

        last_error = ""
        for attempt in range(self.max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )

                if result.returncode == 0:
                    return result.stdout.strip()

                last_error = result.stderr.strip() or f"返回码: {result.returncode}"

            except subprocess.TimeoutExpired:
                last_error = f"Claude CLI 超时（{self.timeout_seconds}秒）"
            except FileNotFoundError:
                return "错误: Claude CLI 未找到。请确认已安装并配置到 PATH 中。"
            except Exception as e:
                last_error = str(e)

        return f"错误: Claude CLI 调用失败（重试{self.max_retries}次）- {last_error}"

    def get_parameters(self) -> list[dict]:
        """获取参数定义"""
        return [
            {"name": "prompt", "type": "string", "description": "传递给 Claude CLI 的完整提示词", "required": True},
            {"name": "model", "type": "string", "description": "指定模型（可选）", "required": False},
        ]
