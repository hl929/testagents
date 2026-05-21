"""
E2E 测试：通过 subprocess 调用真实 python -m test_agents

验证完整的 CLI 执行路径：模块加载 → LLM 调用 → JSON 输出
不 mock LLM，不 mock 工具，跑真实端到端流程。

运行：python -m pytest test_agents/tests/e2e/ -v -s -m e2e
"""

import json
import subprocess

import pytest

from .conftest import run_cli, skip_if_no_api_key

pytestmark = pytest.mark.e2e


class TestModuleLoad:
    """验证 python -m test_agents 模块加载无误"""

    def test_help_exits_cleanly(self):
        result = run_cli(["-m", "test_agents", "--help"])
        assert result.returncode == 0
        assert "request" in result.stdout.lower()

    def test_import_chain(self):
        result = run_cli(
            ["-c", "from test_agents.main import main; print('OK')"]
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_load_prompt_no_crash(self):
        script = (
            "from test_agents.prompts.loader import load_prompt; "
            "p = load_prompt('planner', user_request='hello', tools_info='test'); "
            "assert 'hello' in p; "
            "print('OK')"
        )
        result = run_cli(["-c", script])
        assert result.returncode == 0
        assert "OK" in result.stdout


class TestDirectScriptRun:
    """python test_agents/main.py 应因绝对导入失败"""

    def test_import_error(self):
        result = run_cli(["test_agents/main.py"])
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr


class TestRealPipeline:
    """调用真实 LLM 的端到端测试

    用 stdin="y\\n" 自动确认计划，--output json 输出结构化结果。
    _display_plan 输出到 stderr，stdout 只有 JSON。
    """

    def _parse_json_stdout(self, result: subprocess.CompletedProcess) -> dict:
        """从 stdout 提取 JSON 对象（跳过可能的前导空行）"""
        text = result.stdout.strip()
        # 找到第一个 { 开始的位置
        start = text.find("{")
        if start == -1:
            raise AssertionError(f"No JSON found in stdout:\n{text[:500]}")
        return json.loads(text[start:])

    def test_ambiguous_request_empty_steps(self):
        """模糊请求（如 'hello'）应生成空步骤计划并正常完成

        覆盖：planner_node → load_prompt → LLM → reflect → synthesize 全链路
        """
        skip_if_no_api_key()
        result = run_cli(
            ["-m", "test_agents", "hello", "--output", "json"],
            stdin="y\n",
            timeout=180,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[-500:]}"
        data = self._parse_json_stdout(result)
        assert "plan" in data
        assert "intent" in data["plan"]
        assert data["plan"]["steps"] == []
        assert "final_answer" in data

    def test_code_analysis_request(self):
        """代码分析请求应调用 code_analyzer 并返回结果

        "分析代码变更" 匹配 is_simple_request，走 _run_direct_worker，
        返回结果中有 code_change_report 而非 plan。
        """
        skip_if_no_api_key()
        result = run_cli(
            ["-m", "test_agents", "分析代码变更", "--output", "json"],
            stdin="y\n",
            timeout=180,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[-500:]}"
        data = self._parse_json_stdout(result)
        # 直接 worker 模式：有 code_change_report 或 final_answer
        assert "code_change_report" in data.get("outputs", {}) or "final_answer" in data

    def test_plan_rejection_exits(self):
        """拒绝计划后系统应达到重试上限退出，返回非空结果"""
        skip_if_no_api_key()
        result = run_cli(
            ["-m", "test_agents", "hello", "--output", "json"],
            stdin="n\n随便\n",  # 拒绝 + 输入反馈
            timeout=180,
        )
        # 拒绝后可能重新规划或到达重试上限
        # 不管哪种路径，最终应能产生输出
        assert result.returncode == 0, f"stderr: {result.stderr[-500:]}"
        data = self._parse_json_stdout(result)
        assert "plan" in data or "final_answer" in data
