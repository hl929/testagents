"""Tests for test_agents.tools.fs"""
import shutil
import pytest

from test_agents.tools.fs._rg import run_rg, RgNotInstalled
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
        assert out.count("MATCH") <= 12  # 10 matches + 2 in trailing notice
        assert "⚠️" in out

    def test_grep_rejects_relative_path(self):
        out = GrepTool()._run(pattern="x", path="./relative")
        assert "错误" in out
        assert "绝对路径" in out

    def test_grep_rg_missing_returns_friendly_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("test_agents.tools.fs._rg.shutil.which", lambda name: None)
        out = GrepTool()._run(pattern="x", path=str(tmp_path))
        assert "错误" in out
        assert "ripgrep" in out
