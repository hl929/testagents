# LangGraph 执行追踪与可观测性设计

**日期**: 2026-05-20
**方案**: LangSmith + PostgresSaver

## 目标

为 Test Agents v3 建立完整的可观测性体系，覆盖调试排障、生产监控、回放审计三个维度。

## 整体架构

两层独立系统各司其职：

- **Checkpointing 层**：`PostgresSaver` 替换 `InMemorySaver`，负责状态持久化。支撑 `confirm_plan` 的 interrupt/resume、故障恢复、time-travel 回放。
- **Tracing 层**：LangSmith 通过 `LANGSMITH_TRACING=true` 环境变量自动激活，捕获每次 `graph.invoke()` / `graph.stream()` 的完整执行链路。

两者唯一的代码交汇点在 `builder.py` 的 `compile(checkpointer=...)` 参数，其余全靠环境变量和配置。

```
┌─────────────────────────────────────────────────────┐
│                  LangGraph Supervisor Graph          │
│                                                      │
│  planner → confirm → dispatch → worker → reflect     │
│                                    ↑          ↓      │
│                              code_analyzer  synthesize│
│                              case_reviewer           │
├──────────────────┬──────────────────────────────────-─┤
│   Checkpointing  │          Tracing (LangSmith)       │
│   PostgresSaver  │   自动捕获: 节点/LLM/工具/路由     │
│   状态持久化      │   环境变量驱动, 零代码改动          │
│   interrupt恢复   │   Studio 可视化调试                │
└──────────────────┴────────────────────────────────────┘
```

## Checkpointing 层升级

### 代码改动

`builder.py` 中将 `InMemorySaver` 替换为可配置的 checkpointer 工厂：

```python
import os
import logging
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger(__name__)

def _get_checkpointer():
    mode = os.getenv("LANGGRAPH_CHECKPOINTER", "postgres")
    if mode == "memory":
        return InMemorySaver()
    try:
        cp = PostgresSaver.from_conn_string(
            os.getenv("LANGGRAPH_DB_URI", "postgresql://localhost:5432/langgraph")
        )
        cp.setup()
        return cp
    except Exception:
        logger.warning("PostgresSaver 连接失败，降级为 InMemorySaver")
        return InMemorySaver()

def build_graph():
    builder = StateGraph(SupervisorState)
    # ... 添加节点和边 ...
    checkpointer = _get_checkpointer()
    return builder.compile(checkpointer=checkpointer)
```

### 新增配置项

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LANGGRAPH_DB_URI` | PostgreSQL 连接串 | `postgresql://localhost:5432/langgraph` |
| `LANGGRAPH_CHECKPOINTER` | checkpointer 类型（`memory`/`postgres`） | `postgres` |

### 数据库要求

PostgreSQL 14+，LangGraph 自动建表。开发环境 Docker 启动：

```bash
docker run -d --name langgraph-pg -p 5432:5432 -e POSTGRES_DB=langgraph postgres:16
```

### Time-travel 能力

无需额外代码，checkpoint 自带：

```python
# 查看执行历史
history = list(graph.get_state_history(config))

# 回放：从某节点之前重新执行
target = next(s for s in history if s.next == ("reflect",))
graph.invoke(None, target.config)

# 分叉：修改状态后走不同路径
fork_config = graph.update_state(target.config, {"user_request": "修改后的请求"})
graph.invoke(None, fork_config)
```

## Tracing 层（LangSmith）

### 环境变量配置

```bash
# .env 新增
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=test-agents-v3
```

零代码改动，每次 `graph.invoke()` / `graph.stream()` 自动追踪。

### 追踪捕获内容

| 追踪内容 | 说明 |
|---|---|
| 节点执行 | 每个节点的输入 state / 输出 state |
| LLM 调用 | prompt、模型、token 用量、延迟、完整响应 |
| 工具调用 | 工具名、输入参数、输出结果 |
| 条件路由 | 每个条件边走了哪条路径 |
| 子图执行 | code_analyzer / case_reviewer 内部的完整 ReAct 循环 |

### Metadata 标注

在 `main.py` 的 invoke 调用处添加 tags 和 metadata：

```python
config = {
    "configurable": {"thread_id": session_id},
    "tags": [environment, "supervisor"],
    "metadata": {
        "user_id": user_id,
        "request_type": "full_pipeline",  # 或 "single_worker"
        "plan_iterations": state.get("current_step_index", 0),
    }
}
result = graph.invoke(input, config)
```

LangSmith UI 中可按 tag/metadata 筛选追踪记录。

### 选择性追踪

```python
import langsmith as ls

# 只追踪正式请求
with ls.tracing_context(enabled=True, project_name="test-agents-prod"):
    result = graph.invoke(user_request, config)

# 跳过预热等非关键调用
with ls.tracing_context(enabled=False):
    _ = graph.invoke({"user_request": "warmup"}, config)
```

### 本地调试

开启 LangSmith Studio，可视化步进每个节点、查看 state 快照、检查 LLM 响应质量，无需改代码。

## 错误处理

### Checkpointing 容错

`_get_checkpointer()` 中已包含降级逻辑：PostgresSaver 连接失败时降级为 InMemorySaver 并打出 warning 日志，业务不中断。

### Tracing 容错

LangSmith SDK 内置行为：API Key 未设置或无效时追踪静默跳过，不影响业务执行。

### 结构化日志

关键节点入口添加结构化日志，补充本地可观测性：

```python
import logging
logger = logging.getLogger(__name__)

def planner(state: SupervisorState) -> dict:
    logger.info("planner.start", extra={"user_request": state["user_request"][:100]})
    result = ...
    logger.info("planner.end", extra={"step_count": len(result["plan"].steps)})
    return result
```

即使不打开 LangSmith，本地日志也能看到节点流转。

## 测试策略

| 测试类型 | 说明 |
|---|---|
| 现有单元测试 | 继续使用 `InMemorySaver`，设 `LANGGRAPH_CHECKPOINTER=memory` |
| Checkpoint 集成测试 | 新增 `test_checkpoint.py`，用 `SqliteSaver` 验证 state 持久化和 `get_state_history` |
| Tracing 验证 | 测试时设 `LANGSMITH_TRACING=false`，避免测试数据污染 LangSmith |
| 端到端验证 | 手动触发完整请求，在 LangSmith UI 确认追踪记录完整 |

```python
# conftest.py
import os
os.environ["LANGGRAPH_CHECKPOINTER"] = "memory"
os.environ["LANGSMITH_TRACING"] = "false"
```

## 涉及文件

| 文件 | 改动 |
|---|---|
| `test_agents/graph/builder.py` | 替换 InMemorySaver 为 `_get_checkpointer()` 工厂 |
| `test_agents/config.py` | 新增 `LANGGRAPH_DB_URI`、`LANGGRAPH_CHECKPOINTER` 配置 |
| `test_agents/main.py` | invoke 调用添加 tags/metadata |
| `test_agents/agents/supervisor.py` | 关键节点添加结构化日志 |
| `.env.example` | 新增 LangSmith 和 PostgreSQL 配置模板 |
| `test_agents/tests/conftest.py` | 测试环境变量默认值 |
| `test_agents/tests/test_checkpoint.py` | 新增 checkpoint 集成测试 |
