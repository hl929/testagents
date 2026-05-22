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
