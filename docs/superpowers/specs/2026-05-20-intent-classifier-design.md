<!-- /autoplan restore point: /home/hl/.gstack/projects/testagents/main-autoplan-restore-20260520-161301.md -->
# Intent Classifier 设计文档

## 背景

当前当用户输入与系统能力无关的请求（如"hello"）时，planner 会生成空 steps 的"无效计划"。系统仍继续走 `confirm_plan → dispatch → reflect → synthesize` 的完整流程，导致用户被询问"确认计划？"后才收到冗长的"未获得有效结果"消息。路径太长、体验不友好。

## 目标

在 LangGraph 主图的最前端增加意图分类能力，让无关或模糊请求在最早阶段得到友好回复，不再走完整的 plan-and-solve 流程。

## 架构与数据流

```
START → intent_classifier ──→ route_from_classifier ──→ relevant ──→ planner → confirm_plan → dispatch → ...
                              ↓
                        ambiguous / irrelevant ──→ reply_node ──→ END
```

### 数据流说明

1. `intent_classifier_node` 接收 `user_request`，调用 LLM 输出分类结果
2. 分类结果为 `relevant` / `ambiguous` / `irrelevant` 之一
3. 路由函数 `route_from_classifier` 根据分类结果分支：
   - `relevant` → 进入 `planner_node`
   - `ambiguous` / `irrelevant` → 进入 `reply_node`
4. `reply_node` 调用 LLM 生成友好回复，写入 `final_answer`，然后结束

## 节点设计

### `intent_classifier_node`

- **输入**：`state["user_request"]`
- **输出**：`{"intent_classification": "relevant", "intent_reason": "..."}`

实现逻辑：
1. 使用 `load_prompt("intent_classifier", user_request=user_request)` 生成 prompt
2. 调用 LLM，期望返回 JSON：`{"classification": "relevant", "reason": "..."}`
3. 解析失败时默认 `classification = "ambiguous"`，reason 为解析错误提示

### `reply_node`

- **输入**：`state["user_request"]`, `state["intent_classification"]`, `state["intent_reason"]`
- **输出**：`{"final_answer": "..."}`

实现逻辑：
1. 使用 `load_prompt("reply", user_request=..., classification=..., reason=...)` 生成 prompt
2. 调用 LLM 生成一段自然、友好的回复
3. 回复写入 `final_answer`

## 路由函数

```python
def route_from_classifier(state: SupervisorState) -> Literal["planner", "reply"]:
    classification = state.get("intent_classification", "")
    if classification == "relevant":
        return "planner"
    return "reply"
```

## 状态变更

`SupervisorState` 新增两个字段：

```python
class SupervisorState(TypedDict):
    # ... 现有字段 ...
    intent_classification: str  # "relevant" | "ambiguous" | "irrelevant"
    intent_reason: str          # 分类理由
```

默认值为空字符串，不影响现有流程。

## Prompt 文件

| 文件 | 用途 |
|---|---|
| `test_agents/prompts/intent_classifier.md` | 意图分类 prompt |
| `test_agents/prompts/reply.md` | 回复生成 prompt |

### `intent_classifier.md` 核心内容

- 说明系统能力范围：分析代码变更、评审测试用例
- 定义三分类规则：
  - `relevant`：明确提到代码分析、代码变更、git diff、测试用例评审
  - `ambiguous`：提到"测试""看看代码"但不明确具体需求
  - `irrelevant`：打招呼、闲聊、天气、与代码/测试完全无关
- 输出 JSON 格式：`{"classification": "...", "reason": "..."}`

### `reply.md` 核心内容

- `irrelevant`：礼貌说明系统能力范围，举例可用请求格式
- `ambiguous`：说明理解到用户可能有相关需求，但信息不足，请补充具体模块名/commit/用例

## 图结构变更

在 `test_agents/graph/builder.py` 中：

```python
graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("reply", reply_node)
graph.set_entry_point("intent_classifier")
graph.add_conditional_edges("intent_classifier", route_from_classifier)
graph.add_edge("reply", END)
```

## 错误处理

| 场景 | 行为 |
|---|---|
| LLM 返回非 JSON | 默认 `classification = "ambiguous"`，reply_node 生成引导消息 |
| JSON 缺少 `classification` 字段 | 同上 |
| LLM 调用失败（网络/超时） | 捕获异常，默认 `classification = "ambiguous"`，不中断流程 |

## 测试策略

1. **单元测试 `intent_classifier_node`**：
   - Mock LLM 返回三分类结果，验证输出
   - Mock LLM 返回非法 JSON，验证降级到 `ambiguous`
   - Mock LLM 抛出异常，验证不崩溃

2. **单元测试 `reply_node`**：
   - 验证 `irrelevant` 时生成友好拒绝消息
   - 验证 `ambiguous` 时生成引导补充消息
   - 验证输出写入 `final_answer`

3. **集成测试**：
   - 端到端输入"hello"，验证直接输出友好回复，不经过 planner
   - 端到端输入明确需求，验证仍走完整流程

## 变更文件清单

| 文件路径 | 操作 | 变更内容 |
|---|---|---|
| `test_agents/prompts/intent_classifier.md` | 新增 | 意图分类 Prompt 模板，定义三分类规则（relevant/ambiguous/irrelevant）和 JSON 输出格式 |
| `test_agents/prompts/reply.md` | 新增 | 回复生成 Prompt 模板，根据分类结果生成友好回复 |
| `test_agents/graph/state.py` | 修改 | `SupervisorState` 新增 `intent_classification`（str）和 `intent_reason`（str）两个字段 |
| `test_agents/agents/supervisor.py` | 修改 | 新增 `intent_classifier_node`、`reply_node`、`route_from_classifier` 三个函数 |
| `test_agents/graph/builder.py` | 修改 | 图结构变更：START → intent_classifier → (route) → planner/reply → END |
| `test_agents/main.py` | 修改 | `_build_initial_state` 新增 `intent_classification` 和 `intent_reason` 初始值（空字符串） |
| `test_agents/tests/test_supervisor.py` | 修改 | 新增 `TestIntentClassifierNode`、`TestReplyNode`、`TestRouteFromClassifier` 测试类 |
| `test_agents/tests/test_integration.py` | 修改 | 新增 irrelevant/ambiguous 请求的端到端测试，以及 relevant 请求的完整流程回归测试 |

---

## /autoplan 审查报告

### 审查状态
- **CEO 审查**：已完成，发现 planner 已能识别空步骤，建议短路路由作为替代方案
- **用户决策**：选择 A — 坚持原方案（添加 intent_classifier_node）
- **Design 审查**：跳过（无 UI scope）
- **Eng 审查**：已完成（见下方）
- **DX 审查**：已完成（见下方）
- **Codex 双声音**：不可用（codex CLI 未安装）
- **Claude 子代理 CEO 声音**：已完成

### Phase 1: CEO Review 结论

**前提确认**：用户坚持原方案。

**发现的问题**：
1. `main.py` 中的 `_SINGLE_AGENT_KEYWORDS` 关键字匹配器与新的 LLM 分类器存在职责重叠。某些请求（如"分析代码变更"）会在 `main.py` 层被直接路由到 worker，永远不会到达 intent_classifier。
2. `ambiguous` 分类只能生成静态回复，系统不支持多轮澄清对话。
3. 每请求增加一次 LLM 调用，成本和延迟上升。

**建议**：
- 在文档中明确分类器和关键字匹配器的职责边界
- 考虑未来统一入口路由层

### Phase 3: Eng Review 结论

**架构分析**：
- 新增节点与现有图结构兼容，使用相同模式（get_llm + load_prompt + _strip_markdown_json）
- `SupervisorState` 新增两个字段，默认空字符串不影响现有流程
- 路由逻辑简单明确：`relevant` → planner，其他 → reply

**错误处理评估**：
| 场景 | 处理 | 评价 |
|---|---|---|
| LLM 返回非 JSON | 默认 ambiguous | 合理，不中断流程 |
| JSON 缺少字段 | 默认 ambiguous | 合理 |
| LLM 调用异常 | 捕获 Exception | 合理，但捕获范围过宽（应区分网络/超时/内容错误）|
| 非法 classification 值 | 默认 ambiguous | 合理（计划中已处理）|

**测试评估**：
- 单元测试覆盖三分类、非法 JSON、LLM 异常 — 完整
- 集成测试覆盖 e2e 流程 — 需要验证 mock side_effect 顺序与图中 LLM 调用次数匹配
- 缺少对 `reply_node` 在 LLM 异常时的测试（当前 reply_node 未捕获异常）

**代码质量**：
- 与现有代码风格一致
- `intent_classifier_node` 和 `reply_node` 命名清晰
- `route_from_classifier` 使用 `Literal` 类型注解，符合现有路由函数模式

**未覆盖的边界**：
1. `reply_node` 未处理 LLM 调用异常 — 如果 reply LLM 失败，整个流程会崩溃
2. `intent_classification` 和 `intent_reason` 在 `total=False` 的 TypedDict 中，但代码使用 `.get()` 访问，安全

### Phase 3.5: DX Review 结论

**开发者体验影响**：
- 正面：无关请求不再走完整流程，CLI 交互更友好
- 负面：main.py 中的 direct worker 调用和图中的分类器可能产生不一致的行为

**TTHW（首次使用体验）**：
- 未改变，仍需要 OPENAI_API_KEY 等配置
- 用户仍需要理解"什么样的请求会被分类为 relevant"

**API/CLI 一致性**：
- `run_test_agents()` 行为变化：某些请求现在提前返回 final_answer
- 需要确保 `--output json` 模式对提前返回的结果也正常工作

### 跨阶段主题

**主题 1：与 main.py 关键字匹配器的冲突**
- CEO 和 Eng 阶段均独立发现此问题
- 高置信度信号：需要文档或代码明确两者的优先级

### 决策审计追踪

| # | 阶段 | 决策 | 分类 | 原则 | 理由 | 被拒绝的替代方案 |
|---|------|------|------|------|------|----------------|
| 1 | CEO | 用户坚持原方案，保留 intent_classifier_node | 用户选择 | P6 偏向行动 | 用户明确选择 A | planner 短路方案（B）和混合方案（C）|
| 2 | Eng | 接受当前错误处理模式（catch Exception） | 机械 | P3 务实 | 现有代码也使用 catch Exception，保持一致性 | 改为区分具体异常类型 |
| 3 | Eng | 接受 reply_node 不捕获 LLM 异常 | 口味 | P1 完整性 | 计划中未指定，现有节点也有未捕获异常的情况 | 添加 try/except |
| 4 | DX | 不修改 main.py 关键字匹配器 | 机械 | P4 DRY | 超出当前计划范围，已记录到 TODOS | 统一入口层 |

### 推迟到 TODOS

1. **统一入口路由层**：整合 `main.py` 的 `_SINGLE_AGENT_KEYWORDS` 和 `intent_classifier_node`，避免职责重叠
2. **reply_node 异常处理**：为 `reply_node` 添加 LLM 调用失败的降级策略
3. **ambiguous 多轮澄清**：考虑支持用户在收到 ambiguous 回复后继续补充信息
