# Test Agents 自建可观测体系设计

**日期**: 2026-05-22
**方案**: 标准库 logging + ContextVar + JSON Lines（纯自建、内网友好、零新增依赖）
**取代**: 本设计在内网场景下取代 `2026-05-20-langgraph-tracing-design.md`（LangSmith + Postgres 方案）。该旧方案因数据出网约束被搁置。

## 1. 目标

为 Test Agents v3 建立一套可观测体系，同时覆盖：

1. **定位问题** —— worker 报错、reflect 拒绝、计划反复 replan 时，能快速追到根因
2. **性能/成本分析** —— 每个 LLM 调用耗时与 token、claude_cli 调用时长、worker 总耗时
3. **行为可解释性** —— 完整复盘 supervisor 的决策、worker 的工具调用序列

约束：

- 部署在内网，**禁止任何数据出网**（排除 LangSmith 等 SaaS）
- **不引入新基础设施**（排除自托管 LangFuse、Postgres、Prometheus）
- 不引入新 Python 第三方依赖，全部基于标准库实现

## 2. 技术栈

- Python 标准库 `logging`
- `contextvars.ContextVar`（跨节点 / 工具传递 trace_id、span_id）
- JSON Lines 文件输出
- 无任何新增 `requirements.txt` 条目

## 3. 总体架构

```
┌──────────────────────────────────────────────────────────────┐
│ 用户请求进入 main.py → 生成 trace_id 写入 ContextVar         │
└──────────────────────┬───────────────────────────────────────┘
                       ↓
        ┌──────────────────────────────────┐
        │  各节点 / 工具 / LLM 调用日志       │
        │  ├─ 自动注入 trace_id / span_id    │
        │  ├─ 自动注入耗时                    │
        │  └─ 输出结构化 JSON                 │
        └──────────────┬───────────────────┘
                       ↓
        ┌──────────────────────────────────┐
        │       JsonlMultiHandler            │
        │  ├─ 写主日志 app-YYYY-MM-DD.jsonl  │
        │  └─ 写 per-trace traces/<id>.jsonl │
        └──────────────────────────────────┘

        执行结束时：metrics.jsonl 追加一行 summary
```

## 4. 新增模块

新建 `test_agents/observability/` 包，按职责拆分为以下文件：

| 文件 | 职责 |
|---|---|
| `observability/__init__.py` | 包入口，导出公共 API：`setup_logging`、`new_trace`、`new_span`、`log_node`、`log_tool`、`log_llm_call`、`flush_metrics` |
| `observability/context.py` | 定义 `trace_id_var`、`span_id_var`（`ContextVar`），工具函数 `new_trace()` / `new_span()` / `get_trace_id()` / `get_span_id()` |
| `observability/logger.py` | `setup_logging()` 入口：根据 `TEST_AGENTS_LOG_LEVEL` 注册 Filter 和 Handler；定义自定义级别 `TRACE=5` |
| `observability/filters.py` | `ContextInjectFilter`：在 `filter(record)` 中从 ContextVar 读取 trace_id / span_id 注入到 `LogRecord` |
| `observability/handlers.py` | `JsonlMultiHandler(logging.Handler)`：emit 时序列化 LogRecord → JSON，同时分发到两个底层 writer —— 主日志用标准库 `logging.handlers.TimedRotatingFileHandler` 按天滚动，per-trace 文件按 `record.trace_id` 路由到 `traces/<trace_id>.jsonl`（首次见到 trace_id 时打开文件句柄并缓存，trace 结束时关闭） |
| `observability/decorators.py` | `@log_node(name)`（节点装饰器，记 enter/exit + 耗时 + 异常）、`@log_tool`（工具装饰器，记 input/output + 耗时 + 异常）、`log_llm_call(llm, messages, **kwargs)`（LLM 调用包装，记 model / tokens / 耗时） |
| `observability/metrics.py` | `MetricsCollector`：每个 trace 维护一份累计计数（node_count / llm_call_count / tool_call_count / replan_count / ts_start / status），`flush_metrics()` 在 trace 结束追加一行到 `metrics.jsonl` |

## 5. 数据流改造点

| 改造点 | 改动说明 |
|---|---|
| `test_agents/main.py` | 模块导入后调用 `setup_logging()`；`run_test_agents()` 每次请求入口调用 `new_trace(user_request=...)` 并用 `try/finally` 保证 `flush_metrics(status=...)` 一定执行 |
| `test_agents/config.py` | 新增 `TEST_AGENTS_LOG_LEVEL`(默认 `INFO`)、`TEST_AGENTS_LOG_DIR`(默认 `logs/`)、`TEST_AGENTS_LOG_TRACE_FILES`(默认 `true`)、`TEST_AGENTS_LOG_TRACES_KEEP`(默认 `1000`)、`TEST_AGENTS_LOG_RETAIN_DAYS`(默认 `30`) |
| `test_agents/agents/supervisor.py` | 给以下节点函数加装饰器：`planner` → `@log_node("planner")`、`dispatch` → `@log_node("dispatch")`、`reflect` → `@log_node("reflect")`、`synthesize` → `@log_node("synthesize")`、`save_experience` → `@log_node("save_experience")`。**`confirm_plan` 不装饰**，因其调用 `langgraph.types.interrupt` 会抛 `GraphInterrupt`，由 `main.py` 入口外层用专门的 `log_confirm_plan()` 包装函数处理 interrupt 语义（见 §6） |
| `test_agents/agents/worker_base.py` | 子图节点 `agent` → `@log_node("worker.agent")`、`reflect` → `@log_node("worker.reflect")`；`route_from_reflect` 检测到 replan 时调用 `metrics.incr("replan_count")` |
| `test_agents/tools/base.py` | `TestAgentTool._run` 直接在基类内联实现日志切面（与 `decorators.py` 中的 `@log_tool` 共享同一份核心实现 `_log_tool_invocation(name, args, fn)`，避免代码重复）；由于所有工具都继承基类，子类（`ClaudeCliTool` / `ReadFileTool` / `GrepTool` / `GlobTool` / `ListDirTool` / `TestCaseParserTool` / `BusinessKnowledgeTool`）自动获得工具日志，**不需要修改任何工具子类代码** |
| LLM 调用 | 在 `supervisor.py` / `worker_base.py` 所有 `get_llm().invoke(...)` / `.with_structured_output(...).invoke(...)` 调用处改为 `log_llm_call(llm_or_runnable, messages, model=...)`；该包装函数内部 catch 异常并记录后重新抛出，业务语义不变 |

## 6. trace_id / span_id 传递机制

- **`trace_id`**: 主图入口生成（格式 `tr_<8 字符 hex>`），存入 `trace_id_var: ContextVar[str]`。同一次用户请求的所有日志共享。
- **`span_id`**: 节点 / 工具 / LLM 调用进入时生成（格式 `sp_<8 字符 hex>`），存入 `span_id_var`。`parent_span_id` 从外层 span 自动继承。
- 装饰器实现：
  ```python
  def log_node(name):
      def deco(fn):
          @functools.wraps(fn)
          def wrapper(*args, **kwargs):
              token = span_id_var.set(_new_span_id())
              parent = _get_parent_span()
              t0 = time.perf_counter()
              logger.info("node.enter", extra={"event": "node.enter", "node": name, "parent_span_id": parent})
              try:
                  result = fn(*args, **kwargs)
                  logger.info("node.exit", extra={"event": "node.exit", "node": name,
                                                  "duration_ms": int((time.perf_counter()-t0)*1000),
                                                  "status": "ok"})
                  metrics.incr("node_count")
                  return result
              except Exception as e:
                  logger.exception("node.error", extra={"event": "node.exit", "node": name,
                                                       "duration_ms": int((time.perf_counter()-t0)*1000),
                                                       "status": "error"})
                  metrics.set_status("error")
                  raise
              finally:
                  span_id_var.reset(token)
          return wrapper
      return deco
  ```
- ContextVar 在 LangGraph 同步执行下天然安全；若未来切到 async，`asyncio.Task` 创建时会自动复制 ContextVar 快照，仍然安全。

**关于 `GraphInterrupt` 的特殊处理**：

`langgraph.types.interrupt` 通过抛出 `GraphInterrupt` 异常实现暂停。装饰器中要识别这一异常并视为"正常控制流"，不要记 error、不要置 metrics.status=error：

```python
from langgraph.errors import GraphInterrupt

except GraphInterrupt:
    logger.info("node.pause", extra={"event": "node.pause", "node": name,
                                     "duration_ms": ..., "status": "paused"})
    raise  # 不计为错误，但要让 LangGraph 继续处理
except Exception as e:
    ...  # 原有错误处理
```

`confirm_plan` 节点除外（不装饰），因为它是 100% 走 interrupt 的节点，单独的"暂停"事件在 `main.py` 处理 interrupt 恢复时由 `log_confirm_plan()` 显式记录一次更有语义。

## 7. 日志格式（每条 JSON Line）

```json
{
  "ts": "2026-05-22T10:30:45.123Z",
  "level": "INFO",
  "logger": "test_agents.supervisor",
  "trace_id": "tr_8a3f2c1d",
  "span_id": "sp_b21c4a90",
  "parent_span_id": "sp_a1f0e234",
  "event": "node.enter" | "node.exit" | "llm.call" | "tool.call" | "error",
  "node": "planner",
  "tool": "claude_cli",
  "duration_ms": 1234,
  "status": "ok" | "error",
  "input_summary": "...",
  "output_summary": "...",
  "input_full": "...",
  "output_full": "...",
  "error": { "type": "TimeoutError", "message": "...", "traceback": "..." },
  "model": "gpt-4o",
  "tokens": { "prompt": 123, "completion": 45, "total": 168 },
  "extra": { ... }
}
```

字段约定：

- `input_summary` / `output_summary`：截断到前 200 字符，所有级别都有
- `input_full` / `output_full`：截断到 2000 字符，仅 DEBUG / TRACE 级别才出现
- `error`：仅 status=error 时出现
- `tokens`：仅 LLM 事件且 LangChain 响应包含 `usage_metadata` 时出现
- `parent_span_id`：根节点为 `null`

## 8. 三档日志级别行为

| 级别 | 节点 enter/exit | LLM 调用 | 工具调用 | state 快照 |
|---|---|---|---|---|
| **INFO**（默认） | ✓ + 摘要 | ✓ + tokens + 耗时 | ✓ + 摘要 + 耗时 | ✗ |
| **DEBUG** | ✓ + 摘要 | ✓ + prompt/response 全文(2KB) | ✓ + input/output 全文(2KB) | ✗ |
| **TRACE**（自定义级别=5） | ✓ + state 快照 | + state 快照 | 同 DEBUG | ✓（节点 enter/exit 时序列化 `SupervisorState` / `WorkerState`） |

`TRACE` 级别通过 `logging.addLevelName(5, "TRACE")` 注册，并在 `logger.py` 暴露 `log.trace(msg, ...)` 便捷方法。

## 9. 文件布局

```
logs/
  app-2026-05-22.jsonl          # 主日志，按天滚动，默认保留 30 天
  app-2026-05-21.jsonl
  metrics.jsonl                  # 每次执行追加一行 summary（不滚动，由用户自行归档）
  traces/
    tr_8a3f2c1d.jsonl            # 单次执行的全部日志
    tr_9b4e1d22.jsonl
    ...
```

清理策略：

- **主日志**：`TimedRotatingFileHandler(when='midnight', backupCount=TEST_AGENTS_LOG_RETAIN_DAYS)`
- **per-trace 文件**：`setup_logging()` 启动时扫描 `traces/`，按 mtime 降序保留最新 `TEST_AGENTS_LOG_TRACES_KEEP` 个文件，多余的删除
- **metrics.jsonl**：不自动清理，运维自行处理（每行很小，长期保留不会成为瓶颈）

## 10. metrics.jsonl 行格式

```json
{
  "trace_id": "tr_8a3f2c1d",
  "ts_start": "2026-05-22T10:30:45.123Z",
  "ts_end": "2026-05-22T10:31:12.456Z",
  "duration_ms": 27333,
  "user_request": "分析订单模块代码变更",
  "status": "ok" | "error",
  "node_count": 7,
  "llm_call_count": 5,
  "tool_call_count": 12,
  "replan_count": 0,
  "final_answer_length": 1024,
  "error": null
}
```

`flush_metrics()` 在 `run_test_agents()` 的 `finally` 块中调用，无论成功失败都会输出一行。

## 11. 测试策略

新增 `test_agents/tests/test_observability/` 目录：

- `test_context.py`：ContextVar 行为 —— 嵌套 span、父子继承、跨函数调用、退出后 reset 正确
- `test_filters.py`：`ContextInjectFilter` 注入正确性，空上下文时也能 emit
- `test_handlers.py`：`JsonlMultiHandler` 双写 —— 主日志一行、per-trace 一行；trace 切换时正确路由；文件按天切分
- `test_decorators.py`：装饰器 —— 成功路径、异常路径、耗时字段非零、metrics 计数正确
- `test_metrics.py`：`MetricsCollector` —— 累计正确、flush 后 metrics.jsonl 多一行、status 在异常时为 error
- `test_integration_observability.py`：跑一次完整 mock pipeline，校验：
  - `traces/<trace_id>.jsonl` 存在且行数 ≥ 节点数 × 2
  - 所有事件按时间排序构成合理调用链
  - `metrics.jsonl` 多出一行且字段齐全
- 性能验证（非自动化）：开 `DEBUG` 跑 10 次 mock pipeline，目测无明显卡顿、日志文件可读

## 12. 风险与权衡

- **ContextVar 与 LangGraph 兼容性**：当前 LangGraph 同步执行下安全；若未来切到异步，需补充 async 测试覆盖
- **日志文件体积**：DEBUG 级开 claude_cli 全文记录可能单次执行 100KB+，靠 traces 目录数量上限 + 主日志按天切分 + 字符截断（2KB）三重控制
- **装饰器 vs 内联打点**：选用装饰器降低业务代码侵入性，代价是栈帧多一层，对调试断点略有干扰，可接受
- **不脱敏**：本次明确不做脱敏，未来若要把日志拷出内网分析，需评估二次处理流程
- **磁盘写入是同步的**：高频日志可能成为热点，目前 LangGraph 执行节奏受 LLM 调用主导（百毫秒级），同步写盘不会成为瓶颈；如未来需要再考虑 `QueueHandler` 异步化

## 13. 非目标（YAGNI）

- 不做 Prometheus / OpenTelemetry 指标导出
- 不做实时 Web UI（如需可视化未来再加 LangFuse 自托管）
- 不做日志加密、不做脱敏
- 不做集中式日志收集（ELK / Loki）
- 不做告警 / 通知机制
