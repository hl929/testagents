# dispatch 与 worker wrapper 重构设计文档

## 1. 背景与动机

当前 `dispatch_node`（`agents/supervisor.py:137`）直接 `return {}`，未承担设计文档（§3.3、§4.3）中约定的双向映射职责。

实际的双向映射逻辑散落在 `code_analyzer_wrapper` 和 `case_reviewer_wrapper` 中，导致：
- 架构职责不清晰（dispatch 名存实亡，wrapper 承担双重职责）
- 两个 wrapper 之间存在大量重复代码（构建 WorkerState、拼接 outputs、生成 step_results）

本方案将 dispatch 重构为真正的调度中枢，wrapper 退化为 thin adapter。

## 2. 目标架构

```
dispatch_node          wrapper (thin adapter)
    │                       │
    ├─ 读取 plan step       ├─ 读取 worker_input
    ├─ 构建 WorkerState  ──→├─ 调用子图
    ├─ 写入 state           ├─ 调用公共聚合函数
    │                       │   (输出 → outputs / step_results / index)
    └─ 边路由到 wrapper ───→┘
```

## 3. 状态变更

`SupervisorState` 新增字段：

```python
worker_input: Optional[dict]   # dispatch 准备好的 WorkerState（dict 形式）
```

## 4. 节点重构

### 4.1 dispatch_node

职责：
1. 读取 `plan.steps[current_step_index]`
2. 构建完整 `WorkerState`
3. 写入 `state["worker_input"]`
4. 条件边路由到对应 wrapper

```python
def dispatch_node(state: SupervisorState) -> dict:
    plan = state.get("plan") or {}
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    current_index = state.get("current_step_index", 0)

    if current_index >= len(steps):
        return {}  # 路由到 reflect

    step = steps[current_index]
    task_desc, messages = build_worker_task(step, state)
    output_key = step.get("output_key", "") or _default_output_key(step.get("agent", ""))

    worker_input = {
        "task": task_desc,
        "messages": messages,
        "error": "no",
        "reflection_count": 0,
        "max_reflections": 0,
        "output_key": output_key,
        "result": "",
    }
    return {"worker_input": worker_input}
```

### 4.2 worker_base.py 新增公共聚合函数

```python
def aggregate_worker_result(
    state: SupervisorState,
    worker_result: dict,
    output_key: str,
    agent_name: str,
    post_processor: Callable | None = None,
) -> dict:
    """通用 Worker 结果聚合：提取 result → 可选后处理 → 更新 outputs → 生成 step_result"""
    output_value = extract_worker_output(worker_result, output_key).get(output_key, "")

    if post_processor:
        output_value = post_processor(output_value)

    outputs = state.get("outputs", {}).copy()
    existing = outputs.get(output_key, "")

    # 同 output_key 拼接逻辑（保留模块分隔）
    step = state["plan"]["steps"][state["current_step_index"]]
    module_name = step.get("input_mapping", {}).get("module_name", "")
    if existing and module_name:
        output_value = existing + f"\n\n## 模块: {module_name}\n" + str(output_value)

    outputs[output_key] = output_value

    return {
        "outputs": outputs,
        "current_step_index": state["current_step_index"] + 1,
        "step_results": [{
            "step_id": step.get("step_id", 0),
            "agent": agent_name,
            "status": "success" if output_value else "failed",
            "output_key": output_key,
            "error": "" if output_value else "Empty result",
        }],
    }
```

### 4.3 wrapper 瘦身

**code_analyzer_wrapper：**

```python
def code_analyzer_wrapper(state: SupervisorState) -> dict:
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    result = code_analyzer_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "code_analyzer"
    )
```

**case_reviewer_wrapper：**（保留结构化解析）

```python
def case_reviewer_wrapper(state: SupervisorState) -> dict:
    worker_input = state.get("worker_input")
    if not worker_input:
        return {}
    result = case_reviewer_graph.invoke(worker_input)
    return aggregate_worker_result(
        state, result, worker_input["output_key"], "case_reviewer",
        post_processor=_parse_review_results
    )
```

## 5. 变更文件清单

| 文件 | 变更内容 |
|---|---|
| `test_agents/graph/state.py` | `SupervisorState` 新增 `worker_input` |
| `test_agents/agents/supervisor.py` | `dispatch_node` 重构，`_default_output_key` 辅助函数 |
| `test_agents/agents/worker_base.py` | 新增 `aggregate_worker_result`，`extract_worker_output` 保持 |
| `test_agents/agents/code_analyzer.py` | wrapper 瘦身，移除重复逻辑 |
| `test_agents/agents/case_reviewer.py` | wrapper 瘦身，保留 `_parse_review_results` |
| `test_agents/tests/test_integration.py` | mock wrapper 方式适配 |
| `test_agents/tests/test_workers.py` | wrapper 行为验证更新 |

## 6. 明确不做

| 项目 | 原因 |
|---|---|
| planner 提取 targets/test_cases/business_knowledge | 用户明确不需要 |
| intent classifier 升级 | 拆分为独立任务 |
| 增加新功能 | 纯重构，外部行为不变 |
