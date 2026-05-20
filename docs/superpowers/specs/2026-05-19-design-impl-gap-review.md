# 设计文档与代码实现差距审查报告

**审查日期**: 2026-05-19
**审查对象**: `docs/superpowers/specs/2026-05-15-test-agents-design.md` vs 当前代码实现
**审查范围**: `test_agents/` 全量代码（含 agents、graph、tools、prompts、tests）

---

## 一、架构层面不匹配（严重）

### D1. Worker 子图未作为主图节点注册

| 项目 | 内容 |
|------|------|
| **设计** | `supervisor_graph.add_node("code_analyzer", code_analyzer_graph)` — Worker 子图直接注册为主图节点 |
| **实现** | `graph.add_node("code_analyzer", code_analyzer_wrapper)` — 注册的是 wrapper 函数 |
| **位置** | `test_agents/graph/builder.py:48` |
| **影响** | LangGraph 无法原生追踪子图内部状态（agent→tools→reflect 循环对外部不可见），与设计文档§4.7、§5.1 的架构范式不符 |
| **建议** | 保留 wrapper 作为状态转换层，但将 wrapper 内部改为调用 `CompiledGraph.invoke()`，并在 builder 中让 wrapper 函数本身作为节点；或重构为子图直接挂载（需调整 State 映射方式） |

---

### D2. SupervisorState 残留已废弃字段

| 项目 | 内容 |
|------|------|
| **设计** | `SupervisorState` 中仅保留 `outputs`，移除 `code_change_report`、`review_results` 等固定字段 |
| **实现** | `code_change_report: str` 和 `review_results: list[dict]` 仍存在于 TypedDict 中 |
| **位置** | `test_agents/graph/state.py:73-74` |
| **影响** | 新旧机制并存，`main.py` 仍初始化这两个字段，可能导致数据不一致 |
| **建议** | 删除这两个字段，确保所有 Worker 结果统一写入 `outputs[output_key]` |

---

### D3. 直接调用 Worker 模式未实现

| 项目 | 内容 |
|------|------|
| **设计** | `main.py` 中直接 `worker_app.invoke(worker_input)` 调用 Worker 子图 |
| **实现** | `is_simple_request()` 只返回 agent 名称，但 `run_test_agents` 中没有任何直接调用 Worker 的逻辑 |
| **位置** | `test_agents/main.py:19-30` |
| **影响** | 所有请求（包括简单请求）都走完整的 Supervisor 主图，增加不必要的 planner+confirm+reflect 开销 |
| **建议** | 在 `run_test_agents` 中添加分支：若 `is_simple_request` 返回 agent 名，直接构建 `WorkerState` 调用对应 Worker 子图，结果写入 `outputs` 后直接返回 |

---

### D4. dispatch 节点职责严重缩水

| 项目 | 内容 |
|------|------|
| **设计** | dispatch 节点负责双向映射：构建 WorkerState 输入、子图执行完后从 WorkerState.result 取结果写入主图 `outputs[output_key]` |
| **实现** | `dispatch_node` 返回空字典，所有状态映射逻辑散落在 `code_analyzer_wrapper` 和 `case_reviewer_wrapper` 中 |
| **位置** | `test_agents/agents/supervisor.py:67-69` |
| **影响** | 设计文档§4.3 描述的 dispatch 核心职责未落实，状态映射逻辑重复且分散 |
| **建议** | 方式一：将 `_resolve_input`、WorkerState 构建、结果回写统一收归 dispatch；方式二：接受当前 wrapper 模式，但将公共逻辑提取到 worker_base |

---

## 二、功能缺失（中等）

### F1. save_experience 缺少 LLM 去重

| 项目 | 内容 |
|------|------|
| **设计** | LLM 生成经验摘要 → 写入文件 → 去重：LLM 判断新经验是否与已有经验语义重复 |
| **实现** | 直接格式化追加，无去重逻辑，无 LLM 摘要生成 |
| **位置** | `test_agents/agents/supervisor.py:154-187` |
| **建议** | 追加前读取现有经验，调用 LLM 判断语义重复；或改用结构化存储（JSONL）便于去重 |

---

### F2. input_mapping 多 key 拼接未实现

| 项目 | 内容 |
|------|------|
| **设计** | 多 key 拼接语法：`"${outputs.report_a}\n${outputs.report_b}"` |
| **实现** | `_resolve_input` 不支持字符串内多个 `${...}` 引用拼接 |
| **位置** | `test_agents/agents/code_analyzer.py:22-36`、`case_reviewer.py:22-36` |
| **建议** | 使用正则 `re.finditer(r'\$\{([^}]+)\}', value)` 循环替换所有占位符 |

---

### F3. worker_reflect 缺少结果回写

| 项目 | 内容 |
|------|------|
| **设计** | reflect 评估后，agent 重试产生的新内容应更新 `result` |
| **实现** | reflect 只返回 `error` 和 `messages`，`result` 字段未被更新 |
| **位置** | `test_agents/agents/worker_base.py:21-65` |
| **影响** | 如果 agent 在重试后产生新内容，wrapper 从 `WorkerState.result` 读取时仍是旧值 |
| **建议** | reflect 节点在 `error == "no"` 时，从 messages 中提取最新 agent 输出并更新 `result` |

---


---

## 四、代码质量优化

### Q1. `_resolve_input` 重复定义

- `code_analyzer.py:22` 和 `case_reviewer.py:22` 有完全相同的函数
- **建议**：提取到 `test_agents/agents/worker_base.py` 作为公共函数

---

### Q2. `case_reviewer_wrapper` JSON 解析过于脆弱

- `case_reviewer.py:89-101` 使用字符串 split 提取 JSON，容易因 markdown 格式变化而失败
- **建议**：使用正则 `re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)` 或尝试直接 `json.loads`

---

### Q3. `save_experience_node` 无并发保护

- 多线程/多进程场景下同时追加 `reflection_experience.md` 可能产生内容交错
- **建议**：追加写入时使用文件锁（`fcntl` / `portalocker`）或改用独立进程队列

---

### Q4. planner prompt 示例语法不一致

- `planner.md:71` 示例中 `"${outputs.code_change_report}"` 与正文描述的 `"${code_change_report}"` 并存
- `_resolve_input` 同时兼容两种语法（`path.startswith("outputs.")` 和直接字段名）
- **建议**：统一使用 `${outputs.xxx}` 语法，移除旧语法的兼容代码

---

## 五、测试覆盖缺口

### T1. Worker 子图内部循环未测试

- `test_integration.py` 和 `test_workers.py` 全部 mock wrapper，未测试 agent→tools→reflect 的完整循环
- **建议**：添加不 mock wrapper 的集成测试，验证 ToolNode 调用和 reflect 重试逻辑

---

### T2. 直接调用 Worker 模式无测试

- 设计文档§5.4 中的直接调用模式没有对应测试
- **建议**：为 `is_simple_request` 和直接 Worker 调用分支添加测试

---

### T3. `_resolve_input` 拼接语法未测试

- `test_integration.py::test_resolve_input` 只测试单 key 引用
- **建议**：补充多 key 拼接和嵌套引用的测试用例

---

## 六、修复优先级建议

| 优先级 | 问题编号 | 说明 |
|--------|----------|------|
| P0 | D1, D2 | 架构核心不匹配，影响图追踪和状态一致性 |
| P1 | D3, D4 | 功能缺失，影响使用体验和代码组织 |
| P2 | F1, F2, F3 | 功能不完整，但不阻塞主流程 |
| P3 | C1, C2, Q1-Q4, T1-T3 | 配置/质量/测试，可逐步修复 |

---

*本报告由 `/review` 技能生成，基于 `2026-05-15-test-agents-design.md` 设计文档与 `main` 分支代码实现对比。*
