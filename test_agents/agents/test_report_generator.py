"""Test report generator worker - ReAct subgraph with ClaudeCliTool + SaveReportTool"""

import os
from typing import Optional

from langchain_core.messages import HumanMessage

from test_agents.agents.worker_base import build_worker_graph, aggregate_worker_result
from test_agents.graph.state import SupervisorState
from test_agents.prompts.loader import load_prompt
from test_agents.tools.base import ToolRegistry


_test_report_generator_tools = ToolRegistry.get_tools_by_names(["claude_cli", "save_report"])
test_report_generator_graph = None

_MAX_PREPROCESS_ROWS = 5000
_MAX_PREPROCESS_CELLS = 100_000
_MAX_TEXT_INLINE_BYTES = 100 * 1024  # 100KB


def build_test_report_generator_graph(llm, llm_with_tools):
    """Build and cache the test_report_generator subgraph"""
    global test_report_generator_graph
    test_report_generator_graph = build_worker_graph(
        _test_report_generator_tools,
        llm,
        llm_with_tools,
        system_prompt=load_prompt("test_report_generator_system"),
    )
    return test_report_generator_graph


def _preprocess_xlsx(file_path: str) -> Optional[str]:
    """Read xlsx and return text representation. None if too large or fails."""
    try:
        import pandas as pd
    except ImportError:
        return None

    try:
        df = pd.read_excel(file_path, nrows=_MAX_PREPROCESS_ROWS)
    except Exception:
        return None

    rows, cols = df.shape
    if rows * cols > _MAX_PREPROCESS_CELLS:
        return None
    return df.to_markdown(index=False)


def _resolve_template_path(business_line: str, template_name: str) -> str:
    """Build the template file path."""
    return os.path.join("templates", business_line, f"{template_name}.md")


def _build_data_context(file_path: str) -> str:
    """Build the test data context block — inline content if small/parseable, else path."""
    if not file_path:
        return "(未提供)"
    if not os.path.isfile(file_path):
        return f"路径: {file_path}\n（文件不存在，请由 claude_cli 自行处理或返回错误）"

    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xls"):
        text = _preprocess_xlsx(file_path)
        if text:
            return f"文件: {file_path}\n内容（已预处理为表格）:\n{text}"
        return f"路径: {file_path}（xlsx 未预处理，请由 claude_cli 直接读取）"

    try:
        size = os.path.getsize(file_path)
        if size <= _MAX_TEXT_INLINE_BYTES:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f"文件: {file_path}\n内容:\n{f.read()}"
    except OSError:
        pass

    return f"路径: {file_path}（文件较大，请由 claude_cli 直接读取）"


def _build_template_context(business_line: str, template_name: str) -> tuple[str, Optional[str]]:
    """Return (template_block, error_msg). If error_msg is set, generation should not proceed."""
    if not business_line or not template_name:
        return "(模板信息不完整)", "缺少业务线或模板名"

    template_path = _resolve_template_path(business_line, template_name)
    if not os.path.isfile(template_path):
        return f"路径: {template_path}", f"模板不存在: {template_path}"

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f"模板: {template_path}\n内容:\n{f.read()}", None
    except OSError as e:
        return f"路径: {template_path}", f"读取模板失败: {e}"


def report_generator_wrapper(state: SupervisorState) -> dict:
    """Test report generator node — thin adapter around worker subgraph."""
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    if test_report_generator_graph is None:
        raise RuntimeError(
            "test_report_generator_graph not initialized. Call build_test_report_generator_graph first."
        )

    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)
    step = steps[current_index] if current_index < len(steps) else {}
    input_mapping = step.get("input_mapping", {})

    file_path = input_mapping.get("file_path", "")
    business_line = input_mapping.get("business_line", "")
    template_name = input_mapping.get("template_name", "")

    template_block, template_error = _build_template_context(business_line, template_name)

    if template_error:
        error_message = (
            f"## 测试报告生成失败\n\n"
            f"**原因:** {template_error}\n\n"
            f"请确认以下信息正确：\n"
            f"- 业务线: `{business_line}`\n"
            f"- 模板名: `{template_name}`\n"
            f"- 模板路径应为: `{_resolve_template_path(business_line, template_name)}`"
        )
        outputs = state.get("outputs", {}).copy()
        outputs[worker_input["output_key"]] = error_message
        return {
            "outputs": outputs,
            "current_step_index": current_index + 1,
            "step_results": [{
                "step_id": step.get("step_id", 0),
                "agent": "test_report_generator",
                "status": "failed",
                "output_key": worker_input["output_key"],
                "error": template_error,
            }],
        }

    data_block = _build_data_context(file_path)
    user_prompt = load_prompt(
        "test_report_generator",
        test_data_content_or_path=data_block,
        template_content_or_path=template_block,
    )

    enriched_input = dict(worker_input)
    enriched_input["messages"] = [
        HumanMessage(
            content=(
                f"{worker_input.get('task', '')}\n\n"
                f"业务线: {business_line}\n"
                f"模板名: {template_name}\n\n"
                f"请按以下指令生成报告，生成后调用 save_report 工具落盘：\n\n{user_prompt}\n\n"
                f"save_report 调用参数：\n"
                f"- business_line: {business_line}\n"
                f"- template_name: {template_name}\n"
                f"- content: 上述生成的 Markdown 报告"
            )
        )
    ]

    result = test_report_generator_graph.invoke(enriched_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "test_report_generator"
    )
