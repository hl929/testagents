# Local FS Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `code_analyzer` worker 增加 4 个只读的本地文件系统工具（read_file / list_dir / grep / glob），让 agent 能直接访问任意绝对路径下的代码仓库（如 `/mnt/d/obs_node/`），无需绕道 Claude CLI。

**Architecture:** 4 个工具继承 `TestAgentTool` 自动注册。`read_file` 和 `list_dir` 使用 Python 原生 `pathlib` / `os.walk`；`grep` 和 `glob` 通过 `subprocess.run([...])`（无 `shell=True`）调用 ripgrep。共享 `_rg.py` 集中处理 rg 二进制定位、超时、错误转换。所有工具仅接受绝对路径，无 cwd 状态，与 LangGraph 并发执行兼容。

**Tech Stack:** Python 3.10+、`langchain-core` BaseTool、`pydantic` v2 schema、`subprocess`、ripgrep 14+（系统依赖）、pytest

**Spec:** `docs/superpowers/specs/2026-05-21-local-fs-tools-design.md`

## File Structure

| 文件 | 类型 | 职责 |
|---|---|---|
| `test_agents/tools/fs/__init__.py` | Create | 空文件（占位包） |
| `test_agents/tools/fs/_rg.py` | Create | `run_rg(args, timeout)` 共享封装；统一错误（rg 未装 / 超时） |
| `test_agents/tools/fs/read_file.py` | Create | `ReadFileTool` —— 读单个文件，cat -n 行号格式，二进制/超大保护 |
| `test_agents/tools/fs/list_dir.py` | Create | `ListDirTool` —— 树形列目录，跳过噪音目录，500 条截断 |
| `test_agents/tools/fs/grep.py` | Create | `GrepTool` —— 调 rg 做正则搜索，include 过滤，100 条截断 |
| `test_agents/tools/fs/glob.py` | Create | `GlobTool` —— 调 `rg --files --glob` 做文件名匹配，mtime 排序，200 条截断 |
| `test_agents/tools/__init__.py` | Modify | 追加 4 个 import 触发自动注册 |
| `test_agents/agents/code_analyzer.py` | Modify | 工具列表新增 4 个工具 |
| `test_agents/tests/test_fs_tools.py` | Create | ~20 条用例覆盖 4 个工具 + 注册集成 |
| `test_agents/tests/test_workers.py` | Modify | 新增 1 条用例断言 code_analyzer 绑定了 5 个工具 |
| `test_agents/prompts/code_analyzer.md` | Modify | 提示 LLM 4 个新工具可用，附跨仓库示范 |
| `README.md` | Modify | 新增 "系统依赖：ripgrep" 安装命令 |
| `CLAUDE.md` | Modify | 工具层段落补充 4 个工具及绑定 |

---

## Task 1: 安装 ripgrep 并验证可用

**Files:** （无代码改动；环境准备）

- [ ] **Step 1: 安装 ripgrep**

WSL/Ubuntu：
```bash
sudo apt update && sudo apt install -y ripgrep
```

macOS：
```bash
brew install ripgrep
```

Windows (scoop)：
```powershell
scoop install ripgrep
```

- [ ] **Step 2: 验证安装**

Run: `which rg && rg --version | head -1`
Expected: 输出形如
```
/usr/bin/rg
ripgrep 14.x.x
```

- [ ] **Step 3: 验证 rg 基本功能**

Run: `rg --files --glob '*.py' /mnt/d/testagents/test_agents | head -5`
Expected: 列出 5 个 .py 文件路径，无报错

---

## Task 2: 创建 fs 子包与 `_rg.py` 共享封装（TDD）

**Files:**
- Create: `test_agents/tools/fs/__init__.py`
- Create: `test_agents/tools/fs/_rg.py`
- Create: `test_agents/tests/test_fs_tools.py`

- [ ] **Step 1: 创建空 `__init__.py`**

Run: `mkdir -p test_agents/tools/fs && touch test_agents/tools/fs/__init__.py`
Expected: 文件存在，0 字节

- [ ] **Step 2: 写失败测试 `_rg` 三个核心行为**

Create `test_agents/tests/test_fs_tools.py`:

```python
"""Tests for test_agents.tools.fs"""
import shutil
import pytest

from test_agents.tools.fs._rg import run_rg, RgNotInstalled


pytestmark_requires_rg = pytest.mark.skipif(
    shutil.which("rg") is None,
    reason="ripgrep 未安装，跳过依赖 rg 的测试",
)


class TestRunRg:
    @pytestmark_requires_rg
    def test_run_rg_returns_tuple(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello world\n")
        rc, out, err = run_rg(["hello", str(tmp_path)])
        assert rc == 0
        assert "hello" in out
        assert err == ""

    @pytestmark_requires_rg
    def test_run_rg_no_match_returns_rc_1(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello\n")
        rc, out, err = run_rg(["nonexistent_pattern_xyz", str(tmp_path)])
        assert rc == 1
        assert out == ""

    def test_run_rg_raises_when_not_installed(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(RgNotInstalled) as exc_info:
            run_rg(["foo", "."])
        assert "apt install ripgrep" in str(exc_info.value)
```

- [ ] **Step 3: 运行测试，确认 3 条都失败**

Run: `python -m pytest test_agents/tests/test_fs_tools.py -v`
Expected: 3 个测试 FAIL（ImportError: cannot import name 'run_rg'）

- [ ] **Step 4: 实现 `_rg.py`**

Create `test_agents/tools/fs/_rg.py`:

```python
"""Shared ripgrep subprocess wrapper."""
import shutil
import subprocess


class RgNotInstalled(RuntimeError):
    """raised when `rg` binary is not on PATH"""


_INSTALL_HINT = (
    "未找到 ripgrep。请安装："
    "apt install ripgrep / brew install ripgrep / scoop install ripgrep"
)


def run_rg(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Call ripgrep with the given args (list form, no shell).

    Returns: (returncode, stdout, stderr)
    Raises:
        RgNotInstalled: when `rg` is not on PATH
        TimeoutError: when subprocess exceeds `timeout` seconds
    """
    rg_path = shutil.which("rg")
    if rg_path is None:
        raise RgNotInstalled(_INSTALL_HINT)

    try:
        result = subprocess.run(
            [rg_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"ripgrep 超时（{timeout}s）") from e
```

- [ ] **Step 5: 运行测试，确认 3 条都通过**

Run: `python -m pytest test_agents/tests/test_fs_tools.py -v`
Expected: 3 passed（若 ripgrep 未装，第 1、2 条 skipped，第 3 条 passed）

- [ ] **Step 6: 提交**

```bash
git add test_agents/tools/fs/__init__.py test_agents/tools/fs/_rg.py test_agents/tests/test_fs_tools.py
git commit -m "feat(tools): add ripgrep subprocess wrapper for fs tools"
```

---

## Task 3: 实现 `ReadFileTool`（TDD）

**Files:**
- Create: `test_agents/tools/fs/read_file.py`
- Modify: `test_agents/tests/test_fs_tools.py`（追加测试类）

- [ ] **Step 1: 写失败测试**

Append to `test_agents/tests/test_fs_tools.py`:

```python
from test_agents.tools.fs.read_file import ReadFileTool


class TestReadFileTool:
    def test_reads_file_with_line_numbers(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("line1\nline2\nline3\n")
        out = ReadFileTool()._run(file_path=str(p))
        assert "1\tline1" in out
        assert "2\tline2" in out
        assert "3\tline3" in out

    def test_rejects_relative_path(self):
        out = ReadFileTool()._run(file_path="./relative.txt")
        assert "错误" in out
        assert "绝对路径" in out

    def test_rejects_nonexistent_path(self, tmp_path):
        out = ReadFileTool()._run(file_path=str(tmp_path / "nope.txt"))
        assert "错误" in out
        assert "文件不存在" in out

    def test_rejects_directory_path(self, tmp_path):
        out = ReadFileTool()._run(file_path=str(tmp_path))
        assert "错误" in out
        assert "list_dir" in out

    def test_rejects_binary_file(self, tmp_path):
        p = tmp_path / "bin.dat"
        p.write_bytes(b"hello\x00world")
        out = ReadFileTool()._run(file_path=str(p))
        assert "错误" in out
        assert "二进制" in out

    def test_offset_and_limit(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
        out = ReadFileTool()._run(file_path=str(p), offset=2, limit=3)
        assert "3\tline3" in out
        assert "4\tline4" in out
        assert "5\tline5" in out
        assert "line2" not in out
        assert "line6" not in out

    def test_large_file_force_truncates(self, tmp_path):
        p = tmp_path / "big.txt"
        # 5MB+1byte
        p.write_bytes(b"x" * (5 * 1024 * 1024 + 1) + b"\n")
        out = ReadFileTool()._run(file_path=str(p))
        assert "⚠️" in out
        assert "文件过大" in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestReadFileTool -v`
Expected: 7 FAILED（ImportError）

- [ ] **Step 3: 实现 `ReadFileTool`**

Create `test_agents/tools/fs/read_file.py`:

```python
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestReadFileTool -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add test_agents/tools/fs/read_file.py test_agents/tests/test_fs_tools.py
git commit -m "feat(tools): add ReadFileTool with line numbers and binary/size guards"
```

---

## Task 4: 实现 `ListDirTool`（TDD）

**Files:**
- Create: `test_agents/tools/fs/list_dir.py`
- Modify: `test_agents/tests/test_fs_tools.py`

- [ ] **Step 1: 写失败测试**

Append to `test_agents/tests/test_fs_tools.py`:

```python
from test_agents.tools.fs.list_dir import ListDirTool


class TestListDirTool:
    def test_lists_depth_1(self, tmp_path):
        (tmp_path / "a.txt").write_text("hi")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("inner")
        out = ListDirTool()._run(path=str(tmp_path), depth=1)
        assert "a.txt" in out
        assert "sub/" in out
        assert "b.txt" not in out

    def test_lists_depth_3(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("inner")
        out = ListDirTool()._run(path=str(tmp_path), depth=3)
        assert "sub/" in out
        assert "b.txt" in out

    def test_skips_noise_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / ".venv").mkdir()
        (tmp_path / "real.py").write_text("y")
        out = ListDirTool()._run(path=str(tmp_path), depth=3, show_hidden=True)
        assert "real.py" in out
        assert ".git/" not in out
        assert "__pycache__/" not in out
        assert "node_modules/" not in out
        assert ".venv/" not in out

    def test_hidden_files_default_hidden(self, tmp_path):
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / "visible.txt").write_text("y")
        out = ListDirTool()._run(path=str(tmp_path))
        assert "visible.txt" in out
        assert ".hidden" not in out

    def test_hidden_files_shown_when_requested(self, tmp_path):
        (tmp_path / ".hidden").write_text("x")
        out = ListDirTool()._run(path=str(tmp_path), show_hidden=True)
        assert ".hidden" in out

    def test_rejects_nonexistent(self, tmp_path):
        out = ListDirTool()._run(path=str(tmp_path / "nope"))
        assert "错误" in out

    def test_rejects_relative_path(self):
        out = ListDirTool()._run(path="./relative")
        assert "错误" in out
        assert "绝对路径" in out

    def test_truncates_at_500_entries(self, tmp_path):
        for i in range(600):
            (tmp_path / f"f{i:03}.txt").write_text("x")
        out = ListDirTool()._run(path=str(tmp_path), depth=1)
        assert out.count("\n") <= 510  # 500 + 截断提示
        assert "截断" in out or "⚠️" in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestListDirTool -v`
Expected: 8 FAILED（ImportError）

- [ ] **Step 3: 实现 `ListDirTool`**

Create `test_agents/tools/fs/list_dir.py`:

```python
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
                items = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError as e:
                entries.append(f"{prefix}(无法读取: {e!r})")
                return
            for item in items:
                if truncated:
                    return
                if item.name in _NOISE_DIRS:
                    continue
                if not show_hidden and item.name.startswith("."):
                    continue
                if len(entries) >= _MAX_ENTRIES:
                    truncated = True
                    return
                if item.is_dir():
                    entries.append(f"{prefix}{item.name}/")
                    walk(item, level + 1, prefix + "  ")
                else:
                    try:
                        size = item.stat().st_size
                        entries.append(f"{prefix}{item.name} ({size}B)")
                    except OSError:
                        entries.append(f"{prefix}{item.name}")

        walk(p, 1, "")
        body = "\n".join(entries)
        if truncated:
            body += f"\n⚠️ 条目超过 {_MAX_ENTRIES}，已截断"
        return body or "(空目录)"
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestListDirTool -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add test_agents/tools/fs/list_dir.py test_agents/tests/test_fs_tools.py
git commit -m "feat(tools): add ListDirTool with tree output and noise-dir skipping"
```

---

## Task 5: 实现 `GrepTool`（TDD）

**Files:**
- Create: `test_agents/tools/fs/grep.py`
- Modify: `test_agents/tests/test_fs_tools.py`

- [ ] **Step 1: 写失败测试**

Append to `test_agents/tests/test_fs_tools.py`:

```python
from test_agents.tools.fs.grep import GrepTool


class TestGrepTool:
    @pytestmark_requires_rg
    def test_grep_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass\ndef bar(): pass\n")
        out = GrepTool()._run(pattern="def foo", path=str(tmp_path))
        assert "a.py" in out
        assert "def foo" in out

    @pytestmark_requires_rg
    def test_grep_no_match(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass\n")
        out = GrepTool()._run(pattern="nonexistent_zzz", path=str(tmp_path))
        assert "未找到匹配" in out

    @pytestmark_requires_rg
    def test_grep_include_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("hello\n")
        (tmp_path / "b.md").write_text("hello\n")
        out = GrepTool()._run(pattern="hello", path=str(tmp_path), include="*.py")
        assert "a.py" in out
        assert "b.md" not in out

    @pytestmark_requires_rg
    def test_grep_case_insensitive(self, tmp_path):
        (tmp_path / "a.txt").write_text("Hello World\n")
        out = GrepTool()._run(pattern="hello", path=str(tmp_path), case_insensitive=True)
        assert "Hello" in out

    @pytestmark_requires_rg
    def test_grep_max_results_truncates(self, tmp_path):
        for i in range(150):
            (tmp_path / f"f{i:03}.txt").write_text("MATCH\n")
        out = GrepTool()._run(pattern="MATCH", path=str(tmp_path), max_results=10)
        assert out.count("MATCH") <= 12  # 10 matches + 2 in trailing notice
        assert "⚠️" in out

    def test_grep_rejects_relative_path(self):
        out = GrepTool()._run(pattern="x", path="./relative")
        assert "错误" in out
        assert "绝对路径" in out

    def test_grep_rg_missing_returns_friendly_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        out = GrepTool()._run(pattern="x", path=str(tmp_path))
        assert "错误" in out
        assert "ripgrep" in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestGrepTool -v`
Expected: 7 FAILED（ImportError）

- [ ] **Step 3: 实现 `GrepTool`**

Create `test_agents/tools/fs/grep.py`:

```python
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestGrepTool -v`
Expected: 7 passed（若 rg 未装：5 skipped + 2 passed）

- [ ] **Step 5: 提交**

```bash
git add test_agents/tools/fs/grep.py test_agents/tests/test_fs_tools.py
git commit -m "feat(tools): add GrepTool wrapping ripgrep with include/case filters"
```

---

## Task 6: 实现 `GlobTool`（TDD）

**Files:**
- Create: `test_agents/tools/fs/glob.py`
- Modify: `test_agents/tests/test_fs_tools.py`

- [ ] **Step 1: 写失败测试**

Append to `test_agents/tests/test_fs_tools.py`:

```python
import time

from test_agents.tools.fs.glob import GlobTool


class TestGlobTool:
    @pytestmark_requires_rg
    def test_glob_matches_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.md").write_text("x")
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path))
        assert "a.py" in out
        assert "b.md" not in out

    @pytestmark_requires_rg
    def test_glob_recursive_pattern(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.py").write_text("x")
        out = GlobTool()._run(pattern="**/*.py", path=str(tmp_path))
        assert "inner.py" in out

    @pytestmark_requires_rg
    def test_glob_sorts_by_mtime_desc(self, tmp_path):
        old = tmp_path / "old.py"
        old.write_text("x")
        time.sleep(0.05)
        new = tmp_path / "new.py"
        new.write_text("x")
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path))
        lines = [l for l in out.splitlines() if l.strip()]
        assert lines[0].endswith("new.py")
        assert lines[1].endswith("old.py")

    @pytestmark_requires_rg
    def test_glob_max_results_truncates(self, tmp_path):
        for i in range(250):
            (tmp_path / f"f{i:03}.py").write_text("x")
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path), max_results=10)
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("⚠️")]
        assert len(lines) == 10
        assert "⚠️" in out

    def test_glob_rejects_relative_path(self):
        out = GlobTool()._run(pattern="*.py", path="./relative")
        assert "错误" in out
        assert "绝对路径" in out
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestGlobTool -v`
Expected: 5 FAILED（ImportError）

- [ ] **Step 3: 实现 `GlobTool`**

Create `test_agents/tools/fs/glob.py`:

```python
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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -m pytest test_agents/tests/test_fs_tools.py::TestGlobTool -v`
Expected: 5 passed（若 rg 未装：4 skipped + 1 passed）

- [ ] **Step 5: 提交**

```bash
git add test_agents/tools/fs/glob.py test_agents/tests/test_fs_tools.py
git commit -m "feat(tools): add GlobTool for file-name matching via rg --files"
```

---

## Task 7: 注册工具并绑定到 code_analyzer

**Files:**
- Modify: `test_agents/tools/__init__.py`
- Modify: `test_agents/agents/code_analyzer.py`
- Modify: `test_agents/tests/test_workers.py`

- [ ] **Step 1: 写失败测试 —— code_analyzer 绑定 5 个工具**

Append to `test_agents/tests/test_workers.py`:

```python
from test_agents.tools.base import ToolRegistry


class TestCodeAnalyzerToolBinding:
    def test_code_analyzer_tools_include_fs_tools(self):
        """After registration, code_analyzer binds claude_cli + 4 fs tools."""
        # Importing the module triggers __init_subclass__ registration
        from test_agents.tools.fs.read_file import ReadFileTool
        from test_agents.tools.fs.list_dir import ListDirTool
        from test_agents.tools.fs.grep import GrepTool
        from test_agents.tools.fs.glob import GlobTool

        names = ["claude_cli", "read_file", "list_dir", "grep", "glob"]
        tools = ToolRegistry.get_tools_by_names(names)
        assert len(tools) == 5
        assert [t.name for t in tools] == names
```

- [ ] **Step 2: 运行测试，确认通过**

Run: `python -m pytest test_agents/tests/test_workers.py::TestCodeAnalyzerToolBinding -v`
Expected: 1 passed（因为 import 已触发注册）

- [ ] **Step 3: 修改 `test_agents/tools/__init__.py`，追加 4 个 import**

当前文件内容：
```python
from test_agents.tools.base import ToolRegistry, TestAgentTool
from test_agents.tools.claude_cli import ClaudeCliTool
from test_agents.tools.test_case_parser import TestCaseParserTool
from test_agents.tools.business_knowledge import BusinessKnowledgeTool
```

追加 4 行：
```python
from test_agents.tools.fs.read_file import ReadFileTool
from test_agents.tools.fs.list_dir import ListDirTool
from test_agents.tools.fs.grep import GrepTool
from test_agents.tools.fs.glob import GlobTool
```

- [ ] **Step 4: 修改 `test_agents/agents/code_analyzer.py`，更新工具绑定**

将第 8 行：
```python
_code_analyzer_tools = ToolRegistry.get_tools_by_names(["claude_cli"])
```
改为：
```python
_code_analyzer_tools = ToolRegistry.get_tools_by_names(
    ["claude_cli", "read_file", "list_dir", "grep", "glob"]
)
```

- [ ] **Step 5: 运行全部测试，确认无回归**

Run: `python -m pytest test_agents/tests/ -v`
Expected: 全部 passed（test_workers.py 和 test_fs_tools.py 合计约 28+ 条）

- [ ] **Step 6: 提交**

```bash
git add test_agents/tools/__init__.py test_agents/agents/code_analyzer.py test_agents/tests/test_workers.py
git commit -m "feat(code_analyzer): bind read_file/list_dir/grep/glob tools"
```

---


## Task 8: 更新 code_analyzer prompt

**Files:**
- Modify: `test_agents/prompts/code_analyzer.md`

- [ ] **Step 1: 查看当前 prompt**

Run: `cat test_agents/prompts/code_analyzer.md`
Expected: 看到 git diff 单一工具用法的旧版 prompt

- [ ] **Step 2: 重写 prompt 为新版本**

将 `test_agents/prompts/code_analyzer.md` 内容整体替换为：

```markdown
请分析模块 {module_name} 在 commit {source_commit}..{target_commit} 之间的代码变更。

Commit 消息：{commit_msg}

## 可用工具

- `claude_cli` —— 调用 Claude CLI 执行复杂分析任务（适合需要语义理解的场景）
- `list_dir` —— 列出目录结构，必须传绝对路径
- `read_file` —— 读取单个文件（带行号），必须传绝对路径
- `grep` —— 在指定路径下按正则搜索（基于 ripgrep），必须传绝对路径
- `glob` —— 按文件名 glob 模式查找文件，必须传绝对路径

## 工作流程

1. **定位仓库**：若用户给出绝对路径（如 `/mnt/d/obs_node/`），直接在该路径下操作；否则默认在当前项目根 `/mnt/d/testagents`。
2. **了解结构**：用 `list_dir` 查看模块根目录，必要时 `depth=3`
3. **找变更范围**：用 `claude_cli` 调用 `git -C <repo_path> log --oneline -- <module>/` 等命令收集 commit
4. **看变更内容**：用 `claude_cli` 调用 `git -C <repo_path> diff <range> -- <module>/` 收集 diff
5. **查上下文**：用 `read_file` / `grep` / `glob` 在源码中查证函数定义、调用方、相关测试
6. **输出结构化报告**

## 报告格式

## 变更概述
...
## 新增/修改/删除的文件
...
## 关键逻辑变更
...
## 影响范围评估
...
## 测试建议
...
```

- [ ] **Step 3: 运行全部测试，确保 prompt 改动不破坏现有测试**

Run: `python -m pytest test_agents/tests/ -v`
Expected: 全部 passed

- [ ] **Step 4: 提交**

```bash
git add test_agents/prompts/code_analyzer.md
git commit -m "docs(prompt): teach code_analyzer to use fs tools across repos"
```

---

## Task 9: 更新 README 与 CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: 在 README.md 的 "安装依赖" 段落后追加 "系统依赖" 小节**

在 README 的 `pip install -r requirements.txt` 段落后追加：

```markdown
### 系统依赖：ripgrep

`grep` / `glob` 工具基于 ripgrep。请按平台安装：

- WSL/Ubuntu/Debian：`sudo apt install ripgrep`
- macOS：`brew install ripgrep`
- Windows (scoop)：`scoop install ripgrep`
- Windows (winget)：`winget install BurntSushi.ripgrep.MSVC`

验证：`rg --version`
```

- [ ] **Step 2: 在 CLAUDE.md 的 "工具层" 段落补充 4 个新工具**

在 CLAUDE.md "工具层" 段落（`### 工具层` 或对应位置）下方追加：

```markdown
- **ReadFileTool / ListDirTool / GrepTool / GlobTool** (`test_agents/tools/fs/`): 4 个只读文件系统工具。`read_file` / `list_dir` 走原生 fs，`grep` / `glob` 通过 `subprocess` 调用 ripgrep（共享 `_rg.py`）。全部仅接受绝对路径。绑定到 `code_analyzer`，用于跨仓库源码探索。
```

并在工具绑定说明处更新 `code_analyzer` 的工具列表：从 `[claude_cli]` 改为 `[claude_cli, read_file, list_dir, grep, glob]`。

- [ ] **Step 3: 提交**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document ripgrep dependency and new fs tools binding"
```

---

## Task 10: 手工 e2e 验证

**Files:** （无代码改动）

- [ ] **Step 1: 准备一个真实的代码仓库路径**

确认 `/mnt/d/obs_node/` 实际是否为代码仓库；若不是，让用户提供真实路径。备用：用当前项目自身：`/mnt/d/testagents`

- [ ] **Step 2: 启动交互模式**

Run: `python -m test_agents`
Expected: 进入交互提示

- [ ] **Step 3: 输入跨仓库分析请求**

输入提示（替换 PATH 为真实路径）：
```
分析 /mnt/d/testagents/test_agents 模块结构，列出主要 Python 文件并简述每个文件的职责
```
确认计划：`y`

- [ ] **Step 4: 观察 worker 是否调用了 list_dir / read_file / glob**

Expected: stdout 中可见工具调用日志，包含 `list_dir`、`read_file` 或 `glob`；最终产出包含具体文件名（非空泛回答）

- [ ] **Step 5: 若失败，定位问题**

- 若 LLM 不调用新工具 → 检查 prompt 是否生效（Task 8）
- 若工具报 "ripgrep 未安装" → 重做 Task 1
- 若工具被 ToolRegistry 找不到 → 检查 `tools/__init__.py` 中的 4 行 import（Task 7 Step 3）

---

## 验收标准

- [ ] `python -m pytest test_agents/tests/ -v` 全绿
- [ ] `python -m test_agents "分析 <绝对路径> 的代码结构"` 实际调用到 `list_dir` / `read_file` 中的至少一个
- [ ] README 和 CLAUDE.md 反映了新工具与 ripgrep 系统依赖
- [ ] 所有提交均为单一焦点，可独立 revert
