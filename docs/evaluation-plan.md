# 测试智能体群效果评估方案

本文档定义 Test Agents v3（Plan-and-Solve + Reflection 架构）的**纯效果评估方法**，聚焦于衡量智能体输出质量、决策正确性和任务完成度，不包含传统软件测试（单元测试、结构测试、代码覆盖率）。

> [!note] 评估原则
> Agent 效果评估与软件测试的根本区别在于：**没有唯一标准答案**。同一份代码变更报告可能存在多种合理的写法，同一条测试用例评审结论也可能因视角不同而有差异。因此评估必须依赖结构化匹配、LLM Judge、人工标注等柔性手段，而非简单的对错判断。

---

## 评估分层体系概览

完整的测试体系包含 7 个层级。L1-L2 为传统软件测试，本文档仅覆盖 **L3-L7 的 Agent 效果评估**。

| 层级 | 类型 | 评估对象 | 方法 | 关键指标 |
|-----|------|---------|------|---------|
| L1 | 软件测试 | 路由函数、状态模型、工具类 | 确定性断言 | 测试通过率 |
| L2 | 软件测试 | Graph 拓扑、State 转换 | Mock + 断言 | 节点/边覆盖率 |
| **L3** | **效果评估** | Planner：ExecutionPlan 生成质量 | 结构匹配 | 意图准确率、步骤正确率 |
| **L4** | **效果评估** | Worker：Code Analyzer / Case Reviewer 输出 | LLM Judge + 规则匹配 | 召回率、一致性、解析成功率 |
| **L5** | **效果评估** | Supervisor：Reflection 判断、Synthesize 质量 | 构造已知好/坏结果测试 | 判断准确率、语义完整性 |
| **L6** | **效果评估** | 端到端：完整 Pipeline | Win Rate 成对对比 + 任务完成度 | 胜率、任务成功率 |
| **L7** | **效果评估** | 运营效率：Token、耗时、重试 | 运行时打点 | Token 消耗、响应时间、Replan 率 |

---

## 1. L3：Planner 效果评估（结构匹配）

Planner 使用 `llm.with_structured_output(ExecutionPlan)` 生成计划，输出是 Pydantic 模型，天然适合**结构化匹配**。评估方法论继承 [[智能体性能评估.md]] 中的 **BFCL AST 匹配思想**。

### 1.1 评估数据集

准备标准用户请求，人工标注期望的 `ExecutionPlan`：

| 请求示例 | 期望意图 | 期望步骤 |
|---------|---------|---------|
| "分析订单模块代码变更" | 代码分析 | `[code_analyzer]` |
| "评审测试用例 TC001" | 用例评审 | `[case_reviewer]` |
| "分析 payment 模块从 a1b2c3d 到 e4f5a6b 的变更" | 代码分析 | `[code_analyzer]`，input_mapping 含 module_name/source_commit/target_commit |
| "分析代码变更并评审测试用例" | 混合任务 | `[code_analyzer, case_reviewer]` |
| "帮我看看这些测试用例写得怎么样" | 用例评审 | `[case_reviewer]` |

### 1.2 匹配规则（类比 BFCL AST Match）

定义 `PlanMatch(预测 P, 期望 G)`：

```
PlanMatch(P, G) = 1 当且仅当：
  1. 意图分类一致：P.intent 与 G.intent 属于同一语义类别
  2. 步骤数量相等：len(P.steps) == len(G.steps)
  3. 每步 agent 类型一致：P.steps[i].agent == G.steps[i].agent
  4. 关键 input_mapping 字段完备：
     - G 中要求的字段（module_name / source_commit / target_commit / test_cases）P 中必须存在
     - 值可以是常量字符串或 ${field} 引用，字段名必须对应
```

### 1.3 评估指标

| 指标 | 定义 | 计算方式 | 目标值 |
|-----|------|---------|--------|
| **意图识别准确率** | 意图分类正确的比例 | 正确意图数 / 总样本数 | ≥ 90% |
| **步骤正确率** | 计划完全匹配的比例 | PlanMatch == 1 的样本数 / 总样本数 | ≥ 85% |
| **input_mapping 完备率** | 关键字段映射正确的比例 | 字段映射正确的步骤数 / 期望映射字段总数 | ≥ 90% |
| **分类准确率** | 按意图类型分别统计 | 某意图类型正确数 / 该类型总样本数 | — |

### 1.4 失败分析

当 Planner 评估失败时，按以下维度分类根因：

- **意图误分类**：如将"分析并评审"误判为纯代码分析
- **步骤遗漏**：如遗漏了 case_reviewer 步骤
- **顺序错误**：如先评审再分析（虽然本项目顺序通常不影响结果，但需记录）
- **参数缺失**：如未映射 source_commit / target_commit
- **幻觉参数**：如映射了不存在的字段

---

## 2. L4：Worker 效果评估（LLM Judge + 结构化指标）

Worker 层的评估覆盖两个 Agent：**Code Analyzer** 和 **Case Reviewer**。两者输出均为开放文本或半结构化数据，需使用 **LLM Judge** 评估语义质量，同时结合**规则匹配**验证结构化正确性。

> 本项目 `tools/builtin/llm_judge_tool.py` 已集成 LLM Judge 框架，可直接复用。

---

### 2.1 Code Analyzer 效果评估

Code Analyzer 输出开放式代码变更报告，无唯一标准答案。

#### 评估数据集

| 字段 | 说明 |
|-----|------|
| `module_name` | 模块名称 |
| `source_commit` / `target_commit` | Commit 范围 |
| `diff` | 真实的 git diff 或构造的 mock diff |
| `expected_coverage` | 期望报告涵盖的关键文件/函数列表 |
| `expected_risks` | 期望识别出的高风险变更点 |
| `expected_structure` | 期望报告包含的段落（如"变更概述"、"风险点"、"影响范围"） |

#### LLM Judge 评分维度（1-5 分）

| 维度 | 评分标准 |
|-----|---------|
| **变更覆盖度** | 5=涵盖所有关键文件和函数；1=遗漏核心变更 |
| **风险识别** | 5=准确标记所有高风险点；1=完全未识别风险 |
| **报告清晰度** | 5=结构清晰、段落分明、结论明确；1=混乱无章 |
| **准确性** | 5=分析描述与 diff 完全一致，无幻觉；1=包含明显错误描述 |

#### 评估指标

| 指标 | 定义 | 目标值 |
|-----|------|--------|
| **平均分** | 所有样本四维度均值的平均 | ≥ 3.5 |
| **及格率** | 平均分 ≥ 3.5 的样本比例 | ≥ 80% |
| **优秀率** | 平均分 ≥ 4.5 的样本比例 | ≥ 30% |
| **覆盖度召回率** | `expected_coverage` 中被报告提及的比例 | ≥ 85% |
| **风险识别召回率** | `expected_risks` 中被报告提及的比例 | ≥ 75% |

---

### 2.2 Case Reviewer 效果评估

Case Reviewer 输出结构化 JSON（`review_results`），评估需兼顾**语义质量**（LLM Judge）和**结构化正确性**（解析指标）。

#### 评估数据集

| 字段 | 说明 |
|-----|------|
| `test_cases` | 测试用例列表（含已知问题：缺失断言、边界值遗漏、步骤不完整等） |
| `code_change_report` | 关联的代码变更报告（可选） |
| `known_issues` | 每条用例的已知问题清单 |
| `expected_verdicts` | 期望的评审结论（pass / needs_revision / fail） |

#### LLM Judge 评分维度（1-5 分）

| 维度 | 评分标准 |
|-----|---------|
| **问题发现能力** | 5=发现所有已知问题；1=完全遗漏 |
| **评审合理性** | 5=结论与理由逻辑自洽；1=结论与理由矛盾 |
| **建议可执行性** | 5=给出的修改建议具体可执行；1=建议空泛无用 |
| **结构化程度** | 5=输出为规范 JSON，字段完整；1=无法解析 |

#### 结构化指标

| 指标 | 定义 | 目标值 |
|-----|------|--------|
| **评审召回率** | 已知有问题的用例被检测出的比例 | ≥ 80% |
| **误报率** | 无问题的用例被标记为有问题的比例 | ≤ 20% |
| **评分一致性** | 同一批用例多次评审，评分标准差 | ≤ 0.5 |
| **JSON 解析成功率** | `review_results` 能被正确解析为列表的比例 | ≥ 95% |

---

## 3. L5：Supervisor 效果评估（判断准确率 + LLM Judge）

Supervisor 层包含两个关键节点：**Reflection** 和 **Synthesize**。Reflection 是 Agent 的**元决策能力**，Synthesize 是**信息汇总质量**。

---

### 3.1 Reflection 效果评估

`reflect_node` 负责判断整体执行结果是否合格，决定 `COMPLETE` 或 `REPLAN`。

#### 评估方法

**构造已知结果的测试集**（不经过真实 Worker 执行，直接构造 `step_results` 注入）：

| 场景 | step_results 构造 | 期望结论 |
|-----|------------------|---------|
| 全部成功 | 所有步骤 status="success"，输出完整 | `COMPLETE` |
| Worker 失败 | 某步骤 status="failed"，error 非空 | `REPLAN` |
| 输出为空 | Code Analyzer 返回空报告 | `REPLAN` |
| 结果矛盾 | Analyzer 报告无风险，但 Reviewer 发现大量问题 | `REPLAN` |
| 部分成功 | 一个 Worker 成功，一个失败 | `REPLAN` |
| 重复失败 | 同一 Worker 多次重试后仍失败 | `COMPLETE`（应接受结果，避免无限循环） |

#### 评估指标

| 指标 | 定义 | 目标值 | 重要性 |
|-----|------|--------|--------|
| **判断准确率** | reflect 结论与人工标注一致的比例 | ≥ 85% | 核心指标 |
| **假阴性率** | 应 REPLAN 但判为 COMPLETE 的比例 | ≤ 15% | 漏判会导致低质量结果交付 |
| **假阳性率** | 应 COMPLETE 但判为 REPLAN 的比例 | ≤ 15% | 误判会浪费 Token 和时间 |

---

### 3.2 Synthesize 效果评估

`Synthesize` 将多个 Worker 的输出汇总为 `final_answer`，评估重点是**信息保真度**和**用户意图匹配度**。

#### 评估方法

构造多组包含不同 `step_results` 的 State，运行 `synthesize_node`，对输出进行 LLM Judge 评估。

#### LLM Judge 评分维度（1-5 分）

| 维度 | 评分标准 |
|-----|---------|
| **信息完整性** | 5=覆盖所有步骤的关键结论，无遗漏；1=遗漏核心信息 |
| **逻辑一致性** | 5=最终结论与各步骤结果完全一致，无矛盾；1=存在明显矛盾 |
| **用户意图匹配度** | 5=直接回答用户原始问题，无偏题；1=完全未回应用户需求 |
| **结构化程度** | 5=有清晰段落、标题、结论；1=大段堆砌、无层次 |

#### 评估指标

| 指标 | 定义 | 目标值 |
|-----|------|--------|
| **平均分** | 四维度均值的平均 | ≥ 3.5 |
| **信息遗漏率** | 关键信息（来自 step_results）未出现在 final_answer 中的比例 | ≤ 10% |

---

## 4. L6：端到端效果评估（Win Rate + 任务完成度）

端到端评估衡量整个 Pipeline 从用户请求到最终答案的完整效果。继承 [[智能体性能评估.md]] 中的 **Win Rate 成对对比** 和 **GAIA 准精确匹配** 方法。

---

### 4.1 Win Rate 成对对比（架构有效性验证）

设计以下对比实验，验证 Plan-and-Solve + Reflection 架构是否有效：

| 对比组 A | 对比组 B | 验证假设 |
|---------|---------|---------|
| **v3 Plan-and-Solve + Reflection** | v2 直接调度（无计划节点） | Plan-and-Solve 是否能提升复杂任务质量 |
| **多智能体**（Supervisor + 2 Workers） | **单智能体**（直接用 GPT-4o 处理同样请求） | 分工协作是否优于单模型端到端 |
| **含 Reflection** | **不含 Reflection**（Worker 和 Supervisor 反射均关闭） | Reflection 是否能提升输出质量一致性 |

#### 实验设计

1. 准备 50+ 组真实业务请求
2. 每组请求分别输入 A 和 B
3. 使用 LLM Judge（或人工）进行盲评，判定哪组输出更好
4. 统计 Win / Loss / Tie

#### 评估指标

| 指标 | 定义 | 解读 |
|-----|------|------|
| **胜率** | A 被判定更好的比例 | > 55% 说明架构有显著优势 |
| **败率** | B 被判定更好的比例 | > 30% 说明架构 overhead 未带来实质收益 |
| **平局率** | 两者质量相当的比例 | 高平局率说明架构差异不大 |

> [!tip] 理想结果
> Win Rate ≈ 50% 说明本系统与基线质量相当；显著高于 50% 说明 Plan-and-Solve + Reflection 架构有效；显著低于 50% 说明需要重新审视架构设计。

---

### 4.2 任务完成度评估（GAIA 式）

对于**有明确标准答案**的任务（如"列出变更涉及的所有模块"、"给出评审不通过的用例 ID 列表"），参考 GAIA 的**准精确匹配（Quasi Exact Match）**：

**归一化规则**：
- 列表答案：元素排序后重新连接（忽略顺序差异）
- 文本答案：转小写、移除多余空格和末尾标点
- 数字答案：移除逗号分隔符

#### 评估指标

| 指标 | 定义 | 计算方式 |
|-----|------|---------|
| **任务成功率** | 归一化后与期望答案匹配的比例 | 正确样本数 / 总样本数 |
| **分意图成功率** | 按意图类型分别统计 | 某类型正确数 / 该类型总样本数 |

> [!warning] 局限性
> 代码分析报告和用例评审结论通常无法做精确匹配，此指标仅适用于有明确答案子集的任务。开放性任务请使用 LLM Judge。

---

## 5. L7：效率与成本监控（运营基线）

Agent 效果不仅包括质量，还包括**效率和成本**。参考 **智能体性能评估.md** 中"评估成本高昂"的警示，建立运行时监控：

| 指标 | 说明 | 采集方式 | 目标值 |
|-----|------|---------|--------|
| **Token 消耗** | 单次请求总 Token 数 | 在 `get_llm()` 添加 LangChain callback | 视模型而定 |
| **API 调用次数** | 单次请求中 LLM invoke 次数 | 在节点入口处计数 | ≤ 10 次（含 Reflection） |
| **响应时间** | 从请求到 `final_answer` 的总耗时 | `run_test_agents()` 打点计时 | ≤ 60s（不含人工确认） |
| **Worker 重试率** | Worker reflect 触发重试的比例 | `reflection_count > 0` 的样本占比 | ≤ 30% |
| **Replan 率** | Supervisor 触发重规划的比例 | `needs_replan=True` 的样本占比 | ≤ 20% |
| **确认重试率** | 用户拒绝计划导致重规划的比例 | `confirm_retry_count > 0` 的样本占比 | ≤ 15% |

---

## 6. 实施路线图

```
Phase 1（1-2 周）：L3 Planner + L5 Reflection 评估
├── 建立 Planner 评估数据集（20+ 条标准请求）
├── 实现 PlanMatch 结构匹配脚本
├── 构造 Reflection 好/坏结果测试集（10+ 场景）
└── 输出：Planner 意图准确率、Reflection 判断准确率基线

Phase 2（2-3 周）：L4 Worker + L5 Synthesize 质量评估
├── Code Analyzer：建立含已知变更的测试集（15+ 组）
├── Code Analyzer：LLM Judge 四维度评分脚本
├── Case Reviewer：建立含已知问题的用例集（20+ 组）
├── Case Reviewer：召回率/误报率/LLM Judge 联合评估
├── Synthesize：多组 step_results → final_answer 评估
└── 输出：Worker 平均分、召回率、Synthesize 信息遗漏率

Phase 3（3-4 周）：L6 端到端对比 + L7 效率基线
├── Win Rate：v3 vs v2 成对对比（50+ 组请求）
├── Win Rate：多智能体 vs 单智能体对比（30+ 组）
├── 任务完成度：有明确答案的任务成功率统计
├── 效率基线：100 次请求的运行时指标统计
└── 输出：Win Rate 报告、效率基线报告

Phase 4（持续）：回归监控
├── 每次模型/提示词变更后跑 Phase 1-2 评估
├── 每周跑 Phase 3 端到端评估（采样 20 组）
├── 每月更新效率基线，监控 Token 成本趋势
└── 建立评估结果历史数据库，追踪指标变化
```

---

## 7. 现有工具复用说明

本项目 `tools/builtin/` 中预置了 HelloAgents 框架的评估工具，需根据本项目架构适配使用：

| 工具 | 文件 | 复用建议 |
|-----|------|---------|
| **LLM Judge** | `tools/builtin/llm_judge_tool.py` | **最可直接复用**。替换评估维度为本文 L4（Worker）和 L5（Synthesize）定义的专属维度 |
| **Win Rate** | `tools/builtin/win_rate_tool.py` | **可直接复用**。对比组替换为 v3 vs v2 或 多智能体 vs 单智能体 |
| **BFCL 评估** | `tools/builtin/bfcl_evaluation_tool.py` | 不直接用于工具调用评估，但可借鉴其 AST 匹配逻辑实现 L3 Planner 的 `PlanMatch` |
| **GAIA 评估** | `tools/builtin/gaia_evaluation_tool.py` | 可用于 L6 有明确答案的端到端任务，需替换数据集为本项目业务场景 |

---

## 附录 A：评估数据集模板

### Planner 评估数据集

```json
[
  {
    "request": "分析订单模块代码变更",
    "expected_plan": {
      "intent": "代码分析",
      "steps": [
        {
          "agent": "code_analyzer",
          "input_mapping": {
            "module_name": "${module_name}",
            "source_commit": "${source_commit}",
            "target_commit": "${target_commit}"
          }
        }
      ]
    }
  }
]
```

### Code Analyzer 评估数据集

```json
[
  {
    "module_name": "order",
    "source_commit": "a1b2c3d",
    "target_commit": "e4f5a6b",
    "diff": "...git diff 内容...",
    "expected_coverage": ["OrderService.create_order", "OrderValidator.validate"],
    "expected_risks": ["数据库事务边界变更"]
  }
]
```

### Case Reviewer 评估数据集

```json
[
  {
    "test_cases": [
      {"case_id": "TC001", "title": "创建订单", "steps": "1. 输入商品ID 2. 点击提交", "expected_result": "订单创建成功"}
    ],
    "known_issues": ["缺少边界值测试", "步骤描述不完整"],
    "expected_verdicts": ["needs_revision"]
  }
]
```

### Reflection 评估数据集

```json
[
  {
    "scenario": "全部成功",
    "step_results": [
      {"step_id": 1, "agent": "code_analyzer", "status": "success", "output_key": "code_change_report"},
      {"step_id": 2, "agent": "case_reviewer", "status": "success", "output_key": "review_results"}
    ],
    "expected_assessment": "COMPLETE"
  }
]
```

---

## 附录 B：指标汇总表

| 层级 | 评估对象 | 核心指标 | 目标值 | 评估方法 |
|-----|---------|---------|--------|---------|
| L3 | Planner | 意图识别准确率 | ≥ 90% | 结构匹配 |
| L3 | Planner | 步骤正确率 | ≥ 85% | 结构匹配 |
| L4 | Code Analyzer | 平均分 | ≥ 3.5/5 | LLM Judge |
| L4 | Code Analyzer | 风险识别召回率 | ≥ 75% | 规则匹配 |
| L4 | Case Reviewer | 评审召回率 | ≥ 80% | 规则匹配 |
| L4 | Case Reviewer | 误报率 | ≤ 20% | 规则匹配 |
| L4 | Case Reviewer | JSON 解析成功率 | ≥ 95% | 规则匹配 |
| L5 | Reflection | 判断准确率 | ≥ 85% | 构造测试集 |
| L5 | Reflection | 假阴性率 | ≤ 15% | 构造测试集 |
| L5 | Synthesize | 平均分 | ≥ 3.5/5 | LLM Judge |
| L5 | Synthesize | 信息遗漏率 | ≤ 10% | 规则匹配 |
| L6 | 端到端 | 任务成功率 | ≥ 70% | 准精确匹配 |
| L6 | 端到端 | Win Rate | ≥ 45% | 成对对比 |
| L7 | 效率 | 响应时间 | ≤ 60s | 运行时打点 |
| L7 | 效率 | Replan 率 | ≤ 20% | 运行时统计 |
