"""Git 变更提取工具 - 带安全验证"""

import re
import subprocess
from typing import Dict, Any


# diff 大小阈值（字符数）
MAX_DIFF_SIZE = 100_000  # 100KB


def extract_diff_summary(diff_content: str) -> str:
    """从 diff 内容提取摘要"""
    if not diff_content:
        return "无变更"

    lines = diff_content.split("\n")
    files = []
    additions = 0
    deletions = 0

    for line in lines:
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                files.append(parts[-1].replace("b/", ""))
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    summary = f"变更文件: {', '.join(files)}\n"
    summary += f"新增: {additions} 行, 删除: {deletions} 行\n"

    # 如果 diff 太大，只返回摘要
    if len(diff_content) > MAX_DIFF_SIZE:
        summary += f"\n[Diff 内容超过 {MAX_DIFF_SIZE} 字符，已截断]"
        # 保留前 500 行作为预览
        preview = "\n".join(lines[:500])
        summary += f"\n预览:\n{preview}"
    else:
        summary += f"\n{diff_content}"

    return summary


class GitDiffTool:
    """提取指定模块在 commit 范围内的代码变更"""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self.name = "git_diff"
        self.description = "提取指定模块在两个 commit 之间的代码变更"

    def _validate_inputs(self, module_name: str, source_commit: str, target_commit: str) -> None:
        """验证输入参数，防止命令注入"""
        if not re.match(r"^[a-f0-9]{7,40}$", source_commit, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {source_commit}")
        if not re.match(r"^[a-f0-9]{7,40}$", target_commit, re.IGNORECASE):
            raise ValueError(f"Invalid commit SHA: {target_commit}")
        if ".." in module_name or module_name.startswith("/"):
            raise ValueError(f"Invalid module name: {module_name}")

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行 git diff 并返回变更摘要"""
        module_name = parameters.get("module_name", "")
        source_commit = parameters.get("source_commit", "")
        target_commit = parameters.get("target_commit", "")

        self._validate_inputs(module_name, source_commit, target_commit)

        try:
            result = subprocess.run(
                [
                    "git", "diff",
                    f"{source_commit}..{target_commit}",
                    "--",
                    f"{module_name}/",
                ],
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=30,
            )

            if result.returncode != 0:
                return f"错误: git diff 失败 - {result.stderr}"

            return extract_diff_summary(result.stdout)

        except subprocess.TimeoutExpired:
            return "错误: git diff 超时（30秒）"
        except FileNotFoundError:
            return "错误: git 命令未找到，请确认 git 已安装"
        except Exception as e:
            return f"错误: {str(e)}"

    def get_parameters(self) -> list[dict]:
        """获取参数定义"""
        return [
            {"name": "module_name", "type": "string", "description": "模块路径", "required": True},
            {"name": "source_commit", "type": "string", "description": "源 commit SHA", "required": True},
            {"name": "target_commit", "type": "string", "description": "目标 commit SHA", "required": True},
        ]
