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
