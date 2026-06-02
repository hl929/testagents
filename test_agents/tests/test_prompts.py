from test_agents.prompts.loader import load_prompt


def test_planner_prompt_loads():
    prompt = load_prompt("planner", user_request="分析 payment 模块代码变更")
    assert "payment" in prompt
    assert "code_analyzer" in prompt


def test_supervisor_reflect_prompt_loads():
    prompt = load_prompt("supervisor_reflect", user_request="test", plan_summary="plan", step_results_summary="results")
    assert "COMPLETE" in prompt or "REPLAN" in prompt


def test_synthesize_prompt_loads():
    prompt = load_prompt("synthesize", user_request="test", plan_summary="plan", step_results_summary="results")
    assert "test" in prompt


def test_worker_reflect_prompt_loads():
    prompt = load_prompt("worker_reflect", task="分析代码", result="报告内容")
    assert "pass" in prompt or "retry" in prompt


def test_data_analyst_prompt_loads():
    prompt = load_prompt("data_analyst")
    assert "测试数据分析师" in prompt
    assert "query_database" in prompt
    assert "describe_schema" in prompt
