"""Tests for test_agents.tools.fs"""
import os
import shutil
import pytest

from test_agents.tools.fs._rg import run_rg, RgNotInstalled
from test_agents.tools.fs.glob import GlobTool
from test_agents.tools.fs.grep import GrepTool
from test_agents.tools.fs.list_dir import ListDirTool
from test_agents.tools.fs.read_file import ReadFileTool


requires_rg = pytest.mark.skipif(
    shutil.which("rg") is None,
    reason="ripgrep 未安装，跳过依赖 rg 的测试",
)


class TestRunRg:
    @requires_rg
    def test_run_rg_returns_tuple(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello world\n")
        rc, out, err = run_rg(["hello", str(tmp_path)])
        assert rc == 0
        assert "hello" in out
        assert err == ""

    @requires_rg
    def test_run_rg_no_match_returns_rc_1(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello\n")
        rc, out, err = run_rg(["nonexistent_pattern_xyz", str(tmp_path)])
        assert rc == 1
        assert out == ""

    def test_run_rg_raises_when_not_installed(self, monkeypatch):
        monkeypatch.setattr("test_agents.tools.fs._rg.shutil.which", lambda name: None)
        with pytest.raises(RgNotInstalled) as exc_info:
            run_rg(["foo", "."])
        assert "apt install ripgrep" in str(exc_info.value)


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


class TestGrepTool:
    @requires_rg
    def test_grep_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass\ndef bar(): pass\n")
        out = GrepTool()._run(pattern="def foo", path=str(tmp_path))
        assert "a.py" in out
        assert "def foo" in out

    @requires_rg
    def test_grep_no_match(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass\n")
        out = GrepTool()._run(pattern="nonexistent_zzz", path=str(tmp_path))
        assert "未找到匹配" in out

    @requires_rg
    def test_grep_include_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("hello\n")
        (tmp_path / "b.md").write_text("hello\n")
        out = GrepTool()._run(pattern="hello", path=str(tmp_path), include="*.py")
        assert "a.py" in out
        assert "b.md" not in out

    @requires_rg
    def test_grep_case_insensitive(self, tmp_path):
        (tmp_path / "a.txt").write_text("Hello World\n")
        out = GrepTool()._run(pattern="hello", path=str(tmp_path), case_insensitive=True)
        assert "Hello" in out

    @requires_rg
    def test_grep_max_results_truncates(self, tmp_path):
        for i in range(150):
            (tmp_path / f"f{i:03}.txt").write_text("MATCH\n")
        out = GrepTool()._run(pattern="MATCH", path=str(tmp_path), max_results=10)
        # exactly 10 match lines, no more
        match_lines = [l for l in out.splitlines() if "MATCH" in l]
        assert len(match_lines) == 10
        assert "⚠️" in out
        assert "结果超过 10" in out

    def test_grep_rejects_relative_path(self):
        out = GrepTool()._run(pattern="x", path="./relative")
        assert "错误" in out
        assert "绝对路径" in out

    def test_grep_rg_missing_returns_friendly_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("test_agents.tools.fs._rg.shutil.which", lambda name: None)
        out = GrepTool()._run(pattern="x", path=str(tmp_path))
        assert out.startswith("错误: ")
        assert "ripgrep" in out
        assert "apt install ripgrep" in out

    @requires_rg
    def test_grep_pattern_starting_with_dash(self, tmp_path):
        """The `--` separator in run_rg args must protect against patterns starting with '-'."""
        (tmp_path / "a.txt").write_text("-foo bar\n--bar baz\n")
        out = GrepTool()._run(pattern="-foo", path=str(tmp_path))
        assert "a.txt" in out
        assert "-foo" in out

    def test_grep_rejects_nonexistent_path(self, tmp_path):
        out = GrepTool()._run(pattern="x", path=str(tmp_path / "nope"))
        assert "错误" in out
        assert "不存在" in out


class TestGlobTool:
    @requires_rg
    def test_glob_matches_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.md").write_text("x")
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path))
        assert "a.py" in out
        assert "b.md" not in out

    @requires_rg
    def test_glob_recursive_pattern(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.py").write_text("x")
        out = GlobTool()._run(pattern="**/*.py", path=str(tmp_path))
        assert "inner.py" in out

    @requires_rg
    def test_glob_sorts_by_mtime_desc(self, tmp_path):
        old = tmp_path / "old.py"
        old.write_text("x")
        new = tmp_path / "new.py"
        new.write_text("x")
        # Explicit mtimes — independent of filesystem granularity
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path))
        lines = [l for l in out.splitlines() if l.strip()]
        assert lines[0].endswith("new.py")
        assert lines[1].endswith("old.py")

    @requires_rg
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

    def test_glob_rejects_nonexistent_path(self, tmp_path):
        out = GlobTool()._run(pattern="*.py", path=str(tmp_path / "nope"))
        assert "错误" in out
        assert "不存在" in out
