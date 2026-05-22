"""GlobTool - file name matching via `rg --files --glob`."""
import os
from pathlib import Path

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.tools.fs._rg import run_rg, RgNotInstalled


_DEFAULT_MAX_RESULTS = 200


class _GlobInput(BaseModel):
    pattern: str = Field(description="glob 模式，如 **/*.py 或 *.{ts,tsx}")
    path: str = Field(description="搜索根目录（绝对路径）")
    max_results: int = Field(default=_DEFAULT_MAX_RESULTS, description="结果截断条数")


class GlobTool(TestAgentTool):
    name: str = "glob"
    description: str = (
        "按文件名 glob 模式查找文件（基于 ripgrep --files --glob）。"
        "仅接受绝对路径。返回匹配的绝对路径列表，按修改时间倒序。"
        "默认尊重 .gitignore。最多返回 200 条。"
    )
    args_schema: type = _GlobInput

    def _run(
        self,
        pattern: str,
        path: str,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> str:
        if not os.path.isabs(path):
            return f"错误: path 必须是绝对路径，收到: {path}"

        args = ["--files", "--glob", pattern, path]
        try:
            rc, out, err = run_rg(args)
        except RgNotInstalled as e:
            return f"错误: {e}"
        except TimeoutError as e:
            return f"错误: {e}"
        except Exception as e:
            return f"错误: 工具执行失败 - {e!r}"

        if rc >= 2:
            return f"错误: ripgrep 退出码 {rc} - {err.strip() or '(no stderr)'}"

        paths = [p for p in out.splitlines() if p.strip()]
        if not paths:
            return "未找到匹配文件"

        def mtime(p):
            try:
                return Path(p).stat().st_mtime
            except OSError:
                return 0.0

        paths.sort(key=mtime, reverse=True)
        truncated = len(paths) > max_results
        if truncated:
            paths = paths[:max_results]
        body = "\n".join(paths)
        if truncated:
            body += f"\n\n⚠️ 结果超过 {max_results}，仅显示前 {max_results} 条"
        return body
