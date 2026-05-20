# LangGraph 可观测性与记忆系统设计

**日期**: 2026-05-20
**方案**: LangSmith + PostgresSaver + PostgresStore

## 目标

为 Test Agents v3 建立完整的可观测性体系，覆盖调试排障、生产监控、回放审计三个维度，并实现短期记忆与长期记忆的统一管理。

## 依赖与安装

### Python 包（pip）

```bash
pip install -U "psycopg[binary,pool]" langgraph-checkpoint-postgres langsmith
```

| 包 | 版本 | 用途 | 说明 |
|---|---|---|---|
| `langgraph-checkpoint-postgres` | >=3.1.0 | PostgresSaver + PostgresStore | 同时提供 Checkpointing 和 Store 的 PostgreSQL 实现 |
| `psycopg[binary,pool]` | >=3.2.0 | PostgreSQL 驱动 | `binary` 提供 C 加速，`pool` 提供连接池；`langgraph-checkpoint-postgres` 的依赖 |
| `langsmith` | >=0.3.45 | LangSmith 追踪 SDK | 已作为 `langchain-core` 的依赖安装，通常无需单独安装 |

**注意**：`PostgresStore` 不是独立包，它包含在 `langgraph-checkpoint-postgres` 中（`from langgraph.store.postgres import PostgresStore`）。不需要安装 `langgraph-store-postgres`（该包不存在）。

### 基础设施

| 工具 | 用途 | 安装方式 |
|---|---|---|
| PostgreSQL 14+ | Checkpoint + Store 数据库 | `docker run -d --name langgraph-pg -p 5432:5432 -e POSTGRES_DB=langgraph postgres:16` |

### requirements.txt 新增

```
langgraph-checkpoint-postgres>=3.1.0
psycopg[binary,pool]>=3.2.0
```

`langsmith` 已通过 `langchain-core` 间接依赖，无需显式添加。

## 整体架构

三层独立系统各司其职：

- **Checkpointing 层**：`PostgresSaver` 替换 `InMemorySaver`，负责短期记忆（thread 内状态持久化）。支撑 `confirm_plan` 的 interrupt/resume、故障恢复、time-travel 回放。
- **Store 层**：`PostgresStore` 替代 `reflection_experience.md`，负责长期记忆（跨 thread 经验存取与检索）。planner 可按意图类型检索历史经验辅助规划。
- **Tracing 层**：LangSmith 通过 `LANGSMITH_TRACING=true` 环境变量自动激活，捕获每次 `graph.invoke()` / `graph.stream()` 的完整执行链路。

代码交汇点在 `builder.py` 的 `compile(checkpointer=..., store=...)` 参数，其余全靠环境变量和配置。

```
┌─────────────────────────────────────────────────────┐
│                  LangGraph Supervisor Graph          │
│                                                      │
│  planner ←── Store.search() ──→ save_experience     │
│     ↓           (长期记忆检索)        (长期记忆写入)  │
│  confirm → dispatch → worker → reflect               │
│                            ↑          ↓              │
│                      code_analyzer  synthesize       │
│                      case_reviewer                   │
├───────────────┬────────────────┬─────────────────────┤
│ Checkpointing │     Store      │  Tracing (LangSmith)│
│ PostgresSaver │ PostgresStore  │  自动捕获:          │
│ 短期记忆      │ 长期记忆       │  节点/LLM/工具/路由 │
│ interrupt恢复 │ 跨thread经验   │  环境变量驱动       │
│ time-travel   │ 按意图检索     │  Studio 可视化调试  │
└───────────────┴────────────────┴─────────────────────┘
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

PostgreSQL 14+，LangGraph 自动建表（`cp.setup()` / `store.setup()`）。开发环境 Docker 启动方式见上方「依赖与安装」章节。

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

## Store 层（长期记忆）

### 当前问题

`save_experience` 节点将经验追加写入 `data/reflection_experience.md` 文件，存在以下问题：

- 无检索能力，planner prompt 只能整段注入（当前甚至未实现注入）
- 文件无限增长，指纹去重只能避免完全重复，无语义去重
- 非结构化存储，无法按意图类型筛选

### 解决方案

用 LangGraph 的 `Store` 替代文件存储。Store 通过 `compile(store=...)` 挂载，节点函数签名中接收 `store` 参数，可跨 thread 存取。

```
当前:  save_experience → 写 markdown 文件 → planner 无法按需检索
升级:  save_experience → store.put() → planner 用 store.search() 按意图检索
```

### Namespace 设计

经验按意图类型分 namespace 存储：

```python
namespace = ("experience", intent_type)
# 例: ("experience", "code_analysis"), ("experience", "case_review"), ("experience", "full_pipeline")
```

每个经验条目是一个 JSON 文档：

```python
store.put(
    namespace=("experience", "code_analysis"),
    key=f"exp_{timestamp}",
    value={
        "intent": "分析订单模块代码变更",
        "steps": ["code_analyzer"],
        "results": "step 1: success",
        "reflection": "分析完成，建议关注异常处理分支",
        "created_at": "2026-05-20T10:30:00Z",
    }
)
```

### 代码改动

**builder.py** — 挂载 Store：

```python
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

def _get_store():
    mode = os.getenv("LANGGRAPH_STORE", "postgres")
    if mode == "memory":
        return InMemoryStore()
    store = PostgresStore.from_conn_string(
        os.getenv("LANGGRAPH_DB_URI", "postgresql://localhost:5432/langgraph")
    )
    store.setup()
    return store

def build_graph():
    # ...
    return builder.compile(checkpointer=_get_checkpointer(), store=_get_store())
```

**supervisor.py** — save_experience 节点改用 Store：

```python
def save_experience_node(state: SupervisorState, *, store: BaseStore) -> dict:
    intent = state["plan"].intent
    intent_type = _classify_intent(intent)  # "code_analysis" / "case_review" / "full_pipeline"

    store.put(
        namespace=("experience", intent_type),
        key=f"exp_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        value={
            "intent": intent,
            "steps": [s.agent for s in state["plan"].steps],
            "results": _summarize_results(state["step_results"]),
            "reflection": state.get("reflection_feedback", ""),
            "created_at": datetime.now().isoformat(),
        }
    )
    return {}
```

**supervisor.py** — planner 节点检索历史经验：

```python
def planner_node(state: SupervisorState, *, store: BaseStore, config: RunnableConfig) -> dict:
    experiences = []
    for ns in [("experience", "code_analysis"), ("experience", "case_review"), ("experience", "full_pipeline")]:
        items = store.search(ns, limit=5)
        experiences.extend([item.value for item in items])

    relevant = _filter_relevant(experiences, state["user_request"])
    prompt = load_prompt("planner", user_request=state["user_request"], experience=_format_experience(relevant))
    # ...
```

### 新增配置项

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LANGGRAPH_STORE` | Store 类型（`memory`/`postgres`） | `postgres` |

与 Checkpointer 共用 `LANGGRAPH_DB_URI`，同一 PostgreSQL 实例。

### 迁移策略

1. 提供迁移脚本读取现有 `reflection_experience.md`，解析后写入 Store
2. `save_experience_node` 不再写文件，`data/reflection_experience.md` 保留为只读历史
3. 迁移完成后文件可归档

### 未来增强（本次不实现）

- **向量检索**：为 Store 配置 embedding，`store.search()` 支持语义相似度检索，替代当前的粗筛
- **经验衰减**：按时间或访问频率降权旧经验，避免过时建议影响规划

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
| 现有单元测试 | 继续使用 `InMemorySaver` + `InMemoryStore`，设 `LANGGRAPH_CHECKPOINTER=memory`、`LANGGRAPH_STORE=memory` |
| Checkpoint 集成测试 | 新增 `test_checkpoint.py`，用 `SqliteSaver` 验证 state 持久化和 `get_state_history` |
| Store 集成测试 | 新增 `test_store.py`，用 `InMemoryStore` 验证 `put`/`search`/`get` 及 namespace 隔离 |
| Tracing 验证 | 测试时设 `LANGSMITH_TRACING=false`，避免测试数据污染 LangSmith |
| 端到端验证 | 手动触发完整请求，在 LangSmith UI 确认追踪记录完整；验证经验跨 thread 可检索 |

```python
# conftest.py
import os
os.environ["LANGGRAPH_CHECKPOINTER"] = "memory"
os.environ["LANGGRAPH_STORE"] = "memory"
os.environ["LANGSMITH_TRACING"] = "false"
```

## 涉及文件

| 文件 | 改动 |
|---|---|
| `test_agents/graph/builder.py` | 替换 InMemorySaver 为 `_get_checkpointer()` + `_get_store()` 工厂 |
| `test_agents/config.py` | 新增 `LANGGRAPH_DB_URI`、`LANGGRAPH_CHECKPOINTER`、`LANGGRAPH_STORE` 配置 |
| `test_agents/main.py` | invoke 调用添加 tags/metadata |
| `test_agents/agents/supervisor.py` | save_experience 改用 Store；planner 检索历史经验；关键节点添加结构化日志 |
| `.env.example` | 新增 LangSmith 和 PostgreSQL 配置模板 |
| `test_agents/tests/conftest.py` | 测试环境变量默认值 |
| `test_agents/tests/test_checkpoint.py` | 新增 checkpoint 集成测试 |
| `scripts/migrate_experience.py` | 新增迁移脚本，将 reflection_experience.md 导入 Store |
