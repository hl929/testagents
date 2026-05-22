# Test Agents 自建可观测体系设计

**日期**: 2026-05-22
**方案**: 标准库 logging + ContextVar + JSON Lines + LangGraph callback（纯自建、内网友好、零新增依赖）
**取代**: 本设计在内网场景下取代 `2026-05-20-langgraph-tracing-design.md`（LangSmith + Postgres 方案）。该旧方案因数据出网约束被搁置。
**评审记录**:
- 2026-05-22 CEO 评审（HOLD SCOPE，8 finding 全部纳入）
- 2026-05-22 Eng 评审（12 finding + outside voice 7 finding 全部纳入）

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
- `contextvars.ContextVar`（跨调用传递 trace_id，**不再使用 span_id_var**，见 §6 Finding 1.5）
- **`langchain_core.callbacks.BaseCallbackHandler`**（LangGraph 自带的事件拦截机制，无需新增依赖）
- JSON Lines 文件输出
- 无任何新增 `requirements.txt` 条目

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ main.py: run_test_agents(user_request)                               │
│   ├─ setup_logging()                  ← 模块导入时一次               │
│   └─ return _with_observability(target_func, user_request)           │
│        ├─ trace_token = new_trace(user_request)                      │
│        ├─ try: result = target_func(_make_run_config())              │
│        ├─    flush_metrics(status="ok|aborted", final_answer_length) │
│        ├─ except BaseException:                                      │
│        ├─    flush_metrics(status="error")                           │
│        └─ finally: close_trace_writer()                              │
│                                                                     │
│   _make_run_config() returns:                                        │
│     {"callbacks": [ObservabilityCallback()],                         │
│      "configurable": {"thread_id": ...}}                             │
└──────────────────────┬──────────────────────────────────────────────┘
                       ↓
         LangGraph 引擎执行（自动触发 callback）
                       ↓
   ObservabilityCallback (BaseCallbackHandler 子类)
   ├─ on_chain_start         → node.enter (仅当 metadata.langgraph_node 存在)
   ├─ on_chain_end / error   → node.exit + duration_ms + replan 推断
   ├─ on_chat_model_start    → llm.call start (主路径)
   ├─ on_llm_start           → llm.call start (兼容 completion 模型)
   ├─ on_chat_model_end/llm_end → llm.call + tokens + duration_ms
   ├─ on_tool_start          → tool.call start
   └─ on_tool_end / error    → tool.call + duration_ms
                       ↓
   logging.getLogger("test_agents") ← Filter 自动注入 trace_id
                       ↓
   JsonlMultiHandler
   ├─ TimedRotatingFileHandler → logs/app-YYYY-MM-DD.jsonl
   └─ per-trace writer (LRU) → logs/traces/<trace_id>.jsonl
                       ↓
   trace 结束：flush_metrics() → logs/metrics.jsonl 追加一行
```

**Approach 选型说明（CEO 评审 D1）**：选 callback 为主的方案。
节点 / LLM / 工具事件全部走 LangGraph callback 自动拦截，业务代码改动 0；
trace 生命周期与 metrics 聚合走 main.py 入口的 `_with_observability` 包装函数手动控制。
**MetricsCollector 是全局单例 + dict[trace_id, counters]**（Eng 评审 Finding 4.7），
不挂在 callback 实例上，避免每次 `app.invoke` 新建 callback 时状态丢失。

## 4. 新增模块

新建 `test_agents/observability/` 包，按职责拆分为以下文件：

| 文件 | 职责 |
|---|---|
| `observability/__init__.py` | 包入口，导出公共 API：`setup_logging`、`new_trace`、`flush_metrics`、`close_trace_writer`、`make_run_config`、`ObservabilityCallback` |
| `observability/context.py` | 定义 `trace_id_var: ContextVar[str]`；工具函数 `new_trace(user_request)` 生成 trace_id 并写入 ContextVar、`get_trace_id()`（默认 None）。**不再有 `span_id_var`**（Eng Finding 1.5：span_id 由 callback 内部 dict 维护） |
| `observability/logger.py` | `setup_logging()` 入口：根据 `TEST_AGENTS_LOG_LEVEL` 注册 Filter 和 Handler；定义自定义级别 `TRACE=5` 和 `OFF`（含义见 §8）。**幂等**：连续调用 2 次不重复注册 handler |
| `observability/filters.py` | `ContextInjectFilter`：在 `filter(record)` 中从 `trace_id_var` 读取注入到 `LogRecord.trace_id`，未 set 时注入 None。**span_id / parent_span_id 由 callback 直接通过 logger.info(..., extra={...}) 传**，不走 ContextVar |
| `observability/handlers.py` | `JsonlMultiHandler(logging.Handler)`：emit 时序列化 LogRecord → JSON，分发到：① 主日志 `TimedRotatingFileHandler` 按天滚动写 `app-YYYY-MM-DD.jsonl`；② per-trace 文件按 `record.trace_id` 路由到 `traces/<trace_id>.jsonl`，**LRU 缓存最多 `TEST_AGENTS_LOG_TRACE_HANDLES` 个文件句柄**（默认 64）；③ `trace_id` 为 None 时**不写 per-trace 文件**；④ 序列化遇到不可序列化对象用 `str(obj)` 并加 `___unserializable___: true` 标记，永不抛 TypeError |
| `observability/callback.py` | `ObservabilityCallback(BaseCallbackHandler)`，详见 §5 行为说明。**所有回调方法都包 try/except**，吞掉自身异常仅写一条 `event: callback.failed` 日志，**绝不向 LangGraph 传播** |
| `observability/metrics.py` | **全局单例** `MetricsCollector`：维护 `dict[trace_id, dict[str, int/str]]`（Eng Finding 4.7）。API：`new_trace_metrics(trace_id, user_request)`、`incr(trace_id, key)`、`flush(trace_id, status, final_answer_length)` 追加一行到 `metrics.jsonl` 后从 dict 删除，写失败静默降级到 stderr |

## 5. callback 详细行为（Eng Finding 1.1/1.2/1.3/1.4/1.5/2.2/2.3/4.1/4.2/4.3/4.4/4.7）

```python
class ObservabilityCallback(BaseCallbackHandler):
    # 类级别共享状态（不挂 self，因为每次 invoke 新建实例）
    _spans: dict[UUID, str] = {}              # run_id → span_id
    _last_node_per_trace: dict[str, str] = {} # trace_id → last_node_name

    def on_chain_start(self, serialized, inputs, *, run_id,
                       parent_run_id=None, metadata=None, **kw):
        try:
            # Finding 1.2: 只记真实节点，过滤 LangGraph 内部 chain 噪声
            node_name = (metadata or {}).get("langgraph_node")
            # Finding 4.4: 子图 wrapper span 也保留（其 metadata 也带 langgraph_node）
            if not node_name:
                return
            span_id = _new_span_id()
            self._spans[run_id] = span_id
            parent_span = self._spans.get(parent_run_id)
            logger.info("node.enter", extra={
                "event": "node.enter",
                "node": node_name,
                "span_id": span_id,
                "parent_span_id": parent_span,
                "input_summary": _summarize(inputs, kind="dict"),  # Finding 2.3
                "input_full": _full(inputs, kind="dict"),          # DEBUG only
            })
        except Exception:
            logger.warning("callback.failed", exc_info=True)

    def on_chain_end(self, outputs, *, run_id, **kw):
        try:
            span_id = self._spans.pop(run_id, None)  # Finding 4.3: cleanup
            if span_id is None: return                # 之前被过滤了
            node_name = ...  # 从 span 记录提取
            trace_id = get_trace_id()
            # Finding 2.2/4.2: replan 推断
            last = self._last_node_per_trace.get(trace_id)
            if last == "reflect" and node_name == "planner":
                metrics.incr(trace_id, "replan_count")
            self._last_node_per_trace[trace_id] = node_name
            metrics.incr(trace_id, "node_count")
            logger.info("node.exit", extra={
                "event": "node.exit", "node": node_name,
                "duration_ms": ..., "status": "ok",
                "output_summary": _summarize(outputs, kind="dict"),
            })
        except Exception:
            logger.warning("callback.failed", exc_info=True)

    def on_chain_error(self, error, *, run_id, **kw):
        try:
            span_id = self._spans.pop(run_id, None)  # Finding 4.3: cleanup
            if span_id is None: return
            logger.error("node.exit", extra={
                "event": "node.exit", "status": "error",
                "error": {"type": type(error).__name__, "message": str(error),
                          "traceback": traceback.format_exc()},
            })
        except Exception:
            logger.warning("callback.failed", exc_info=True)

    # Finding 1.1: ChatOpenAI 触发 on_chat_model_start
    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._on_llm_call_start(serialized, messages, run_id, kind="chat")

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self._on_llm_call_start(serialized, prompts, run_id, kind="completion")

    def _on_llm_call_start(self, serialized, payload, run_id, kind):
        try:
            # Finding 9: model 字段提取
            model = (serialized.get("kwargs", {}).get("model_name") or
                     (serialized.get("id") or [None])[-1])
            span_id = _new_span_id()
            self._spans[run_id] = span_id
            # Finding 2.3: 不同事件源不同序列化策略
            if kind == "chat":
                summary = " ".join(m.content for m in payload[0] if hasattr(m, "content"))[:200]
            else:
                summary = (payload[0] if payload else "")[:200]
            logger.info("llm.call", extra={
                "event": "llm.call", "model": model, "phase": "start",
                "span_id": span_id, "input_summary": summary,
            })
        except Exception:
            logger.warning("callback.failed", exc_info=True)

    def on_llm_end(self, response, *, run_id, **kw):
        self._on_llm_call_end(response, run_id)
    on_chat_model_end = on_llm_end

    def _on_llm_call_end(self, response, run_id):
        try:
            self._spans.pop(run_id, None)  # Finding 4.3
            trace_id = get_trace_id()
            metrics.incr(trace_id, "llm_call_count")
            tokens = getattr(response, "usage_metadata", None) or {}
            extra = {"event": "llm.call", "phase": "end", "duration_ms": ...}
            if tokens:
                extra["tokens"] = {"prompt": tokens.get("input_tokens"),
                                   "completion": tokens.get("output_tokens"),
                                   "total": tokens.get("total_tokens")}
            logger.info("llm.call", extra=extra)
        except Exception:
            logger.warning("callback.failed", exc_info=True)

    on_llm_error = on_chat_model_error = lambda self, error, *, run_id, **kw: (
        self._spans.pop(run_id, None),
        logger.error("llm.error", extra={"event": "error", "error": ...}),
    )

    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        # Finding 2.3: input_str 直接截断
        ...

    def on_tool_end / on_tool_error: # 同 _spans.pop，metrics.incr("tool_call_count")
        ...
```

### close_trace_writer 增强（Eng Finding 4.3）

```python
def close_trace_writer():
    """main.py finally 调用。关闭 per-trace 文件句柄 + 清理 callback 跨事件 dict"""
    trace_id = get_trace_id()
    if trace_id:
        JsonlMultiHandler.singleton.close_trace(trace_id)
        ObservabilityCallback._last_node_per_trace.pop(trace_id, None)
```

## 6. 数据流改造点

approach C 让业务代码改动量降到最小，且修复 Eng 评审发现的所有问题：

| 改造点 | 改动说明 |
|---|---|
| `test_agents/main.py` | 模块导入时调用 `setup_logging()`。**Eng Finding 4.1**：抽 `_with_observability(target_func, user_request, kind)` 包装函数，`_run_supervisor` 和 `_run_direct_worker` 都通过它调用，确保两条路径都有 trace_id：<br>```python\ndef _with_observability(target_func, user_request, kind):\n    new_trace(user_request)\n    metrics.new_trace_metrics(get_trace_id(), user_request)\n    final_status = "ok"\n    final_answer = ""\n    try:\n        result = target_func(make_run_config())\n        final_answer = result.get("final_answer") or ""\n        # Finding 4.6: confirm_retry 超限 → aborted\n        if not final_answer and kind == "supervisor":\n            final_status = "aborted"\n        return result\n    except BaseException:\n        final_status = "error"\n        raise\n    finally:\n        flush_metrics(get_trace_id(), status=final_status, final_answer_length=len(final_answer))\n        close_trace_writer()\n```<br>`make_run_config()` 由 observability 提供，返回 `{"callbacks": [ObservabilityCallback()], "configurable": {...}}` |
| `test_agents/config.py` | 新增 `TEST_AGENTS_LOG_LEVEL`(默认 `INFO`，含 `OFF` 总开关)、`TEST_AGENTS_LOG_DIR`(默认 `logs/`)、`TEST_AGENTS_LOG_TRACE_FILES`(默认 `true`)、`TEST_AGENTS_LOG_TRACES_KEEP`(默认 `1000`)、`TEST_AGENTS_LOG_RETAIN_DAYS`(默认 `30`)、`TEST_AGENTS_LOG_TRACE_HANDLES`(默认 `64`) |
| `test_agents/agents/supervisor.py` / `worker_base.py` | **0 处改动**。LangGraph callback 自动拦截每个节点 + 每次 `llm.invoke` |
| `test_agents/tools/base.py` 及全部子类 | **0 处改动**。LangGraph callback 自动拦截每次工具调用 |
| `test_agents/graph/builder.py` | **0 处改动**（Eng Finding 1.4：LangGraph 编译后的 graph 无默认 callback API，callback 只能通过 invoke 的 config 传） |

**confirm_plan interrupt 处理（Eng Finding 4.5）**：spec §3 声明"interrupt 不触发 on_chain_error"——但 `GraphInterrupt` 是 `Exception` 子类，依赖 LangGraph 引擎特殊处理。该声明必须由 `test_main_observability.py::test_interrupt_resume_no_spurious_error` 测试覆盖验证，不能仅靠 spec 声明。

## 7. trace_id / span_id 传递机制

- **`trace_id`**: `_with_observability` 入口 `new_trace(user_request)` 生成（格式 `tr_<8 字符 hex>`），存入 `trace_id_var: ContextVar[str]`。**整个生命周期由 main.py 入口包装函数单点控制**。confirm_plan interrupt 导致同一 trace 跨多次 `app.invoke` 时，由于 trace_id 存在 ContextVar，且 callback 每次 invoke 新建但 MetricsCollector 是全局 dict（**Eng Finding 4.7**），状态正确累积。
- **`span_id`**: 由 `ObservabilityCallback._spans: dict[UUID, str]` 在 enter 事件时生成并存入（Eng Finding 1.5）。`parent_span_id` 通过 `parent_run_id` 查同一个 dict 得到。**Spec 不再使用 `span_id_var: ContextVar`**。
- **生命周期所有权**：所有 dict 在 on_chain_end / on_chain_error / on_chat_model_end / on_llm_end / on_tool_end / on_tool_error / on_*_error 共 6 个出口都 `pop(run_id, None)`（Eng Finding 4.3）。`close_trace_writer()` 额外清理 `_last_node_per_trace[trace_id]`。
- **不支持嵌套 `new_trace`**（Eng Finding 1.6：当前架构下不存在该场景，spec 不为该假设场景留代码路径）。
- ContextVar 在 LangGraph 同步执行下天然安全。**不支持多线程并发执行**（CEO Finding 4.1）。

## 8. 日志格式（每条 JSON Line）

```json
{
  "ts": "2026-05-22T10:30:45.123Z",
  "level": "INFO",
  "logger": "test_agents.observability.callback",
  "trace_id": "tr_8a3f2c1d",
  "span_id": "sp_b21c4a90",
  "parent_span_id": "sp_a1f0e234",
  "event": "node.enter|node.exit|llm.call|tool.call|error|callback.failed",
  "node": "planner",
  "tool": "claude_cli",
  "duration_ms": 1234,
  "status": "ok|error",
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
- **序列化策略按事件源类型**（Eng Finding 2.3）：
  - `on_chain_start.inputs` (dict) → `json.dumps(inputs, default=str, ensure_ascii=False)[:200]`
  - `on_chat_model_start.messages` (list[BaseMessage]) → `" ".join(m.content for m in messages[0])[:200]`
  - `on_llm_start.prompts` (list[str]) → `prompts[0][:200] if prompts else ""`
  - `on_tool_start.input_str` (str) → `input_str[:200]`
- `error`：仅 status=error 时出现
- `tokens`：仅 LLM 事件且响应含 `usage_metadata` 时出现；缺失时字段缺省
- `parent_span_id`：根节点为 `null`
- `model`（Eng Finding outside-voice #9）：`serialized.get("kwargs", {}).get("model_name")` 或 `(serialized.get("id") or [None])[-1]`；缺失为 null
- `extra`（Eng Finding outside-voice #8）：自由字段，**单条 ≤256 字节**，超出由 ContextInjectFilter 截断并加 `___extra_truncated___: true` 标记
- 不可序列化对象 → `str(obj)` + 加 `___unserializable___: true` 标记（CEO Finding 2.1）

## 9. 四档日志级别 + 总开关

| 级别 | 节点 enter/exit | LLM 调用 | 工具调用 | state 快照 |
|---|---|---|---|---|
| **OFF**（CEO Finding 1.3） | `setup_logging` 不注册 Handler、不创建 MetricsCollector，`make_run_config()` 返回 `{"callbacks": [], "configurable": ...}` 不挂 callback。整套观测体系彻底失活 | — | — | — |
| **INFO**（默认） | ✓ + 摘要 | ✓ + tokens + 耗时 | ✓ + 摘要 + 耗时 | ✗ |
| **DEBUG** | ✓ + 摘要 | ✓ + prompt/response 全文(2KB) | ✓ + input/output 全文(2KB) | ✗ |
| **TRACE**（自定义级别=5） | ✓ + state 快照 | + state 快照 | 同 DEBUG | ✓（节点 enter/exit 时序列化 `SupervisorState` / `WorkerState`） |

`TRACE` 通过 `logging.addLevelName(5, "TRACE")` 注册。`OFF` 是 `setup_logging` 的早退分支，配合 `make_run_config()` 返回空 callbacks 保证 `TEST_AGENTS_LOG_LEVEL=OFF` 时整套体系零开销。

## 10. 文件布局

```
logs/
  app-2026-05-22.jsonl          # 主日志，按天滚动，默认保留 30 天
  app-2026-05-21.jsonl
  metrics.jsonl                  # 每次执行追加一行 summary（不滚动）
  traces/
    tr_8a3f2c1d.jsonl
    tr_9b4e1d22.jsonl
    ...
```

清理：

- **主日志**：`TimedRotatingFileHandler(when='midnight', backupCount=TEST_AGENTS_LOG_RETAIN_DAYS)`
- **per-trace 文件**：`setup_logging()` 启动时扫描 `traces/`，按 mtime 降序保留最新 `TEST_AGENTS_LOG_TRACES_KEEP`
- **per-trace writer 句柄**：LRU 容量 `TEST_AGENTS_LOG_TRACE_HANDLES`（默认 64），超出关最旧（CEO Finding 2.1）
- **metrics.jsonl**：不自动清理

## 11. metrics.jsonl 行格式

```json
{
  "trace_id": "tr_8a3f2c1d",
  "ts_start": "2026-05-22T10:30:45.123Z",
  "ts_end": "2026-05-22T10:31:12.456Z",
  "duration_ms": 27333,
  "user_request": "分析订单模块代码变更",
  "status": "ok|error|aborted",
  "node_count": 7,
  "llm_call_count": 5,
  "tool_call_count": 12,
  "replan_count": 0,
  "final_answer_length": 1024,
  "error": null
}
```

**status 三态**（Eng Finding 4.6）：
- `ok`：流程完成，有 final_answer
- `error`：异常抛出（包括 KeyboardInterrupt）
- `aborted`：流程完成但无 final_answer（confirm_retry 超限）

## 12. 错误处理原则

可观测系统的故障**绝不允许影响业务执行**。统一原则：

| 错误场景 | 处理策略 | 用户感知 |
|---|---|---|
| `setup_logging` 时 `logs/` 目录创建失败 | print warning to stderr，将所有 logger 设为 NoOp 后返回；业务正常运行 | stderr 一行警告 |
| `JsonlMultiHandler.emit` 写盘失败 | try/except OSError，降级 `sys.__stderr__`；不重抛 | stderr 偶发一行 |
| per-trace 文件句柄超过 LRU 上限 | 关闭最旧句柄，打开新句柄 | 无 |
| `ContextVar` 未 set | `.get(default=None)`，输出 `trace_id: null` | 无 |
| LogRecord 含不可序列化对象 | `str(obj)` + `___unserializable___: true` 标记 | 字段以 `<...>` 字符串形式出现 |
| `MetricsCollector.flush` 写失败 | 静默降级到 stderr | stderr 一行 |
| `ObservabilityCallback` 任意方法抛异常 | 内层 try/except 吞掉，写一条 `event: callback.failed` 日志，永不传播 | 无 |
| trace_id 为 None | 不写 per-trace 文件，主日志正常写 | 主日志 trace_id 字段为 null |

## 13. 测试策略

新增 `test_agents/tests/test_observability/` 目录：

- `test_context.py`：ContextVar 行为 —— set / get / 退出后 reset；多次 `new_trace` 行为
- `test_logger.py`（**Eng Finding 3.1 新增**）：`setup_logging` 幂等性、四个级别注册不同 handler/filter、启动失败降级（mock `os.makedirs` 抛 `OSError`）、OFF 早退路径
- `test_filters.py`：`ContextInjectFilter` 注入正确性；空上下文 emit；extra 截断
- `test_handlers.py`：`JsonlMultiHandler` 双写 —— 主日志一行、per-trace 一行；trace_id=None 时不写 per-trace；LRU 句柄上限触发关闭；不可序列化对象写入加标记
- `test_callback.py`（**Eng Finding 3.3 拆为 6 个明确子项**）：
  1. `test_filter_non_langgraph_chain`：on_chain_start 没有 `metadata.langgraph_node` 时 return
  2. `test_replan_inference`：reflect → planner 转移触发 `replan_count++`
  3. `test_serialization_three_kinds`：dict / list[BaseMessage] / str 三种事件源序列化结果符合 §8
  4. `test_callback_exception_not_propagating`：mock 内部抛错，业务正常完成，写入 `callback.failed`
  5. `test_tokens_extraction`：`response.usage_metadata` 存在和缺失两种场景
  6. `test_chat_model_event_paired_with_on_chat_model`：ChatOpenAI 触发 on_chat_model_*，断言 callback 处理
- `test_metrics.py`：MetricsCollector 全局 dict 行为 —— `new_trace_metrics`、`incr`、`flush` 删 dict 项；并发安全（单线程）；写失败降级
- `test_errors.py`：错误处理路径 —— 启动失败、emit 失败、序列化失败的降级行为
- `test_off_switch.py`：`TEST_AGENTS_LOG_LEVEL=OFF` → 不创建文件、`make_run_config()` 返回空 callbacks、业务 0 额外耗时
- `test_main_observability.py`（**Eng Finding 3.2 新增**）：
  1. `test_with_observability_supervisor_path`：成功调 _run_supervisor → metrics.jsonl 加一行 status=ok
  2. `test_with_observability_simple_worker_path`：成功调 _run_direct_worker → metrics.jsonl 加一行（**Finding 4.1 验证**）
  3. `test_with_observability_error`：mock 抛错 → flush(error) + raise + close_trace_writer 调用
  4. `test_with_observability_keyboard_interrupt`：mock KeyboardInterrupt → finally 仍 flush
  5. `test_with_observability_aborted`：mock 返回空 final_answer → status=aborted（**Finding 4.6 验证**）
  6. `test_interrupt_resume_no_spurious_error`：mock confirm_plan interrupt 然后 resume → callback 不记 `node.exit status=error`（**Finding 4.5 验证 §6 声明**）
  7. `test_metrics_persist_across_invokes`：confirm_resume 流程后 metrics 累加正确（**Finding 4.7 验证**）
- `test_integration_observability.py`：完整 mock pipeline，校验：
  - `traces/<trace_id>.jsonl` 存在且行数 ≥ 节点数 × 2
  - 事件按时间排序构成完整调用链（保留子图 wrapper span，**Finding 4.4 验证**）
  - `metrics.jsonl` 多出一行且字段齐全
  - `_spans` 和 `_last_node_per_trace` dict 在 trace 完成后无残留（**Finding 4.3 验证**）
- 性能验证（非自动化）：开 `DEBUG` 跑 10 次 mock pipeline，目测无明显卡顿、日志可读

## 14. 风险与权衡

- **ContextVar 与 LangGraph 兼容性**：当前 LangGraph 同步执行下安全；若未来切到异步，需补充 async 测试。**不支持多线程并发**
- **LangGraph callback 接口稳定性**：approach 依赖 callback 字段（如 `on_chain_start` 的 `metadata.langgraph_node`），LangGraph 大版本升级可能改接口。影响面集中在 `observability/callback.py` 一个文件
- **日志文件体积**：DEBUG 级开 claude_cli 全文记录可能单次执行 100KB+，靠 traces 目录数量上限 + 主日志按天切分 + 字符截断（2KB）三重控制
- **不脱敏**：本次明确不做
- **磁盘写入同步**：高频日志可能成为热点；当前 LLM 调用主导（百毫秒级），同步写盘不会成为瓶颈
- **`_spans` / `_last_node_per_trace` 是类级别 dict**：进程级共享，单线程安全；多进程场景需额外锁（当前 CLI 工具不存在该场景）

## 15. 日志查询 Cheatsheet

```bash
# 看某次执行的完整事件序列
cat logs/traces/tr_8a3f2c1d.jsonl | jq -r '"\(.ts) [\(.event)] \(.node // .tool // "")"'

# 今天最慢的 10 次节点执行
jq -r 'select(.event=="node.exit") | "\(.duration_ms) \(.node) \(.trace_id)"' \
  logs/app-$(date +%F).jsonl | sort -rn | head -10

# 今天每个节点的平均耗时
jq -r 'select(.event=="node.exit") | "\(.node) \(.duration_ms)"' logs/app-$(date +%F).jsonl \
  | awk '{sum[$1]+=$2; cnt[$1]++} END {for (k in sum) print k, sum[k]/cnt[k]"ms (n="cnt[k]")"}'

# 最近 100 次执行的 replan 率
tail -100 logs/metrics.jsonl | jq -s 'map(select(.replan_count>0)) | length'

# 最近 100 次执行的 aborted 率（confirm_retry 超限）
tail -100 logs/metrics.jsonl | jq -s 'map(select(.status=="aborted")) | length'

# 失败 trace 列表
jq 'select(.status=="error") | .trace_id' logs/metrics.jsonl

# token 用量 top
jq -r 'select(.event=="llm.call" and .phase=="end") | "\(.tokens.total // 0) \(.model) \(.trace_id)"' \
  logs/app-$(date +%F).jsonl | sort -rn | head -10
```

## 16. 非目标（YAGNI）

- 不做 Prometheus / OpenTelemetry 指标导出
- 不做实时 Web UI（如需可视化未来再加 LangFuse 自托管）
- 不做日志加密、不做脱敏
- 不做集中式日志收集（ELK / Loki）
- 不做告警 / 通知机制
- 不做异步 QueueHandler（CEO Finding 1.4）
- 不支持多线程并发执行（CEO Finding 4.1）
- 不在 build_graph 默认绑定 callback（Eng Finding 1.4）
- 不支持嵌套 new_trace（Eng Finding 1.6）
