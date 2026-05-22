"""ListDirTool - tree-style directory listing."""
import os
from pathlib import Path

from pydantic import BaseModel, Field

from test_agents.tools.base import TestAgentTool


_NOISE_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
_MAX_ENTRIES = 500
_MAX_DEPTH = 3


class _ListDirInput(BaseModel):
    path: str = Field(description="目录的绝对路径")
    depth: int = Field(default=1, description="递归深度（1-3）")
    show_hidden: bool = Field(default=False, description="是否显示 . 开头条目")


class ListDirTool(TestAgentTool):
    name: str = "list_dir"
    description: str = (
        "列出目录的内容（树形）。仅接受绝对路径。"
        "depth 控制递归深度（1-3）。show_hidden 控制是否显示 . 开头条目。"
        "始终跳过 .git/node_modules/__pycache__/.venv 等噪音目录。"
        "最多输出 500 个条目。"
    )
    args_schema: type = _ListDirInput

    def _run(self, path: str, depth: int = 1, show_hidden: bool = False) -> str:
        if not os.path.isabs(path):
            return f"错误: path 必须是绝对路径，收到: {path}"

        p = Path(path)
        if not p.exists():
            return f"错误: 目录不存在: {path}"
        if not p.is_dir():
            return f"错误: 路径不是目录: {path}"

        depth = max(1, min(_MAX_DEPTH, depth))
        entries: list[str] = []
        truncated = False

        def walk(d: Path, level: int, prefix: str):
            nonlocal truncated
            if level > depth or truncated:
                return
            try:
                with os.scandir(d) as it:
                    items = sorted(
                        it,
                        key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()),
                    )
            except OSError as e:
                entries.append(f"{prefix}(无法读取: {e!r})")
                return
            for entry in items:
                if truncated:
                    return
                if entry.name in _NOISE_DIRS:
                    continue
                if not show_hidden and entry.name.startswith("."):
                    continue
                if len(entries) >= _MAX_ENTRIES:
                    truncated = True
                    return
                if entry.is_symlink() and entry.is_dir():
                    # symlink to a directory — show but don't follow (prevents loops)
                    entries.append(f"{prefix}{entry.name} -> (symlink)")
                elif entry.is_dir(follow_symlinks=False):
                    entries.append(f"{prefix}{entry.name}/")
                    walk(Path(entry.path), level + 1, prefix + "  ")
                else:
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                        entries.append(f"{prefix}{entry.name} ({size}B)")
                    except OSError:
                        entries.append(f"{prefix}{entry.name}")

        walk(p, 1, "")
        body = "\n".join(entries)
        if truncated:
            body += f"\n⚠️ 条目超过 {_MAX_ENTRIES}，已截断"
        return body or "(空目录)"
