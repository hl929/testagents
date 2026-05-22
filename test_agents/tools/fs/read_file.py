"""ReadFileTool - read a single file with cat -n style line numbers."""
import os
from pathlib import Path

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool


_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_LIMIT = 2000
_BINARY_SNIFF_BYTES = 4096


class _ReadFileInput(BaseModel):
    file_path: str = Field(description="文件的绝对路径")
    offset: int = Field(default=0, description="起始行号（0-based）")
    limit: int = Field(default=_DEFAULT_LIMIT, description="最多读取行数")


class ReadFileTool(TestAgentTool):
    name: str = "read_file"
    description: str = (
        "读取单个文件内容，输出带行号（与 `cat -n` 一致）。"
        "仅接受绝对路径。二进制文件、目录、不存在的路径会返回错误。"
        "大文件自动截断到前 2000 行。"
    )
    args_schema: type = _ReadFileInput

    def _run(self, file_path: str, offset: int = 0, limit: int = _DEFAULT_LIMIT) -> str:
        if not os.path.isabs(file_path):
            return f"错误: file_path 必须是绝对路径，收到: {file_path}"

        p = Path(file_path)
        if not p.exists():
            return f"错误: 文件不存在: {file_path}"
        if p.is_dir():
            return f"错误: 路径是目录，请用 list_dir: {file_path}"

        try:
            with open(p, "rb") as f:
                head = f.read(_BINARY_SNIFF_BYTES)
            if b"\x00" in head:
                return f"错误: 二进制文件无法读取: {file_path}"
        except OSError as e:
            return f"错误: 工具执行失败 - {e!r}"

        size = p.stat().st_size
        forced_truncate = size > _MAX_BYTES and limit == _DEFAULT_LIMIT

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = []
                for idx, line in enumerate(f, start=1):
                    if idx <= offset:
                        continue
                    if len(lines) >= limit:
                        break
                    lines.append((idx, line.rstrip("\n")))
        except OSError as e:
            return f"错误: 工具执行失败 - {e!r}"

        body = "\n".join(f"{idx:>6}\t{content}" for idx, content in lines)
        if forced_truncate:
            body += f"\n\n⚠️ 文件过大（{size} 字节），仅显示前 {_DEFAULT_LIMIT} 行"
        return body
