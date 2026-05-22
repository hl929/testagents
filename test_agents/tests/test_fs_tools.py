"""Tests for test_agents.tools.fs"""
import shutil
import pytest

from test_agents.tools.fs._rg import run_rg, RgNotInstalled


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
