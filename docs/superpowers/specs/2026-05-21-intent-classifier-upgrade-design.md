# Intent Classifier 升级为意图解析器 — 设计文档

## 背景

当前 `intent_classifier_node` 存在**信息断层**问题：

1. LLM 在分类时已经理解了用户意图（模块名、commit 范围、操作类型），但理解成果被丢弃
2. 只输出粗分类标签（`relevant`/`ambiguous`/`irrelevant`）和一句话理由
3. 下游 `planner_node` 拿到原始 `user_request`，需要从零重新做完整的意图解析
4. 两次 LLM 调用（intent_classifier + planner）在做同一件事：理解用户想要什么

## 目标

将 intent_classifier 从"纯分类器"升级为"分类 + 结构化提取"，让 `relevant` 请求的意图解析结果直接复用给 planner，消除信息断层。

## 设计原则

1. **最小化 LLM 输出复杂度** — 仅 `relevant` 时输出 `extracted`，ambiguous/irrelevant 时 `extracted = null`
2. **最大化降级安全性** — `extracted` 解析失败时 `intent_analysis = None`，planner 回退到原始行为
3. **辅助参考，非强制依赖** — `intent_analysis` 是 planner 的辅助输入，不是前置条件
4. **图结构和路由不变** — `START → intent_classifier → [planner | reply]`，`route_from_classifier` 逻辑不变

## 架构与数据流

```
START → intent_classifier ──→ route_from_classifier ──→ relevant ──→ planner → confirm_plan → dispatch → ...
                              ↓                              ↓
                        ambiguous / irrelevant          intent_analysis 写入 state
                              ↓                          planner 读取辅助生成步骤
                        reply_node ──→ END
```

### 数据流变更

| 步骤 | 变更前 | 变更后 |
|---|---|---|
| intent_classifier 输出 | `intent_classification` + `intent_reason` | 新增 `intent_analysis`（仅 relevant 时有值） |
| planner 输入 | 仅 `user_request` | `user_request` + `intent_analysis`（辅助） |
| planner prompt | 无意图解析结果 | 包含 `{intent_analysis}` 占位符 |
| reply_node | 使用 `intent_reason` | 不变（仍用 `intent_reason`） |

## IntentExtraction 模型

```python
class IntentExtraction(BaseModel):
    goal: str = Field(description="用户核心意图，如'分析代码变更并评审测试用例'")
    modules: list[str] = Field(default_factory=list, description="涉及的模块名列表")
    source_commit: str = Field(default="", description="源 commit SHA")
    target_commit: str = Field(default="", description="目标 commit SHA")
    needs_code_analysis: bool = Field(default=False, description="是否需要代码变更分析")
    needs_case_review: bool = Field(default=False, description="是否需要测试用例评审")
    test_cases_provided: bool = Field(default=False, description="用户是否提供了测试用例")
    missing_info: list[str] = Field(default_factory=list, description="缺少的关键信息")
```

所有字段有默认值，确保部分解析时不会因为单个字段缺失而整体失败。

## SupervisorState 变更

```python
class SupervisorState(TypedDict, total=False):
    # ... 现有字段 ...
    intent_classification: str        # 不变
    intent_reason: str                # 不变
    intent_analysis: Optional[dict]   # 新增：IntentExtraction.model_dump()，relevant 时有值
```

## 节点变更

### intent_classifier_node

**输出格式变更**（仅 relevant 时增加 `extracted`）：

relevant：
```json
{
  "classification": "relevant",
  "reason": "明确提到代码分析，包含模块名和 commit 范围",
  "extracted": {
    "goal": "分析代码变更并评审测试用例",
    "modules": ["payment"],
    "source_commit": "abc1234",
    "target_commit": "def5678",
    "needs_code_analysis": true,
    "needs_case_review": true,
    "test_cases_provided": false,
    "missing_info": []
  }
}
```

ambiguous：
```json
{
  "classification": "ambiguous",
  "reason": "提到测试但未说明具体模块和 commit 范围"
}
```

irrelevant：
```json
{
  "classification": "irrelevant",
  "reason": "用户仅打招呼"
}
```

**解析逻辑**：

```python
def intent_classifier_node(state: SupervisorState) -> dict:
    llm = get_llm()
    user_request = state.get("user_request", "")
    prompt = load_prompt("intent_classifier", user_request=user_request)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = _strip_markdown_json(response.content)
        assessment = json.loads(content)
        classification = assessment.get("classification", "ambiguous")
        reason = assessment.get("reason", "")
        if classification not in ("relevant", "ambiguous", "irrelevant"):
            classification = "ambiguous"

        # 新增：提取结构化意图（仅 relevant 时）
        intent_analysis = None
        if classification == "relevant":
            extracted = assessment.get("extracted")
            if extracted and isinstance(extracted, dict):
                try:
                    validated = IntentExtraction.model_validate(extracted)
                    intent_analysis = validated.model_dump()
                except Exception:
                    intent_analysis = None  # 降级：丢弃提取结果
    except (json.JSONDecodeError, Exception):
        classification = "ambiguous"
        reason = "意图分类解析失败，默认按模糊请求处理"
        intent_analysis = None

    return {
        "intent_classification": classification,
        "intent_reason": reason,
        "intent_analysis": intent_analysis,
    }
```

### planner_node

**变更**：读取 `intent_analysis`，传入 prompt。

```python
def planner_node(state: SupervisorState) -> dict:
    llm = get_llm()
    user_request = state.get("user_request", "")
    intent_analysis = state.get("intent_analysis")
    tools_info = ToolRegistry.render_all()

    # 格式化意图解析结果
    if intent_analysis:
        analysis_text = _format_intent_analysis(intent_analysis)
    else:
        analysis_text = "(无)"

    prompt = load_prompt(
        "planner",
        user_request=user_request,
        tools_info=tools_info,
        intent_analysis=analysis_text,
    )
    # ... 后续逻辑不变 ...
```

```python
def _format_intent_analysis(analysis: dict) -> str:
    """将 intent_analysis 格式化为 planner 可读的文本"""
    parts = []
    if analysis.get("goal"):
        parts.append(f"- 核心意图：{analysis['goal']}")
    if analysis.get("modules"):
        parts.append(f"- 涉及模块：{', '.join(analysis['modules'])}")
    if analysis.get("source_commit") or analysis.get("target_commit"):
        parts.append(f"- Commit 范围：{analysis.get('source_commit', '?')} → {analysis.get('target_commit', '?')}")
    if analysis.get("needs_code_analysis"):
        parts.append("- 需要：代码变更分析")
    if analysis.get("needs_case_review"):
        parts.append("- 需要：测试用例评审")
    if analysis.get("test_cases_provided"):
        parts.append("- 用户已提供测试用例")
    if analysis.get("missing_info"):
        parts.append(f"- 缺少信息：{', '.join(analysis['missing_info'])}")
    return "\n".join(parts)
```

### reply_node

**不变**。ambiguous/irrelevant 时 `intent_analysis` 为 None，`reply_node` 仍只使用 `intent_classification` 和 `intent_reason`。

### route_from_classifier

**不变**。仍只看 `intent_classification` 字段。

## Prompt 变更

### intent_classifier.md

在原有分类规则基础上新增：

- `relevant` 分类时，必须同时输出 `extracted` 字段
- `ambiguous` / `irrelevant` 分类时，不输出 `extracted` 字段
- 更新所有示例，relevant 示例包含 `extracted`

### planner.md

在"输入"章节后新增：

```markdown
## 意图解析结果

{intent_analysis}

如果意图解析结果可用，直接基于其中的 goal、modules、commit 范围生成步骤，无需重新理解用户需求。如果意图解析结果为"(无)"，根据用户需求原文自行理解。
```

## 错误处理

| 场景 | 处理 | 与变更前对比 |
|---|---|---|
| LLM 返回非 JSON | `classification = "ambiguous"`, `intent_analysis = None` | 不变 |
| JSON 缺少 `classification` | 同上 | 不变 |
| `classification = "relevant"` 但 `extracted` 缺失 | `intent_analysis = None`，planner 自行理解 | **新增** |
| `extracted` 存在但字段不完整 | 尝试 `IntentExtraction.model_validate()`，失败则 `intent_analysis = None` | **新增** |
| `extracted` 字段值不合理（如 modules 为空但 needs_code_analysis = true） | 不做业务校验，原样传递给 planner，由 planner 判断 | **新增** |

## 降级路径

```
extracted 解析成功 → intent_analysis 有值 → planner 参考 extracted 生成步骤
                ↓ 失败
extracted 解析失败 → intent_analysis = None → planner 回退到原始行为（自行理解 user_request）
                ↓
classification 也失败 → classification = "ambiguous" → reply_node 生成引导消息
```

每一级都有安全的降级路径，不会因为 `extracted` 的引入而导致原本能工作的流程中断。

## 测试策略

### 单元测试变更

| 测试 | 变更 |
|---|---|
| `test_intent_classifier_relevant` | mock 返回包含 `extracted` 的 JSON，断言 `intent_analysis` 非空且字段正确 |
| `test_intent_classifier_ambiguous` | mock 返回不含 `extracted` 的 JSON，断言 `intent_analysis` 为 None |
| `test_intent_classifier_irrelevant` | 同上 |
| `test_intent_classifier_invalid_json` | 断言 `intent_analysis` 为 None |
| `test_intent_classifier_extracted_validation_fails` | **新增**：mock 返回 `extracted` 字段不合法的 JSON，断言 `intent_analysis` 为 None 但 `classification` 仍为 "relevant" |
| `test_route_from_classifier` | 不变 |
| `test_planner_with_intent_analysis` | **新增**：验证 planner prompt 包含格式化后的 intent_analysis |
| `test_planner_without_intent_analysis` | **新增**：验证 intent_analysis 为 None 时 planner 仍正常工作 |

### 集成测试变更

| 测试 | 变更 |
|---|---|
| `test_irrelevant_request_skips_planner` | mock 返回不含 `extracted` 的 JSON，其余不变 |
| `test_ambiguous_request_gets_clarification` | 同上 |
| `test_full_pipeline_mocked` | mock classifier 返回含 `extracted` 的 JSON |

## 变更文件清单

| 文件路径 | 操作 | 变更内容 |
|---|---|---|
| `test_agents/graph/state.py` | 修改 | 新增 `IntentExtraction` Pydantic 模型；`SupervisorState` 新增 `intent_analysis` 字段 |
| `test_agents/prompts/intent_classifier.md` | 修改 | 重写 prompt，relevant 时要求输出 `extracted`，ambiguous/irrelevant 不输出 |
| `test_agents/agents/supervisor.py` | 修改 | `intent_classifier_node` 解析 `extracted` 并写入 state；`planner_node` 读取 `intent_analysis`；新增 `_format_intent_analysis` |
| `test_agents/prompts/planner.md` | 修改 | 新增 `{intent_analysis}` 占位符和使用说明 |
| `test_agents/main.py` | 修改 | `_build_initial_state` 新增 `intent_analysis` 初始值（None） |
| `test_agents/tests/test_supervisor.py` | 修改 | 更新 mock 返回值和断言，新增 extracted 降级测试 |
| `test_agents/tests/test_integration.py` | 修改 | 更新 mock 返回值 |

## 不变的部分

- 图结构：节点和边不变
- `route_from_classifier`：仍基于 `intent_classification` 判断
- `reply_node`：仍使用 `intent_classification` + `intent_reason`
- Worker 子图：不受影响
- `save_experience_node`：不变（未来可基于 `intent_analysis.goal` 优化匹配）

## 与现有审查发现的关联

2026-05-20 首版设计审查中发现的以下问题，本次升级**不直接解决**，但为后续改进铺路：

1. **与 main.py 关键字匹配器的冲突** — 不在本次范围内，`intent_analysis` 的结构化提取为未来统一入口层提供了基础
2. **reply_node 异常处理** — 不变，维持现状
3. **ambiguous 多轮澄清** — 不变。`missing_info` 字段存在于 `IntentExtraction` 但当前不传给 `reply_node`，为未来增强保留扩展点
