# 数字员工建设设计文档

**日期**：2026-05-21
**作者**：基于 brainstorming 与用户决策共同沉淀
**适用项目**：test_agents（基于 LangGraph 的多智能体测试系统）
**目标定位**：将现有"工具型 Agent"演进为**专家型测试数字员工**

---

## 0. 背景与定位

### 0.1 现状

当前项目（test_agents v3）已具备 Plan-and-Solve + Reflection 的基础形态：
- 执行层：`intent_classifier → planner → dispatch → worker → reflect → synthesize → save_experience`
- Worker 子图：`agent ⇄ tools → reflect → END`
- Worker 类型：`code_analyzer`（代码变更分析）、`case_reviewer`（测试用例评审）

但距离"数字员工"还存在三层根本性能力缺失：

| 层 | 现状 | 缺失 |
|---|---|---|
| 执行层 | 能跑完流程产出报告 | 不知道自己不知道，缺业务感，错误兜底不足 |
| 评估层 | LLM 自评打分（reflect_node） | 无真值基准、无多维度量化、无回归门禁 |
| 进化层 | `save_experience` 写日志 | 写了没人读，无召回回灌、无错题本、无 prompt 迭代 |

### 0.2 目标

建成一个**专家型测试数字员工**：聚焦"代码变更分析 + 测试用例评审"两项核心职责，做到接近资深测试工程师水平。

**不做**：
- 通用型员工（不扩展到自动写用例、缺陷分类等）
- 平台化（不做"孵化任意角色"的通用底座）

### 0.3 智能体 vs 数字员工的分界线

| 维度 | 智能体（现状） | 数字员工（目标） |
|---|---|---|
| 定位 | 通用认知引擎 | 企业虚拟岗位镜像 |
| 边界 | 任务驱动、跨领域 | 岗位导向、职责固定 |
| 治理 | 无身份、无 KPI | 工号、KPI、审计、SLA |
| 流程 | 自由发挥 | SOP 驱动、可审批、可追溯 |
| 迭代 | 偶尔改 prompt | 闭环演进（错题→反馈→经验→实验） |

---

## 1. 决策汇总

所有关键决策已通过 brainstorming 与用户对齐：

| 维度 | 决策 |
|---|---|
| 数字员工形态 | 专家型测试员工 |
| 执行层 - 判断力 | A2 不确定性自省（先）→ A1 提升天花板（后） |
| 执行层 - 不确定动作 | L4 标记升级，集中呈现待人工 review |
| 执行层 - 不确定判定 | S3 评审员（主） + S4 规则（辅） |
| 执行层 - 业务知识源 | B2 历史抽取（主） + B3 在线沉淀（辅） |
| 执行层 - 数据源 | D1 Git + D2 PR/Review + D3 Bug 单（必拿），D4/D5/D6 弱依赖 |
| 执行层 - 知识召回 | R3 Agent 主动查询（工具化），高 severity 错题强制注入 |
| 执行层 - SOP 实现 | 方案 C 混合：LangGraph 骨架 + YAML 策略层 |
| 执行层 - 审批机制 | C2 待审批队列 + CLI 工具 |
| 评估层 - 真值基准 | C1 黄金集 20-30 个/tenant 起步 |
| 评估层 - 评分维度 | M2 四维度，风险覆盖率用 M3 关键点命中率 |
| 进化层 - 路径 | E2 错题本 → E4 反馈通道 → E1 经验库 → E3 prompt 自动迭代 |
| 交付节奏 | P2 最小闭环，分 4 阶段 |
| 身份模型 | I2 多员工实例，2-3 个起步，默认隔离 + 通用经验可晋升 |
| 治理补充 | 岗位说明书 + 审计追溯 + 运营监控 CLI |

---

## 2. 整体架构

```
                        ┌─────────────────────────────────────────────┐
                        │             数字员工实例（per tenant）         │
                        │   tenant: 订单/支付/会员（2-3 个起步）          │
                        └─────────────────────────────────────────────┘

┌──────────────────────── 执行层 (Execution Layer) ────────────────────────┐
│                                                                            │
│  user_request ──> intent_classifier ──> planner ──> dispatch              │
│                                                       │                    │
│                                                       ▼                    │
│                                ┌──── Worker 子图 ──────────────────┐      │
│                                │  agent ⇄ tools (含知识工具集)      │      │
│                                │     │                              │      │
│                                │     ▼                              │      │
│                                │  reflect (流程决策)                 │      │
│                                │     │                              │      │
│                                │     ▼                              │      │
│                                │  judge (4 维评分)                   │      │
│                                │     │                              │      │
│                                │     ▼                              │      │
│                                │  rule_check (S4 硬约束)             │      │
│                                │     │                              │      │
│                                │     ▼                              │      │
│                                │  sop_check (策略层)                 │      │
│                                │     ├ mandatory_tools 缺失→升级    │      │
│                                │     ├ force_escalation 命中→升级   │      │
│                                │     └ approval_gate 命中→interrupt │      │
│                                └────────────┬───────────────────────┘      │
│                                             │                              │
│                                             ▼                              │
│                                  INTERRUPT（如需审批）                       │
│                                             │                              │
│                                             ▼ resume                       │
│                                       synthesize                           │
│                                       （报告 + ⚠️待复核 + 审批记录）         │
│                                             │                              │
│                                             ▼                              │
│                                    save_experience                         │
│                              （失败→错题本，成功→success_case）              │
└────────────────────────────────────────────┬───────────────────────────────┘
                                             │
         ┌───────────────────────────────────┴────────────────────────┐
         ▼                                                            ▼
┌── 评估层 (Eval) ────────────────────┐               ┌── 进化层 (Evolve) ──────┐
│                                      │               │                          │
│  黄金集（per tenant, 20-30 case）     │               │  错题本（E2）             │
│      │                               │ ──失败 case──>│      ↓                   │
│  CI 回归运行器（4 维 × case 矩阵）   │               │  反馈通道（E4）          │
│      │                               │               │      ↓                   │
│  能力曲线 + 回归门禁                  │               │  经验库（E1，正负通吃）   │
│                                      │               │      ↓                   │
│  Judge Agent + 校准集                 │ <─Judge 评分─ │  Prompt 自动迭代（E3）   │
│                                      │               │      ↓                   │
└──────────────────────────────────────┘               │  实验台 + 灰度 + 人工批  │
                                                       └──────────────────────────┘

────────── 共享基础设施 ──────────
• 多租户存储（SQLite + Chroma），所有表带 tenant_id
• 通用经验晋升通道（tenant_id = "GLOBAL"）
• 知识抽取 pipeline（D1/D2/D3 → embedding → 工具暴露）
• 审计追溯（decision_log jsonl）
• 待审批队列（approval_queue 表 + CLI）
• 运营监控（admin status CLI）
```

**三层间的关键数据流**：

1. **执行 → 评估**：每次报告产出后，自动走 Judge 4 维评分；不达标进入"待 review 队列"
2. **评估 → 进化**：失败 case 自动入错题本；用户反馈通过 E4 入库；月度回归数据驱动 E3 prompt 迭代
3. **进化 → 执行**：错题本高 severity 条目主动注入 system prompt；其他通过 `query_lessons_learned` 工具按需查

---

## 3. 执行层详细设计

### 3.1 评审员 Agent（Judge as Critic）

**职责**：每份 Worker 报告产出后，由独立 Agent 从 4 维度打分，决定是否触发 L4 升级。

**关键设计**：
- 独立 prompt、独立 LLM 实例，与执行 Worker 完全解耦，避免同源偏差
- 评审员可用更稳的模型（如 GPT-4o），Worker 可用 Kimi 等
- 输入：原始 user_request + 执行报告 + Worker 调用过的工具记录
- 输出：结构化 JSON，含 4 维分数 + 每个低分维度的具体证据
- 判定阈值：任一维度 < 0.6 → 触发 L4 升级

**4 个评分维度**：

| 维度 | 评分算法 | 取值 |
|---|---|---|
| 风险覆盖率 | M3 关键点命中率（黄金集标注里有"必须命中的 N 个关键风险"） | 0-1 |
| 业务术语准确率 | 是否使用了本地业务术语而非通用模板词 | 0 或 1 |
| 证据强度 | 每个论断是否引用了具体代码 / diff / 历史 bug | 0-1 |
| 结论可执行性 | 建议是否具体可执行（"建议加测试" vs "建议测 X 接口的 Y 边界值"） | 0-1 |

**与现有 reflect_node 的关系**：
- reflect 保留，只做流程决策（REPLAN / COMPLETE）
- judge 是新角色，专门做质量评估
- 两者职责不同，不合并

**新增文件**：
- `test_agents/agents/judge.py`
- `test_agents/prompts/judge.md`
- `test_agents/graph/state.py` 增加 `JudgeResult` Pydantic 模型

### 3.2 规则引擎（S4 硬约束兜底）

**职责**：对"绝不能漏"的关键领域做规则兜底，不依赖 LLM 是否"想到"。

**关键设计**：
- 规则形态：YAML 配置 + Python 校验函数，**不是 LLM**
- 执行时机：Judge 评分完毕后并行跑，规则不通过同样触发 L4
- 规则归属：按 tenant 维护，允许 `tenant: GLOBAL` 表示通用规则
- MVP：阶段 1 每 tenant 先建 3-5 条最关键规则

**规则示例**：

```yaml
# eval/rules/payment.yaml
- id: payment_must_mention_transaction
  when:
    module_in: [payment, billing, refund]
  require_in_report:
    any_of: [transaction, idempotent, rollback, 幂等]
  severity: high
```

**新增文件**：
- `test_agents/eval/rule_engine.py`
- `test_agents/eval/rules/<tenant>.yaml`

### 3.3 知识工具集（R3 主动查询）

**职责**：将 D1/D2/D3 数据源抽取的知识以**工具**形式暴露给 Worker。

**工具清单（MVP）**：

| 工具名 | 输入 | 返回 |
|---|---|---|
| `query_similar_bugs` | keyword / module / error_signature | top-K 历史 bug 摘要 + 修复 commit |
| `query_module_history` | module_name | 该模块近 N 月的变更脉络、热点文件 |
| `query_pr_discussion` | file_path 或 PR_id | 相关 PR 的 review 评论、争议点 |
| `query_lessons_learned` | task_keyword | 错题本 + 经验库的相关条目 |

**关键设计**：
- 复用现有 `TestAgentTool` 基类，自动注册到 `ToolRegistry`
- 每个工具内部按 tenant_id 过滤，默认 `include_global=True`
- 知识抽取 pipeline 是独立项目（不在 LangGraph 图里），定期跑（每日/每周）
- 阶段 1 只接 D1（Git），其余源在阶段 2 接入

**双重召回策略**（关键设计）：
- **高 severity 错题**（`severity == "high"`）：在 Worker 启动前主动注入 system prompt（不依赖 Agent "想到去查"），单次注入最多 top 3 条
- **其他知识**（severity=mid/low、success_case、模块历史、PR 讨论等）：通过 `query_lessons_learned`、`query_similar_bugs` 等工具按需查询

**新增文件**：
- `test_agents/tools/query_similar_bugs.py` 等 4 个工具
- `test_agents/knowledge/extractor/`（阶段 2）
- `test_agents/knowledge/store.py`

### 3.4 SOP 策略层（方案 C）

**核心思路**：流程骨架（LangGraph 图）由工程师管，**策略层（YAML）**由业务方管。

**SOP 策略文件**：`tenants/<tenant>/sop.yaml`

**5 个段的语义边界**：

| 段 | 回答的问题 | 触发时机 |
|---|---|---|
| `mandatory_tools` | "干这事必须调哪些工具" | Worker 执行结束、Judge 之前 |
| `approval_gates` | "什么内容必须人工批" | Worker 结束、Judge 之后、Synthesize 之前 |
| `timeouts` | "工具/节点挂了怎么办" | 每个节点执行包裹中 |
| `escalation_channels` | "升级了发给谁" | 任何 escalated_item 产生时 |
| `force_escalation` | "什么硬条件必须升级" | Judge 评分后立即检查 |

**完整 SOP 示例**：

```yaml
# tenants/payment/sop.yaml
version: "1.0"
tenant: payment

mandatory_tools:
  - id: payment_must_query_bugs
    when:
      module_in: [payment, billing, refund]
    must_call_any_of: [query_similar_bugs, query_module_history]
    on_violation: escalate
    reason: "支付域变更必须查历史 bug，避免重复事故"

approval_gates:
  - id: schema_change_approval
    when:
      report_contains_any: ["schema 变更", "DROP", "ALTER TABLE", "字段类型变更"]
    approver_role: payment_tech_lead
    timeout: 24h
    on_timeout: escalate_to_admin
    reason: "schema 变更高风险，必须 tech lead 确认"

timeouts:
  claude_cli:
    duration: 120s
    retry: 1
    on_fail: escalate
  judge:
    duration: 60s
    on_fail: skip_with_warning

escalation_channels:
  - severity: high
    channels: [approval_queue, feishu_webhook]
    target: payment_team_group
  - severity: mid
    channels: [approval_queue, report_inline]
  - severity: low
    channels: [report_inline]

force_escalation:
  - when:
      module_in: [payment]
      judge_dimension: evidence_strength
      score_below: 0.8
    severity: high
    reason: "支付域证据强度不足必须人工复核"
```

**SOP 解释器**：`test_agents/sop/enforcer.py`

**接入位置**：Worker 子图加 `sop_check` 节点：

```
agent ⇄ tools → reflect → judge → rule_check → sop_check → END
                                                    │
                                                    ├ pass → synthesize
                                                    ├ approval_required → interrupt + 写队列
                                                    └ escalate → escalated_items
```

**阶段分配**：
- 阶段 1：只实现 `mandatory_tools` 和 `force_escalation`
- 阶段 2：加入 `timeouts`
- 阶段 3：加入 `approval_gates` + `approval_queue`
- 阶段 4：加入 `escalation_channels` 外部通道（飞书等）

### 3.5 待审批队列（C2 实现）

**新增 SQLite 表**：

```sql
CREATE TABLE approval_queue (
    ticket_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    gate_id TEXT,
    approver_role TEXT,
    context_json TEXT,
    status TEXT,                     -- pending / approved / rejected / timeout
    created_at DATETIME,
    timeout_at DATETIME,
    approved_by TEXT,
    approved_at DATETIME,
    decision_note TEXT,
    FOREIGN KEY (task_id) REFERENCES task_runs(task_id),
    INDEX(tenant_id, status, timeout_at)
);
```

**关键机制**：
- 命中 approval_gate → LangGraph `interrupt` 把 state 持久化（已有 checkpointer）
- 写一条记录到 `approval_queue`
- 审批者通过 CLI 操作：
  ```bash
  python -m test_agents.admin approval list --role payment_tech_lead
  python -m test_agents.admin approval show <ticket_id>
  python -m test_agents.admin approval approve <ticket_id> --note "..."
  python -m test_agents.admin approval reject <ticket_id> --note "..."
  ```
- 超时处理：定时任务每 5 分钟扫 `timeout_at < now` 且 `status=pending` 的票据
- 审批结果回流：
  - approved → resume task，继续 synthesize
  - rejected → resume task，拒绝理由作为 escalated_item；自动入错题本

### 3.6 Worker 子图改造

**改造前**：`agent → tools → agent → reflect → END`
**改造后**：`agent → tools → agent → reflect → judge → rule_check → sop_check → distill → END`

**State 扩展**：

```python
class WorkerState(TypedDict):
    tenant_id: str               # 新增，从 SupervisorState 透传
    task: str
    messages: List
    error: str
    reflection_count: int
    result: str
    judge_result: JudgeResult    # 新增
    escalated_items: List[EscalatedItem]  # 新增
    approval_pending: Optional[str]  # 新增，审批 ticket_id
```

**修改文件**：
- `test_agents/agents/worker_base.py`
- `test_agents/graph/state.py`
- `test_agents/prompts/synthesize.md`（增加"⚠️ 待人工复核项"章节模板）

---

## 4. 评估层详细设计

### 4.1 黄金集（Golden Set）

**形态**：每个 tenant 独立维护 20-30 个 case，每个 case 是一个 YAML 文件，纳入 git 版本控制。

**单个 case 结构**：

```yaml
# eval/golden_set/order/case_001.yaml
id: order_001
tenant: order
created_at: 2026-05-21
created_by: 张三（资深测试）

input:
  user_request: "分析订单模块从 a1b2c3 到 e4f5a6 的变更，评审 3 条相关用例"
  module: order
  source_commit: a1b2c3d
  target_commit: e4f5a6b
  test_cases: [...]

expected:
  # M3 关键点命中率用的"必须命中点"
  must_hit_risks:
    - id: r1
      desc: "order_status 状态机新增 PENDING_REFUND 但 status_history 表未同步"
      keywords_any: [status_history, PENDING_REFUND, 状态历史]
    - id: r2
      desc: "金额字段 amount 改为 decimal 后未处理历史 long 类型数据迁移"
      keywords_any: [decimal, long, 数据迁移, migrate]

  # M2 其他三维标尺
  required_terms: [PENDING_REFUND, status_history, 幂等]
  required_evidence_types: [diff_line, bug_history, pr_discussion]
  required_action_specificity: high

metadata:
  difficulty: medium
  scenario: code_review + case_review
  notes: "复盘自 2025-12 的真实事故"
```

**关键设计**：
- 存放路径：`eval/golden_set/<tenant>/case_*.yaml`，git 版本控制
- 冷启动：阶段 1 每 tenant 标 5 个，阶段 2 扩到 20-30
- case 来源：优先从真实事故复盘里选，避免凭空编
- 演进策略：每月 review，太简单的退役，新事故新增

### 4.2 Judge Agent 在评估场景的复用

- 同一 Judge prompt 用于"在线评分"和"离线评估"，保证一把尺
- 批量模式：评估场景下一次性吃 N 个 case，并行调用
- **Judge 校准集**（关键）：
  - 阶段 1 标注 5 个 case 时，同时标注 Judge 对这 5 个 case 应给的分数
  - 改 Judge prompt 后先在校准集上跑，验证打分接近人工预期，再上线
  - 这是元评估，必须做

### 4.3 回归运行器（CI 化）

**命令**：

```bash
# 跑某 tenant 的全部黄金集
python -m test_agents.eval.run --tenant order

# 跑某 tenant 的单个 case
python -m test_agents.eval.run --tenant order --case order_001

# 跑全部 tenant + 输出回归报告
python -m test_agents.eval.run --all --baseline last_main --report html
```

**输出**：`eval_report.json/html`，包含：
- 总览：各 tenant × 4 维分数矩阵；vs baseline 的 delta
- case 明细：每个 case 的 4 维分数 + Judge 扣分理由 + 实际报告 diff
- 回归门禁：任一 case 任一维度下降 > 0.1 → 标红、CI fail
- 失败聚类：按"失败类型"聚类（漏风险/术语错/证据弱/结论虚）

**CI 集成**：
- PR 触发：每次改 prompt / 工具 / Worker → 自动跑回归 → 评论 PR
- 每日定时：凌晨跑全量，分数曲线写入 `data/capability_trend/<tenant>.jsonl`

**关键设计**：
- 回归门禁阈值保守（任一维度下降 > 0.1 才 fail），避免噪声卡 CI
- 不做"分数必须涨才合并"，只防退步、不强求进步

**新增文件**：
- `test_agents/eval/runner.py`
- `test_agents/eval/reporter.py`
- `test_agents/eval/baseline.py`
- `.github/workflows/eval.yml`

---

## 5. 进化层详细设计

### 5.1 E2：错题本机制（阶段 1）

**核心思路**：评估层判失败的 case 自动入"错题本"；下次任务执行前根据特征召回相似错题，作为强警告注入 prompt。

**数据结构**：

```python
class LessonRecord:
    id: str
    tenant: str                  # order / payment / member / GLOBAL
    created_at: datetime
    source: str                  # "judge_failed" / "rule_failed" / "user_feedback" / "approval_rejected"

    trigger:
        module: str
        keywords: List[str]
        embedding: List[float]
        scenario_tags: List[str]

    what_went_wrong: str
    why_it_matters: str
    correct_approach: str

    severity: str                # low / mid / high
    hit_count: int
    last_validated: datetime
```

**召回机制**：
- 高 severity 错题：Worker 启动前主动注入 system prompt
- 其他错题：通过 `query_lessons_learned` 工具按需查询

**注入示例**：

```
⚠️ 历史教训（请优先关注，避免重复犯错）：
1. [HIGH] 凡涉及字段类型变更，必须查历史迁移事故并验证数据兼容
2. [HIGH] 涉及 /refund 等资金接口必须验证幂等性
3. [MID] PENDING_REFUND 状态新增时容易漏写 status_history
```

**反向治理**（每月一次）：
- `hit_count = 0` 且超过 90 天 → 归档
- 同一 trigger 反复出现 → 合并
- 错题在黄金集上跑过一次"是否仍能复现"，仍能复现的标 `last_validated = now`

**新增/修改**：
- `test_agents/evolve/lessons_store.py`
- `test_agents/evolve/lessons_curator.py`
- `test_agents/tools/query_lessons_learned.py`
- 修改 `worker_base.py` Worker 启动前注入
- 修改 `save_experience_node`

### 5.2 E4：反馈通道（阶段 3）

**反馈入口**：

| 渠道 | 触发方式 |
|---|---|
| CLI 命令行 | `python -m test_agents --feedback "missed payment risk" --task-id xxx` |
| 报告内嵌结构化链接 | 报告末尾"## 反馈链接"段，含 6 类预定义反馈的快捷命令 |
| 批量标注界面（阶段 4） | 最简 Web UI |

**反馈结构**：

```python
class UserFeedback:
    task_id: str
    tenant: str
    category: Literal["missed_risk", "wrong_term", "weak_evidence", "vague_action", "hallucination", "other"]
    severity: Literal["low", "mid", "high"]
    description: str
    correct_answer: Optional[str]
    submitter: str
    created_at: datetime
```

**反馈→错题本**：
- `severity >= mid` 的反馈自动生成 `LessonRecord`（`source="user_feedback"`）
- 同时触发该 task 进入"候选黄金集"提示

**关键设计**：
- 反馈分类是闭集（6 类），驱动后续"哪类错误占比最高"分析
- 反馈不进黄金集（隔离原始信号与权威答案）

**新增**：
- `test_agents/evolve/feedback.py`
- 修改 `main.py` 增加 `--feedback`
- 修改 `synthesize.md` 增加反馈链接段

### 5.3 E1：经验向量库（阶段 3）

**与 E2 的关系**：E2 是 E1 的特化子集。同一张 `experience_records` 表，用 `record_type` 区分：
- `lesson`：负向经验（错题）
- `success_case`：正向经验（4 维分都 ≥ 0.8 的优秀案例）

**B3 在线沉淀的体现**：
- Worker 执行 + Judge 评分后触发 `distill` 节点
- 自动决定：
  - 分数 < 0.6 任一维度 → 生成 lesson 入库
  - 分数 ≥ 0.8 全部维度 → 生成 success_case 入库
  - 中间分数 → 不入库

**通用经验晋升流程**：
- 默认按 tenant 隔离
- 月度 curator 自动找候选：多 tenant 召回过、效果提升明显、severity=high
- 候选生成"晋升 PR"（yaml 改 `tenant: GLOBAL`）
- **必须人工 review merge** —— 自动晋升禁止

**新增**：
- `test_agents/evolve/experience_store.py`
- `test_agents/evolve/distill.py`
- `test_agents/evolve/promotion.py`
- 修改 `worker_base.py` 增加 distill 节点

### 5.4 E3：Prompt 自动迭代实验台（阶段 4）

**触发条件**：
- 黄金集回归报告中某 case 连续 3 次失败
- 某维度 30 天趋势明显下滑
- 人工触发 `python -m test_agents.evolve.experiment --on prompts/code_analyzer.md`

**实验流程**：

```
1. 失败信号触发
        │
        ▼
2. Proposer Agent
   输入：当前 prompt + 失败 case + Judge 扣分理由
   输出：3-5 个候选改写版本
        │
        ▼
3. 黄金集 A/B 评估（每候选跑完整黄金集）
        │
        ▼
4. 胜者判定
   条件：vs baseline 总分 ↑ 且无单维度 ↓ > 0.05
        │
        ├ 无胜者 → 实验失败，归档，通知人工
        │
        └ 有胜者 → 进入灰度
                │
                ▼
5. 灰度上线
   - 新 prompt 写入 prompts/<name>.candidate.md
   - 接下来 N 次真实任务随机 50% 用新版
   - 在线 Judge 持续打分
   - 一周后看在线数据：胜出→替换主版；落后→回滚
        │
        ▼
6. 实验存档
   data/experiments/<ts>_<prompt_name>/
```

**关键约束**：
- 前置条件：黄金集稳定 + 错题本规模化 + 评估信号可靠
- **不允许全自动上线**：胜者灰度是自动的，主版本替换需要人工 confirm
- **永久禁区**：不对 Judge prompt 实验（避免"Judge 改自己 prompt 决定 Judge 是否变好"的递归陷阱）

**新增**：
- `test_agents/evolve/experiment/proposer.py`
- `test_agents/evolve/experiment/runner.py`
- `test_agents/evolve/experiment/canary.py`
- `data/experiments/`

---

## 6. 多租户身份与存储设计

### 6.1 租户模型

```python
class Tenant:
    tenant_id: str               # "order" / "payment" / "member" / "GLOBAL"
    display_name: str            # "订单组测试分析专员"
    owner_team: str
    created_at: datetime
    modules: List[str]           # 负责的代码模块
    code_paths: List[str]        # 知识抽取范围
    llm_model: str
    judge_model: str
    rules_path: str
    golden_set_path: str
    sop_path: str
    capability_baseline: dict    # 上线时 4 维基线分数

    # 治理补充
    role_spec: RoleSpec          # 见 6.3
```

**特殊租户 `GLOBAL`**：
- 不归属任何团队，存放跨业务通用经验和通用规则
- 任何 tenant 调 `query_lessons_learned` 时自动叠加 tenant_id + GLOBAL
- 只有"通用经验晋升流程"能往 GLOBAL 写入

**租户配置位置**：
```
tenants/
├── order.yaml
├── payment.yaml
├── member.yaml
└── global.yaml
```

**启动方式**：
```bash
python -m test_agents --tenant order "分析订单模块变更"
```

### 6.2 存储分层

| 数据类型 | 介质 | 位置 |
|---|---|---|
| 租户配置 | YAML + git | `tenants/*.yaml` |
| 黄金集 | YAML + git | `eval/golden_set/<tenant>/*.yaml` |
| 规则配置 | YAML + git | `eval/rules/<tenant>.yaml` |
| SOP 策略 | YAML + git | `tenants/<tenant>/sop.yaml` |
| 错题本 / 经验库 | SQLite + Chroma | `experience_records` 表 + `experience_embeddings` 向量集合 |
| 执行历史 | SQLite | `task_runs` 表 |
| 决策日志 | JSONL（追加写） | `data/decision_logs/<tenant>/<date>.jsonl` |
| 能力档案 / 趋势 | JSONL | `data/capability_trend/<tenant>.jsonl` |
| 实验存档 | 文件目录 | `data/experiments/<ts>_<prompt>/` |
| 用户反馈 | SQLite | `feedback` 表 |
| 待审批队列 | SQLite | `approval_queue` 表 |

**为什么 git + SQLite + Chroma + JSONL 的组合**：
- 配置（低频、需 code review、可回溯）→ git
- 运行时数据（高频写、需查询）→ SQLite
- 向量数据 → Chroma（轻量，本地文件即可）
- 顺序追加日志（决策、能力趋势）→ JSONL
- 不引入 PG，等规模需要时再切

### 6.3 治理补充：岗位说明书（role_spec）

**每个 tenant YAML 加 `role_spec` 段**：

```yaml
# tenants/order.yaml
role_spec:
  title: "订单组测试分析专员"
  responsibilities:
    - 代码变更风险分析（仅限 order/cart/checkout 模块）
    - 测试用例质量评审
  boundaries:
    - 不做：需求评审、线上巡检、自动化脚本编写
    - 不做：跨支付模块的变更分析（应转交 payment 员工）
  compliance_red_lines:
    - 凡涉及金额计算必验证精度
    - 凡涉及状态机变更必验证历史数据兼容
  kpi:
    risk_coverage: "≥ 0.85"
    business_term_accuracy: "≥ 0.90"
    evidence_strength: "≥ 0.75"
    action_specificity: "≥ 0.80"
```

**作用**：
- 文档化岗位边界（替代"散落在 prompt 和规则里的隐性共识"）
- KPI 与 4 维评分挂钩，可在运营监控 CLI 中输出"达标/未达标"

### 6.4 治理补充：审计追溯（decision_log）

**问题**：现有 `task_runs` 只存"跑了什么"，不存"为什么这么决定"。当用户问"为什么没报这个风险"时无法回答。

**数据结构**：

```python
class DecisionLog:
    task_id: str
    tenant_id: str
    step: str               # "agent_call" / "tool_call" / "judge" / "rule_check" / "sop_check"
    timestamp: datetime
    decision: str           # "调用 query_similar_bugs，关键词=refund"
    reasoning: str          # "Agent 判断此变更可能涉及退款历史 bug"
    outcome: str            # "召回 3 条相关 bug，#BUG-123 最相关"
    alternatives_considered: List[str]  # ["未调 query_module_history，因模块已确定"]
```

**存储**：追加写 `data/decision_logs/<tenant>/<date>.jsonl`，轻量不阻塞。
**查询**：按 task_id 聚合，还原完整决策链。

**价值**：审计、复盘、E3 prompt 迭代的证据来源。

### 6.5 治理补充：运营监控 CLI

**问题**：YAGNI 排除了大盘，但"无监控就无 SLA"是数字员工与 Agent 的关键差异。

**做法**：CLI 级最小监控：

```bash
python -m test_agents.admin status --tenant order
```

输出示例：
```
员工：订单组测试分析专员（order）
状态：活跃

最近 7 天执行统计：
  任务数: 23 | 成功: 18 | 需人工复核: 5 | 平均耗时: 4m32s

4 维 KPI（最近 30 天均值 vs 目标）：
  风险覆盖率:     0.82 / 0.85 ⚠️ 未达标
  业务术语准确率:  0.91 / 0.90 ✅
  证据强度:       0.78 / 0.75 ✅
  结论可执行性:   0.81 / 0.80 ✅

待处理：
  - 错题本条目: 12（其中 3 条 HIGH 未验证）
  - 待人工复核: 2 条
  - GLOBAL 晋升候选: 1 条

告警：
  ⚠️ 风险覆盖率连续 5 天低于 KPI 目标
```

**实现**：聚合查询 `task_runs` + `experience_records` + `capability_trend` jsonl + `approval_queue`，不需要任何 UI 框架。

### 6.6 数据库 Schema（SQLite，MVP）

```sql
-- 任务执行历史
CREATE TABLE task_runs (
    task_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_request TEXT,
    plan_json TEXT,
    final_report TEXT,
    judge_result_json TEXT,
    escalated_items_json TEXT,
    created_at DATETIME,
    INDEX(tenant_id, created_at)
);

-- 经验库（错题 + 成功案例统一存）
CREATE TABLE experience_records (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    record_type TEXT NOT NULL,      -- lesson / success_case
    source TEXT,
    trigger_module TEXT,
    trigger_keywords TEXT,          -- JSON array
    trigger_embedding_id TEXT,
    scenario_tags TEXT,             -- JSON array
    content_json TEXT,
    severity TEXT,
    hit_count INTEGER DEFAULT 0,
    last_validated DATETIME,
    created_at DATETIME,
    archived BOOLEAN DEFAULT FALSE,
    INDEX(tenant_id, archived, severity),
    INDEX(trigger_module)
);

-- 用户反馈
CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT,
    category TEXT,
    severity TEXT,
    description TEXT,
    correct_answer TEXT,
    submitter TEXT,
    created_at DATETIME,
    converted_to_lesson_id TEXT,
    FOREIGN KEY (task_id) REFERENCES task_runs(task_id)
);

-- 待审批队列
CREATE TABLE approval_queue (
    ticket_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    gate_id TEXT,
    approver_role TEXT,
    context_json TEXT,
    status TEXT,                     -- pending / approved / rejected / timeout
    created_at DATETIME,
    timeout_at DATETIME,
    approved_by TEXT,
    approved_at DATETIME,
    decision_note TEXT,
    FOREIGN KEY (task_id) REFERENCES task_runs(task_id),
    INDEX(tenant_id, status, timeout_at)
);
```

**向量库（Chroma）**：
- 单个 collection：`experience_embeddings`
- metadata 必带 `tenant_id, record_type, severity`
- 查询时用 metadata filter 做租户隔离

### 6.7 多租户隔离的实现

**原则：一切跨租户查询必须显式跨**。

**统一仓储接口示例**：

```python
class ExperienceStore:
    def query(
        self,
        tenant_id: str,
        keywords: List[str] = None,
        embedding: List[float] = None,
        record_type: Literal["lesson", "success_case"] = None,
        include_global: bool = True,
        top_k: int = 3,
    ) -> List[ExperienceRecord]: ...

    def insert(self, tenant_id: str, record: ExperienceRecord) -> str:
        assert tenant_id in self.allowed_tenants
        assert tenant_id != "GLOBAL" or self._is_promotion_context()
```

**关键约束**：
- `tenant_id` 是所有读写的必填参数
- 写入 GLOBAL 必须走晋升流程
- 召回默认 `include_global=True`
- Worker State 携带 `tenant_id`，无全局可变租户态

### 6.8 跨租户场景

**通用经验晋升**：
- 月度 curator 找候选（高 hit_count、跨 tenant 召回过、severity=high）
- 生成晋升候选 YAML 提 PR
- 人工 review merge 后，promotion 脚本复制到 `tenant_id=GLOBAL`

**运维查询**：
- 管理 CLI `python -m test_agents.admin stats --cross-tenant`
- 业务代码路径绝不允许跨租户查询

**员工孵化（新增 tenant）**：
- 复制 `tenants/template.yaml`
- 黄金集冷启动：标 5 个 case
- 错题本冷启动：自动拉取 GLOBAL 所有 lesson
- 跑 baseline 评估写入 `capability_baseline`

---

## 7. 4 阶段交付路线图

### 7.1 阶段 1：核心闭环（4-6 周）

**目标**：建成"评审员 + 黄金集 + 错题本 + 多租户骨架 + 治理基础"的最小三角，让"每改一行 prompt 都能看到分数涨跌"成为可能。

**交付物**：

| 模块 | 范围 |
|---|---|
| 多租户基础设施 | `tenants/*.yaml`（含 role_spec）、`WorkerState.tenant_id`、仓储层 |
| 3 个租户配置 | order / payment / member |
| 评审员 Agent | `agents/judge.py`, `prompts/judge.md`，4 维评分 |
| 规则引擎 | `eval/rule_engine.py`, `eval/rules/<tenant>.yaml`（每 tenant 3-5 条） |
| SOP 策略层 v1 | `sop/enforcer.py` + 只实现 `mandatory_tools` + `force_escalation` |
| Worker 子图改造 | 加 `judge + rule_check + sop_check` 节点 + `escalated_items` |
| 黄金集 v1 | 每 tenant 5 个 case（共 15 个），从真实事故选 |
| Judge 校准集 | 5 case × 人工预期分 |
| 回归运行器 | `eval/runner.py`, `reporter.py`, `baseline.py` |
| 错题本 v1 | `evolve/lessons_store.py`, `tools/query_lessons_learned.py` |
| SQLite schema | `task_runs`, `experience_records`, `feedback` |
| 决策日志 | `data/decision_logs/<tenant>/<date>.jsonl` 追加写 |
| 运营监控 CLI v1 | `python -m test_agents.admin status --tenant <t>` |
| CI 集成 | PR 触发回归 + 评论 |
| Git 抽取骨架 | `knowledge/extractor/git_extractor.py` 抽取 commit message + 文件路径入 Chroma；3 个知识查询工具已注册到 ToolRegistry，但返回结果以"暂无数据"或仅 Git commit 摘要为主，先打通调用链路 |

**验收标准**：
- ✅ `python -m test_agents.eval.run --tenant order` 在 5 分钟内出 4 维分数报告
- ✅ 改 `prompts/code_analyzer.md` 后再跑，HTML 报告能看到 vs baseline 的 delta
- ✅ Judge 校准集上，Judge 分与人工预期分差距 < 0.15
- ✅ 失败执行自动入错题本，下一次同模块任务在 system prompt 看到"⚠️ 历史教训"
- ✅ 任一 Worker 报告末尾看到"⚠️ 待人工复核项"章节
- ✅ `admin status` 能输出员工状态卡片

**不做**：D2/D3 抽取、E4 反馈、E1 完整经验库、E3、A1、approval_gates、外部升级通道

### 7.2 阶段 2：业务感（4-6 周）

**目标**：让报告里能看到具体业务术语和历史 bug 引用，不再像"通用模板"。

**交付物**：

| 模块 | 范围 |
|---|---|
| D2/D3 数据抽取 | `pr_extractor.py`（GitLab/GitHub API） + `bug_extractor.py`（Jira/禅道 API） |
| 知识向量化 pipeline | 抽取 → embedding → Chroma；每日凌晨增量更新 |
| 知识工具集补完 | `query_similar_bugs`, `query_module_history`, `query_pr_discussion` 接通真实数据 |
| 黄金集扩展 | 每 tenant 20-30 个 case |
| B3 在线沉淀 | `evolve/distill.py` Worker 后置节点 |
| SOP `timeouts` 段 | 完善节点鲁棒性 |
| 弱依赖数据源 | D4/D5/D6 能拿多少接多少 |

**验收标准**：
- ✅ Chroma 中至少 5000 条 PR 评论 + 2000 条 bug 单
- ✅ 黄金集执行中平均每 case 调用 ≥1 次知识工具
- ✅ "业务术语准确率"和"证据强度"分数 vs 阶段 1 baseline 提升 ≥ 0.15
- ✅ 黄金集到 20-30 个/tenant
- ✅ 抽样 5 份报告人工 review，"通用模板感"明显下降

### 7.3 阶段 3：反馈闭环（3-4 周）

**目标**：让用户吐槽结构化进入系统，影响下一次执行；让正向经验也能沉淀；上线审批机制。

**交付物**：

| 模块 | 范围 |
|---|---|
| E4 反馈通道 | CLI `--feedback` + 报告内嵌链接 + `feedback.py` 转换器 |
| 反馈分类闭集 | 6 类 |
| E1 经验库扩展 | `success_case` record_type 启用 |
| 月度 curator | `lessons_curator.py` 清理 + `promotion.py` 晋升候选 |
| 通用经验晋升流程 | 文档化的人工 review 流程 |
| SOP `approval_gates` 段 | + `approval_queue` 表 + CLI 审批工具 + 超时定时任务 |
| 能力档案 v1 | `capability_trend/<tenant>.jsonl` 每日累积 + `admin profile` CLI |

**验收标准**：
- ✅ 任意执行后用户可通过 1 条 CLI 命令提交反馈
- ✅ severity=mid/high 反馈自动转 lesson 入库
- ✅ 月度 curator 跑一次能输出归档统计 + 晋升候选清单
- ✅ CLI 输出某 tenant 最近 30 天 4 维分数曲线
- ✅ 至少完成 1 次端到端"通用经验晋升"演练
- ✅ 至少完成 1 次端到端"审批拦截→人工 approve/reject→任务继续"演练

### 7.4 阶段 4：自主进化（开放周期）

**目标**：从"人工调 prompt"过渡到"系统提议改进 + 人工把关"；启动 A1 提升天花板。

**交付物**：

| 模块 | 范围 |
|---|---|
| E3 实验台 | `experiment/proposer.py`, `runner.py`, `canary.py` |
| 实验触发条件 | 自动（连续 3 次失败、30 天某维度下滑） + 手动 CLI |
| 灰度机制 | `prompts/<name>.candidate.md` + 50/50 A/B + 人工 confirm |
| 实验存档 | `data/experiments/` 完整审计链 |
| A1 checklist 扩容 | code_analyzer prompt 加入"性能/安全/兼容/数据/权限"五维强制扫描；与 A2 共存 |
| 能力档案 v2 | 增加"实验成功率"、"prompt 演化史" |
| SOP `escalation_channels` 外部通道 | 飞书 webhook 等 |

**验收标准**：
- ✅ 完成至少 1 次完整实验闭环：失败信号 → 候选生成 → A/B → 灰度 → confirm 上线
- ✅ 实验存档可追溯（"过去 3 个月这个 prompt 的演变与各版分数"）
- ✅ A1 checklist 上线后"风险覆盖率"+0.1 以上
- ✅ 数字员工档案能输出"季度成长报告"

**永久禁区**：
- 自动改 Judge prompt
- 自动上线（永远需要人工 confirm）

### 7.5 全局时间线

```
阶段 1 ──────────────  4-6 周   [核心闭环]
   │
阶段 2 ──────────────  4-6 周   [业务感]
   │
阶段 3 ────────────    3-4 周    [反馈闭环 + 审批]
   │
阶段 4 ──────────  开放          [自主进化]
                                 ↓
                            进入"持续运转"稳态
```

**关键检查点**：
- 阶段 1 末必须能演示"改 prompt → 看分数"，否则**不进阶段 2**
- 阶段 2 末黄金集 4 维分数必须有明确提升数据，否则**回头优化阶段 1**
- 阶段 3 末必须完成端到端的反馈闭环和审批闭环演练
- 阶段 4 每个实验独立交付，不规定整体完成时间

---

## 8. 与现有代码的兼容性

**不需要重写现有代码**，只做加法和小幅改造：

| 现有模块 | 改造方式 |
|---|---|
| `intent_classifier`, `planner`, `dispatch` | 不动（State 加 `tenant_id` 字段透传） |
| `code_analyzer`, `case_reviewer` worker | 接收 `tenant_id`；调知识工具集；启动前注入高 severity 错题 |
| `worker_base.py` | 子图加 `judge + rule_check + sop_check + distill` 四个新节点 |
| `reflect_node` | 保留，只做流程决策（replan/complete） |
| `save_experience_node` | 改造为"失败→错题本，成功→success_case"的分发器 |
| `SupervisorState` / `WorkerState` | 加 `tenant_id`, `judge_result`, `escalated_items`, `approval_pending` |
| 现有 prompts | 不动，未来由 E3 实验台改 |
| `confirm_plan` 的 interrupt 机制 | 复用扩展为 SOP `approval_gates` |

---

## 9. 不在本设计范围内的事（YAGNI）

- ❌ Web UI（CLI 已够 MVP，UI 留给规模化阶段）
- ❌ 多模型路由（按 tenant 配 model 已足够，复杂路由是后话）
- ❌ 跨员工协作机制（订单 ask 支付员工，复杂度爆表）
- ❌ 自动孵化新员工（新增 tenant 仍为人工操作）
- ❌ 实时监控大盘（用 jsonl + CLI 输出即可）
- ❌ 模型微调 LoRA/RLHF（prompt + RAG + 错题本天花板未达，过早 fine-tune 是浪费；列入未来路径）
- ❌ SOP DSL 可视化编辑器（防止滑向方案 B 的 DSL 陷阱）
- ❌ 流程顺序变更工具化（流程骨架属于工程师，不由业务方改）
- ❌ 自动改 Judge prompt（永久禁区）
- ❌ 自动上线 prompt（永远需要人工 confirm）

---

## 10. 未来路径（不在本期，但保留思考）

| 方向 | 触发条件 |
|---|---|
| LoRA 微调 | prompt + RAG + 错题本均已优化到天花板，仍无法在某场景达到 KPI |
| 跨员工协作 | 单员工 KPI 稳定 ≥ 0.85 后；订单变更跨支付域需联合分析时 |
| Web UI | 审批用户/反馈用户达到 10+ 人/日；CLI 操作成为瓶颈 |
| 实时大盘 | 员工实例 ≥ 10 个；运营成本需要可视化抓手 |
| 自动孵化新 tenant | 业务方主动提"我们要给 X 业务线建数字员工"的频率 ≥ 1 次/月 |

---

## 11. 风险与守住的事

| 风险 | 守住的事 |
|---|---|
| 黄金集只标 5 个不够全面 | 接受不完美，建信号通路；阶段 2 扩到 20-30 |
| Judge 可能不准 | 校准集机制；校准不通过阻塞上线 |
| 错题本无限增长 | 月度 curator 清理 + 归档机制 |
| 知识抽取 pipeline 数据不全 | R3 工具化 + Judge 兜底；不全也能跑，逐步补 |
| SOP DSL 陷阱 | 只表达"策略"不表达"流程顺序"；YAML 5 段封闭，不扩展 |
| 审批阻塞导致用户绕过 | 超时机制 + 升级通道；不允许"无超时审批" |
| Prompt 自动迭代污染主版 | 灰度 + 人工 confirm 双闸门；永不自动上线 |
| 跨租户经验串味 | 默认隔离 + 显式晋升 + 人工 review merge |

---

## 11.1 后续实现计划文档承接

本 spec 覆盖 4 阶段范围，单一实现计划承接不了全部。后续将拆为 4 份独立 plan 文档分别承接：

- `docs/superpowers/plans/<date>-digital-employee-phase1-core-loop.md`
- `docs/superpowers/plans/<date>-digital-employee-phase2-business-sense.md`
- `docs/superpowers/plans/<date>-digital-employee-phase3-feedback-loop.md`
- `docs/superpowers/plans/<date>-digital-employee-phase4-self-evolution.md`

每阶段 plan 在前一阶段验收通过后再启动撰写，避免过早设计被后续学习推翻。

## 12. 总结

本设计将 test_agents 项目从"工具型 Agent"演进为"专家型测试数字员工"，核心补齐三层能力：

1. **执行层**：评审员 + 规则引擎 + SOP 策略层 + 知识工具集，让"会承认无知 + 业务感强 + 流程可控"成为可能
2. **评估层**：黄金集 + 4 维 Judge + 回归门禁，让"质量可量化、可回归、可比较"成为日常
3. **进化层**：错题本 → 反馈 → 经验库 → prompt 实验，让"每天比昨天聪明一点"成为闭环

辅以**多租户、岗位说明书、审计追溯、运营监控**四项治理设施，让其真正"像正式员工一样可管理"。

按 P2 最小闭环节奏分 4 阶段交付，每阶段独立可验收，确保每一步都建立在可验证的信号上。
