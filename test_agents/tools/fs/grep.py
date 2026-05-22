"""GrepTool - regex content search via ripgrep."""
import os

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool
from test_agents.tools.fs._rg import run_rg, RgNotInstalled


_DEFAULT_MAX_RESULTS = 100


class _GrepInput(BaseModel):
    pattern: str = Field(description="正则模式（ripgrep 默认引擎）")
    path: str = Field(description="搜索路径（绝对路径，可为文件或目录）")
    include: str = Field(default="", description="文件 glob 过滤，如 *.py")
    case_insensitive: bool = Field(default=False, description="是否忽略大小写")
    max_results: int = Field(default=_DEFAULT_MAX_RESULTS, description="结果截断条数")


class GrepTool(TestAgentTool):
    name: str = "grep"
    description: str = (
        "在文件内容中按正则搜索（基于 ripgrep）。仅接受绝对路径。"
        "输出格式 file:line:content。支持 include glob 过滤和 case_insensitive。"
        "默认尊重 .gitignore。最多返回 100 条匹配。"
    )
    args_schema: type = _GrepInput

    def _run(
        self,
        pattern: str,
        path: str,
        include: str = "",
        case_insensitive: bool = False,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> str:
        if not os.path.isabs(path):
            return f"错误: path 必须是绝对路径，收到: {path}"

        args = ["--line-number", "--no-heading", "--color=never"]
        if case_insensitive:
            args.append("-i")
        if include:
            args.extend(["-g", include])
        args.extend(["--", pattern, path])

        try:
            rc, out, err = run_rg(args)
        except RgNotInstalled as e:
            return f"错误: {e}"
        except TimeoutError as e:
            return f"错误: {e}，考虑缩小 path 或使用更精确的 include 过滤"
        except Exception as e:
            return f"错误: 工具执行失败 - {e!r}"

        if rc == 1:
            return "未找到匹配"
        if rc >= 2:
            return f"错误: ripgrep 退出码 {rc} - {err.strip() or '(no stderr)'}"

        lines = out.splitlines()
        truncated = len(lines) > max_results
        if truncated:
            lines = lines[:max_results]
        body = "\n".join(lines)
        if truncated:
            body += f"\n\n⚠️ 结果超过 {max_results}，仅显示前 {max_results} 条"
        return body
