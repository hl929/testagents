"""
集成测试：验证 CLI 的两种执行方式

1. python test_agents/main.py  → 应失败（绝对导入找不到 test_agents 包）
2. python -m test_agents       → 应成功（模块方式正确加载 + 实际执行路径可达）
"""

import subprocess
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

PYTHON = "/mnt/c/Users/root/python-sdk/python3.13.2/python.exe"


def _to_win_path(wsl_path: str) -> str:
    """将 WSL 路径 (/mnt/x/...) 转为 Windows 路径 (X:/...)"""
    m = re.match(r"^/mnt/([a-z])/(.*)$", wsl_path)
    if m:
        drive = m.group(1).upper()
        rest = m.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"
    return wsl_path


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(PROJECT_ROOT),
        timeout=30,
        **kwargs,
    )


class TestDirectScriptExecution:
    """直接运行 test_agents/main.py 应因绝对导入失败"""

    def test_import_error_on_direct_run(self):
        result = _run([PYTHON, "test_agents/main.py"])
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr
        assert "test_agents" in result.stderr


class TestModuleExecution:
    """python -m test_agents 执行路径验证"""

    def test_help_flag_exits_cleanly(self):
        """--help 能正常加载模块并打印帮助"""
        result = _run([PYTHON, "-m", "test_agents", "--help"])
        assert result.returncode == 0
        assert "request" in result.stdout.lower()

    def test_import_chain_works(self):
        """from test_agents.main import main 整条导入链无报错"""
        result = _run(
            [PYTHON, "-c", "from test_agents.main import main; print('OK')"]
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_load_prompt_no_crash(self):
        """load_prompt('planner', ...) 不再因 ${outputs.xxx} 崩溃"""
        script = (
            "from test_agents.prompts.loader import load_prompt; "
            "p = load_prompt('planner', user_request='hello', tools_info='test'); "
            "assert 'hello' in p; "
            "print('OK')"
        )
        result = _run([PYTHON, "-c", script])
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_run_test_agents_reaches_planner(self):
        """run_test_agents('hello') 能走到 planner_node 而非在 load_prompt 崩溃

        用 mock 隔离 LLM 调用，只验证执行路径通畅。
        脚本放在项目目录下，路径转为 Windows 格式确保 .exe 可访问。
        """
        script_file = PROJECT_ROOT / "_test_run_tmp.py"
        win_path = _to_win_path(str(script_file))
        try:
            script_file.write_text(
                "import json\n"
                "from unittest.mock import patch, MagicMock\n"
                "from test_agents.main import run_test_agents\n"
                "\n"
                "mock_llm = MagicMock()\n"
                "# planner + reflect + synthesize all use llm.invoke()\n"
                "plan_resp = MagicMock()\n"
                "plan_resp.content = json.dumps({'intent': 'test', 'steps': [], 'confirmed': False})\n"
                "reflect_resp = MagicMock()\n"
                "reflect_resp.content = '{\"assessment\": \"COMPLETE\", \"feedback\": \"ok\"}'\n"
                "synthesize_resp = MagicMock()\n"
                "synthesize_resp.content = 'no action needed'\n"
                "mock_llm.invoke.side_effect = [plan_resp, reflect_resp, synthesize_resp]\n"
                "\n"
                "with (\n"
                "    patch('test_agents.agents.supervisor.get_llm', return_value=mock_llm),\n"
                "    patch('test_agents.graph.builder.get_llm', return_value=mock_llm),\n"
                "    patch('test_agents.agents.supervisor.interrupt', return_value={'confirmed': True}),\n"
                "):\n"
                "    result = run_test_agents('hello')\n"
                "\n"
                "ok = 'final_answer' in result or 'outputs' in result\n"
                "print('OK' if ok else 'FAIL')\n",
                encoding="utf-8",
            )
            result = _run([PYTHON, win_path])
            assert result.returncode == 0, result.stderr
            assert "OK" in result.stdout
        finally:
            script_file.unlink(missing_ok=True)
