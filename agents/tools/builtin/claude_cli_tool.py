"""ClaudeCliTool - 通过本地 Claude CLI 执行代码分析与理解任务"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ..base import Tool, ToolParameter


class ClaudeCliTool(Tool):
    """Claude CLI 工具

    通过本地安装的 `claude` 命令调用 Claude，用于代码分析、理解、审查等任务。
    支持指定工作目录和 session 复用。

    用法示例:
        tool = ClaudeCliTool()
        result = tool.run({
            "prompt": "分析这个项目的架构",
            "working_dir": "/home/hl/my-project",
            "session_id": "analysis-01"
        })
    """

    def __init__(
        self,
        default_working_dir: str = ".",
        default_timeout: int = 120,
        default_dangerously_skip_permissions: bool = True,
        max_output_size: int = 50 * 1024,  # 50KB
    ):
        super().__init__(
            name="claude_cli",
            description="调用本地 Claude CLI 执行代码分析、理解和推理任务"
        )
        self.default_working_dir = default_working_dir
        self.default_timeout = default_timeout
        self.default_dangerously_skip_permissions = default_dangerously_skip_permissions
        self.max_output_size = max_output_size

    def get_parameters(self) -> List[ToolParameter]:
        """获取工具参数定义"""
        return [
            ToolParameter(
                name="prompt",
                type="string",
                description="发送给 Claude 的提示词。示例: '分析这个函数的复杂度'",
                required=True,
            ),
            ToolParameter(
                name="working_dir",
                type="string",
                description="执行命令的工作目录（默认当前目录）",
                required=False,
                default=self.default_working_dir,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Claude session ID，用于复用上下文",
                required=False,
            ),
            ToolParameter(
                name="dangerously_skip_permissions",
                type="boolean",
                description="是否自动跳过权限提示",
                required=False,
                default=self.default_dangerously_skip_permissions,
            ),
            ToolParameter(
                name="timeout",
                type="integer",
                description="命令执行超时秒数",
                required=False,
                default=self.default_timeout,
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 Claude CLI 命令"""
        if not self.validate_parameters(parameters):
            return "❌ 参数验证失败：缺少必需的 prompt 参数"

        prompt = parameters.get("prompt", "").strip()
        if not prompt:
            return "❌ prompt 不能为空"

        # 检查 claude 命令是否存在
        claude_path = shutil.which("claude")
        if not claude_path:
            return "❌ 未找到 claude 命令，请确保 Claude CLI 已安装并加入 PATH"

        # 解析工作目录
        working_dir = parameters.get("working_dir", self.default_working_dir)
        working_path = Path(working_dir).resolve()
        if not working_path.exists():
            return f"❌ 工作目录不存在: {working_path}"
        if not working_path.is_dir():
            return f"❌ 工作目录不是有效目录: {working_path}"

        # 构建命令参数列表（避免 shell 注入）
        cmd = [claude_path, "-p", prompt]

        session_id = parameters.get("session_id")
        if session_id:
            cmd.extend(["--session-id", str(session_id)])

        dangerously_skip = parameters.get(
            "dangerously_skip_permissions",
            self.default_dangerously_skip_permissions,
        )
        if dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        timeout = parameters.get("timeout", self.default_timeout)

        # 执行命令
        try:
            result = subprocess.run(
                cmd,
                cwd=str(working_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"❌ 命令执行超时（超过 {timeout} 秒）"
        except OSError as e:
            return f"❌ 命令执行失败: {e}"
        except Exception as e:
            return f"❌ 执行 Claude CLI 时发生异常: {e}"

        # 合并输出
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"

        # 截断超长输出
        if len(output) > self.max_output_size:
            output = output[: self.max_output_size]
            output += f"\n\n⚠️ 输出被截断（超过 {self.max_output_size} 字节）"

        # 处理非零返回码
        if result.returncode != 0:
            output = f"⚠️ 命令返回码: {result.returncode}\n\n{output}"

        return output if output.strip() else "✅ 命令执行成功（无输出）"
