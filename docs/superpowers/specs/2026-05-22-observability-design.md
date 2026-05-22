# Test Agents 自建可观测体系设计

**日期**: 2026-05-22
**方案**: 标准库 logging + ContextVar + JSON Lines + LangGraph callback（纯自建、内网友好、零新增依赖）
**取代**: 本设计在内网场景下取代 `2026-05-20-langgraph-tracing-design.md`（LangSmith + Postgres 方案）。该旧方案因数据出网约束被搁置。
**评审**: 2026-05-22 CEO 评审（HOLD SCOPE），结论纳入本版本

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
- **`langchain_core.callbacks.BaseCallbackHandler`**（LangGraph 自带的事件拦截机制，无需新增依赖）
- JSON Lines 文件输出
- 无任何新增 `requirements.txt` 条目

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ main.py: run_test_agents(user_request)                               │
│   ├─ setup_logging()                  ← 模块导入时一次               │
│   ├─ trace_token = new_trace(...)     ← 生成 trace_id 写入 CtxVar    │
│   ├─ try: app.invoke(state, config={                                 │
│   │       "callbacks": [ObservabilityCallback()],  ← 自动拦截入口    │
│   │       "configurable": {"thread_id": ...}})                       │
│   └─ finally: flush_metrics(); close_trace_writer()                  │
└──────────────────────┬──────────────────────────────────────────────┘
                       ↓
         LangGraph 引擎执行（自动触发 callback）
                       ↓
   ObservabilityCallback (BaseCallbackHandler 子类)
   ├─ on_chain_start  → node.enter
   ├─ on_chain_end    → node.exit + duration_ms
   ├─ on_chain_error  → node.exit + status=error
   ├─ on_llm_start    → llm.call start
   ├─ on_llm_end      → llm.call + tokens + duration_ms
   ├─ on_tool_start   → tool.call start
   └─ on_tool_end     → tool.call + duration_ms
                       ↓
   logging.getLogger("test_agents") ← Filter 自动注入 trace_id/span_id
                       ↓
   JsonlMultiHandler
   ├─ TimedRotatingFileHandler → logs/app-YYYY-MM-DD.jsonl
   └─ per-trace writer (LRU) → logs/traces/<trace_id>.jsonl
                       ↓
   trace 结束：flush_metrics() → logs/metrics.jsonl 追加一行
```

**Approach 选型说明（CEO 评审 D1）**：选 callback 为主 + 装饰器为辅的混合方案。
节点 / LLM / 工具事件全部走 LangGraph callback 自动拦截，业务代码改动 0；
trace 生命周期与 metrics 聚合走 main.py 的 try/finally 手动控制。

## 4. 新增模块

新建 `test_agents/observability/` 包，按职责拆分为以下文件：

| 文件 | 职责 |
|---|---|
| `observability/__init__.py` | 包入口，导出公共 API：`setup_logging`、`new_trace`、`flush_metrics`、`close_trace_writer`、`ObservabilityCallback` |
| `observability/context.py` | 定义 `trace_id_var`、`span_id_var`（`ContextVar`）；工具函数 `new_trace(user_request)` 生成 trace_id 并写入 ContextVar、`get_trace_id()` / `get_span_id()`（默认值 None） |
| `observability/logger.py` | `setup_logging()` 入口：根据 `TEST_AGENTS_LOG_LEVEL` 注册 Filter 和 Handler；定义自定义级别 `TRACE=5` 和 `OFF`（含义见 §8） |
| `observability/filters.py` | `ContextInjectFilter`：在 `filter(record)` 中从 ContextVar 读取 trace_id / span_id 注入到 `LogRecord`，未 set 时注入 None |
| `observability/handlers.py` | `JsonlMultiHandler(logging.Handler)`：emit 时序列化 LogRecord → JSON，同时分发到：① 主日志通过 `TimedRotatingFileHandler` 按天滚动写 `app-YYYY-MM-DD.jsonl`；② per-trace 文件按 `record.trace_id` 路由到 `traces/<trace_id>.jsonl`，**LRU 缓存最多 64 个文件句柄**（超出时关闭最久未访问的），`trace_id` 为 None 时**不写 per-trace 文件**；③ 序列化遇到不可序列化对象时使用 `str(obj)` 并加 `___unserializable___` 标记，永不抛 TypeError 中断业务 |
| `observability/callback.py` | `ObservabilityCallback(BaseCallbackHandler)`：实现 `on_chain_start/end/error`、`on_llm_start/end/error`、`on_tool_start/end/error`。**所有回调方法都包 try/except**，吞掉自身异常仅写一条 logger.warning("callback failed", exc_info=True)，**绝不向 LangGraph 传播**。span_id 在 enter 时生成并 push 到 ContextVar，exit 时 reset |
| `observability/metrics.py` | `MetricsCollector`：每个 trace 维护一份累计计数（node_count / llm_call_count / tool_call_count / replan_count / ts_start / status）；`flush_metrics(status, final_answer_length=None)` 追加一行到 `metrics.jsonl`，写失败静默降级到 stderr |

## 5. 数据流改造点

approach C 让业务代码改动量降到最小：

| 改造点 | 改动说明 |
|---|---|
| `test_agents/main.py` | 模块导入后调用 `setup_logging()`；`run_test_agents(user_request)` 入口生成 trace 并在 `try/finally` 中保证 flush：<br>```python\ntrace_token = new_trace(user_request)\ntry:\n    result = app.invoke(state, config={\n        "callbacks": [ObservabilityCallback()],\n        "configurable": {"thread_id": ...},\n    })\n    flush_metrics(status="ok", final_answer_length=len(result.get("final_answer", "")))\n    return result\nexcept BaseException:\n    flush_metrics(status="error")\n    raise\nfinally:\n    close_trace_writer()\n``` |
| `test_agents/config.py` | 新增 `TEST_AGENTS_LOG_LEVEL`(默认 `INFO`，新增 `OFF` 总开关)、`TEST_AGENTS_LOG_DIR`(默认 `logs/`)、`TEST_AGENTS_LOG_TRACE_FILES`(默认 `true`)、`TEST_AGENTS_LOG_TRACES_KEEP`(默认 `1000`)、`TEST_AGENTS_LOG_RETAIN_DAYS`(默认 `30`)、`TEST_AGENTS_LOG_TRACE_HANDLES`(默认 `64`，per-trace writer LRU 容量) |
| `test_agents/agents/supervisor.py` / `worker_base.py` | **0 处改动**。LangGraph callback 自动拦截每个节点的 enter/exit 和每次 `llm.invoke` |
| `test_agents/tools/base.py` 及全部子类 | **0 处改动**。LangGraph callback 自动拦截每次工具调用 |
| `test_agents/graph/builder.py` | 可选：在 `build_graph()` 末尾把 `ObservabilityCallback()` 作为默认 callback 注册到编译后的 app（让任何调用方都自动启用，无需在 main.py 重复传） |

**confirm_plan interrupt 不需要特殊处理**：因为 callback 由 LangGraph 引擎调度，引擎在 interrupt 时不会触发 `on_chain_error`，自然不会把 interrupt 误记为错误。

## 6. trace_id / span_id 传递机制

- **`trace_id`**: main.py 入口 `new_trace(user_request)` 生成（格式 `tr_<8 字符 hex>`），存入 `trace_id_var: ContextVar[str]`。**整个生命周期由 main.py 的 try/finally 单点控制**：进入时创建，退出时 `close_trace_writer()` 释放对应 per-trace 文件句柄。confirm_plan interrupt 导致同一 trace 跨多次 `app.invoke` 时，由于 main.py 只在 `run_test_agents` 入口/退出处控制 trace 生命周期，中间多次 invoke 共享同一个 trace_id，per-trace 文件持续追加。
- **`span_id`**: 由 `ObservabilityCallback` 在 enter 事件时生成（格式 `sp_<8 字符 hex>`），push 到 `span_id_var`；exit 时 reset。`parent_span_id` 通过 LangGraph 传递的 `parent_run_id` 推导。
- **生命周期所有权（CEO 评审 Finding 1.1）**：per-trace writer 的打开/关闭仅由 `new_trace` 和 `close_trace_writer` 控制，callback 中**只读不写** trace 生命周期。这避免了"callback 没有 trace 结束事件"的歧义问题。
- ContextVar 在 LangGraph 同步执行下天然安全；若未来切到 async，`asyncio.Task` 创建时会自动复制 ContextVar 快照，仍然安全。**当前不支持多线程并发执行**（CEO 评审 Finding 4.1）。

## 7. 日志格式（每条 JSON Line）

```json
{
  "ts": "2026-05-22T10:30:45.123Z",
  "level": "INFO",
  "logger": "test_agents.supervisor",
  "trace_id": "tr_8a3f2c1d",
  "span_id": "sp_b21c4a90",
  "parent_span_id": "sp_a1f0e234",
  "event": "node.enter" | "node.exit" | "llm.call" | "tool.call" | "error" | "callback.failed",
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
- `tokens`：仅 LLM 事件且 LangChain 响应包含 `usage_metadata` 时出现；缺失时字段缺省
- `parent_span_id`：根节点为 `null`
- **序列化遇到不可序列化对象**（CEO 评审 Finding 2.1）：使用 `str(obj)`，附加 `___unserializable___: true` 标记，永不抛 TypeError

## 8. 四档日志级别 + 总开关

| 级别 | 节点 enter/exit | LLM 调用 | 工具调用 | state 快照 |
|---|---|---|---|---|
| **OFF**（CEO 评审 Finding 1.3 新增） | `setup_logging` 不注册 Handler、不挂 callback、不创建 MetricsCollector。整套观测体系彻底失活 | — | — | — |
| **INFO**（默认） | ✓ + 摘要 | ✓ + tokens + 耗时 | ✓ + 摘要 + 耗时 | ✗ |
| **DEBUG** | ✓ + 摘要 | ✓ + prompt/response 全文(2KB) | ✓ + input/output 全文(2KB) | ✗ |
| **TRACE**（自定义级别=5） | ✓ + state 快照 | + state 快照 | 同 DEBUG | ✓（节点 enter/exit 时序列化 `SupervisorState` / `WorkerState`） |

`TRACE` 级别通过 `logging.addLevelName(5, "TRACE")` 注册，并在 `logger.py` 暴露 `log.trace(msg, ...)` 便捷方法。`OFF` 是 `setup_logging` 的早退分支，配合容错保证 `TEST_AGENTS_LOG_LEVEL=OFF` 时整套体系零开销且不可能引起任何业务影响。

## 9. 文件布局

```
logs/
  app-2026-05-22.jsonl          # 主日志，按天滚动，默认保留 30 天
  app-2026-05-21.jsonl
  metrics.jsonl                  # 每次执行追加一行 summary（不滚动）
  traces/
    tr_8a3f2c1d.jsonl            # 单次执行的全部日志
    tr_9b4e1d22.jsonl
    ...
```

清理策略：

- **主日志**：`TimedRotatingFileHandler(when='midnight', backupCount=TEST_AGENTS_LOG_RETAIN_DAYS)`
- **per-trace 文件**：`setup_logging()` 启动时扫描 `traces/`，按 mtime 降序保留最新 `TEST_AGENTS_LOG_TRACES_KEEP` 个文件，多余的删除
- **per-trace writer 句柄**（CEO 评审 Finding 2.1）：内存中维护 LRU，容量 `TEST_AGENTS_LOG_TRACE_HANDLES`（默认 64），超出时关闭最久未访问的句柄；防止长跑后撞 ulimit
- **metrics.jsonl**：不自动清理，运维自行处理

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

## 11. 错误处理原则（CEO 评审 Finding 1.2 + 2.1 + 4.1）

可观测系统的故障**绝不允许影响业务执行**。统一原则：

| 错误场景 | 处理策略 | 用户感知 |
|---|---|---|
| `setup_logging` 时 `logs/` 目录创建失败 | 打印 warning 到 stderr，将所有 logger 设为 NoOp 状态后返回；业务正常运行 | stderr 一行警告 |
| `JsonlMultiHandler.emit` 写盘失败 | try/except OSError，降级写 sys.\_\_stderr\_\_；不重抛 | stderr 偶发一行 |
| per-trace 文件句柄超过 LRU 上限 | 关闭最旧的句柄，打开新句柄 | 无 |
| `ContextVar` 未 set | `.get(default=None)`，输出 `trace_id: null` | 无 |
| LogRecord 含不可序列化对象 | `str(obj)` + 加 `___unserializable___: true` 标记 | 字段以 `<...>` 字符串形式出现 |
| `MetricsCollector.flush` 写失败 | 静默降级到 stderr | stderr 一行 |
| `ObservabilityCallback` 任意方法抛异常 | 内层 try/except 吞掉，写一条 `event: callback.failed` 日志（如果可能），永不传播到 LangGraph | 无 |
| trace_id 为 None | 不写 per-trace 文件，主日志正常写 | 主日志 trace_id 字段为 null |
| 重入 `new_trace`（嵌套调用） | 警告日志，复用现有 trace_id | 警告 + 同一 trace |

## 12. 测试策略

新增 `test_agents/tests/test_observability/` 目录：

- `test_context.py`：ContextVar 行为 —— 嵌套 span、父子继承、跨函数调用、退出后 reset 正确
- `test_filters.py`：`ContextInjectFilter` 注入正确性，空上下文时也能 emit
- `test_handlers.py`：`JsonlMultiHandler` 双写 —— 主日志一行、per-trace 一行；trace_id=None 时不写 per-trace（**Finding 6.1**）；LRU 句柄上限触发关闭（**Finding 6.1**）；不可序列化对象写入加标记（**Finding 6.1**）
- `test_callback.py`：`ObservabilityCallback` 行为 —— enter/exit 配对、span 父子关系、tokens 提取；**callback 内部异常被吞掉不传播**（**Finding 6.1**）
- `test_metrics.py`：`MetricsCollector` —— 累计正确、flush 后 metrics.jsonl 多一行、status 在异常时为 error
- `test_errors.py`（**Finding 6.1 新增**）：错误处理路径 —— 启动时 `logs/` 创建失败的降级行为；emit 写盘失败的降级；JsonlSerializer 遇 lambda/socket 等对象的标记
- `test_off_switch.py`（**Finding 6.1 新增**）：`TEST_AGENTS_LOG_LEVEL=OFF` 时验证：① 不创建任何文件；② 不挂 callback；③ 业务调用 0 额外耗时
- `test_integration_observability.py`：跑一次完整 mock pipeline，校验：
  - `traces/<trace_id>.jsonl` 存在且行数 ≥ 节点数 × 2
  - 所有事件按时间排序构成合理调用链
  - `metrics.jsonl` 多出一行且字段齐全
  - **confirm_plan interrupt 恢复后日志在同一 trace 文件**（**Finding 6.1**）
- 性能验证（非自动化）：开 `DEBUG` 跑 10 次 mock pipeline，目测无明显卡顿、日志文件可读

## 13. 风险与权衡

- **ContextVar 与 LangGraph 兼容性**：当前 LangGraph 同步执行下安全；若未来切到异步，需补充 async 测试覆盖。**不支持多线程并发**，spec 明确声明。
- **LangGraph callback 接口稳定性**：approach C 依赖 callback 字段（如 `on_chain_start` 的 metadata 结构），若 LangGraph 大版本升级改了接口需要适配。影响面集中在 `observability/callback.py` 一个文件。
- **日志文件体积**：DEBUG 级开 claude_cli 全文记录可能单次执行 100KB+，靠 traces 目录数量上限 + 主日志按天切分 + 字符截断（2KB）三重控制
- **不脱敏**：本次明确不做脱敏，未来若要把日志拷出内网分析，需评估二次处理流程
- **磁盘写入是同步的**：高频日志可能成为热点，目前 LangGraph 执行节奏受 LLM 调用主导（百毫秒级），同步写盘不会成为瓶颈；如未来需要再考虑 `QueueHandler` 异步化（CEO 评审 Finding 1.4 选择当前接受）

## 14. 日志查询 Cheatsheet（CEO 评审 Finding 8.1）

落地后常见排查模式（前提：装 `jq`）：

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

# 最近 100 次执行的失败率
tail -100 logs/metrics.jsonl | jq -s 'map(select(.status=="error")) | length'

# 看某个工具今天所有调用的入参出参摘要
jq -r 'select(.event=="tool.call" and .tool=="claude_cli") | "\(.ts) \(.input_summary) -> \(.output_summary)"' \
  logs/app-$(date +%F).jsonl | head

# token 用量 top
jq -r 'select(.event=="llm.call") | "\(.tokens.total // 0) \(.model) \(.trace_id)"' \
  logs/app-$(date +%F).jsonl | sort -rn | head -10
```

## 15. 非目标（YAGNI）

- 不做 Prometheus / OpenTelemetry 指标导出
- 不做实时 Web UI（如需可视化未来再加 LangFuse 自托管）
- 不做日志加密、不做脱敏
- 不做集中式日志收集（ELK / Loki）
- 不做告警 / 通知机制
- 不做异步 QueueHandler（CEO 评审 Finding 1.4）
- 不支持多线程并发执行（CEO 评审 Finding 4.1）
