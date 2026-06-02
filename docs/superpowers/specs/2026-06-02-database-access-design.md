# 数据库访问能力设计（Data Analyst Worker）

日期：2026-06-02
状态：Draft（待 review）
作者：Claude Code（与 hl929 协作）

## 背景

当前 Test Agents v3 支持两类 Worker：
- `code_analyzer`：分析代码变更（绑定 `claude_cli` + 文件系统工具）
- `case_reviewer`：评审测试用例（绑定 `claude_cli` + `parse_test_cases` + `query_business_knowledge`）

用户希望 Agent 能访问 MySQL 数据库，基于测试执行结果、缺陷数据、代码覆盖率、CI/CD 流水线等数据，生成测试相关的数据洞察报告（趋势分析、风险评估、数据洞察）。

## 目标

- 新增 `data_analyst` Worker，与现有 Worker 完全平行
- Agent 可直接执行 MySQL 只读查询，获取多轮数据后生成自然语言洞察报告
- 支持多次 SQL 查询（探索 schema → 查数据 → 深度分析）
- 三层安全防控：SQL 白名单 + 连接层只读 + 环境变量隔离
- 复用现有 Plan-and-Solve + Reflection 架构， Supervisor 调度，Worker 内 ReAct 循环
- Prompt 引导 Agent 先制定分析计划，再逐步执行查询（Plan-guided ReAct）

## 非目标

- 不支持写操作（INSERT/UPDATE/DELETE/DDL），Agent 仅做数据洞察
- 不实现通用 BI 可视化，输出为自然语言报告
- 不走独立数据服务/MCP，直接嵌入现有 LangGraph 状态流
- 不做运行时 schema 自动推断（依赖预编写的 schema 描述文件）
- 不替代现有 BI/报表系统，定位为"Agent 驱动的临时数据探索"

## 方案选型

### Worker 内部模式对比

| 候选 | 架构一致性 | 多轮查询灵活性 | LLM 成本 | 实现复杂度 | 结论 |
|---|---|---|---|---|---|
| A. ReAct（现有模式）| 高 | 高（动态调整）| 中（每步 LLM 决策）| 低（复用 `build_worker_graph`）| **采纳** |
| B. Worker 内嵌 Plan-and-Solve | 低（与 Supervisor 层级重复）| 中（计划固定后难调整）| 低 | 高（需全新子图）| 否 |
| C. Plan-guided ReAct（最终采纳）| 高 | 高（Prompt 强制先计划）| 中 | 低（仅改 Prompt）| **最终采纳** |

**最终方案：ReAct + Prompt 引导 Agent 先制定分析计划。**

理由：
- Supervisor 已是宏观 Plan-and-Solve，Worker 再做一层会导致职责混淆
- 数据洞察任务需要动态调整（第一轮查询结果影响第二轮 SQL），ReAct 更灵活
- 通过 Prompt 强制 Agent 首轮输出分析计划，兼具"先规划、少弯路"的优势
- 100% 复用现有 `build_worker_graph`，零架构侵入

### 数据总结节点归属

| 节点 | 职责 |
|---|---|
| `data_analyst` agent | 持有全部原始查询结果，负责"数据 → 洞察 → 自然语言报告" |
| Supervisor `synthesize` | 多 Worker 场景下整合各 Worker 报告为统一最终答案 |

单 Worker 场景：`data_analyst` 输出完整报告，`synthesize` 直接透传。
多 Worker 场景（如 `code_analyst` + `data_analyst`）：`synthesize` 跨 Worker 关联分析。

## 架构

### 新增文件

```
test_agents/
├── agents/
│   └── data_analyst.py          # Worker 包装器（与 code_analyzer.py 平行）
├── tools/
│   ├── database.py              # QueryDatabaseTool（MySQL 只读查询）
│   └── schema_loader.py         # SchemaDescriptionTool（加载表结构描述）
├── prompts/
│   └── data_analyst.md          # Data Analyst 系统 Prompt
└── data/schema/                 # 预编写表结构描述文件
    ├── test_execution.md
    ├── defects.md
    ├── coverage.md
    └── cicd.md
```

### 修改文件

```
test_agents/
├── graph/builder.py             # 注册 data_analyst Worker，路由增加 data_analyst 分支
├── agents/supervisor.py         # route_from_dispatch 增加 data_analyst 判定
├── config.py                    # 新增数据库连接环境变量
└── graph/state.py               # 无需修改（outputs 泛化字典已支持任意 output_key）
```

### 数据流架构

```
用户请求 → planner → confirm_plan → dispatch → data_analyst → reflect → synthesize → save_experience
                                              ↑___________________↓

data_analyst Worker 子图（ReAct + Reflection + Prompt 计划引导）：

START → agent[制定计划] → agent[调用 describe_schema] → tools → agent[生成SQL] → tools[query_database]
            ↓                                                                  ↑
            └──────────── agent[分析结果/生成报告] → reflect → (worker_route) ──┘
                           ↓___________________________________________________↑
```

## Worker 设计

### `data_analyst` Worker 绑定工具

```python
["query_database", "describe_schema"]
```

- `query_database`：执行 MySQL 只读查询
- `describe_schema`：获取表结构描述（帮助 Agent 理解字段含义）

### Supervisor 路由

`route_from_dispatch` 增加分支：

```python
if agent == "data_analyst":
    return "data_analyst"
```

### Worker 输入构建

复用 `build_worker_task()`，`input_mapping` 可传入：
- `module_name`：分析目标模块
- `time_range`：时间范围
- `metrics`：关注指标列表

## 工具规格

### `query_database`

执行 MySQL 只读 SQL 查询，返回 Markdown 表格。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `query` | str | 必填 | 待执行的 SQL 语句 |

**安全校验（执行前严格检查）：**
1. 去除首尾空白后，必须以 `SELECT` 开头（不区分大小写）
2. 禁止关键字（正则匹配，不区分大小写）：`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `EXEC`, `CALL`, `INTO OUTFILE`, `LOAD_FILE`
3. 禁止分号 `;`（防止多语句注入）
4. 禁止 `--` 和 `/* */` 注释（防止注入绕过）
5. 自动限制返回行数：无 `LIMIT` 时自动追加 `LIMIT 500`；有 `LIMIT` 时若值 > 500 则截断为 500
6. 查询超时：30 秒

**MySQL 连接：**
- 驱动：`pymysql`（纯 Python，无需系统安装 `mysql-client`）
- 连接串来源：环境变量 `TEST_AGENTS_DB_URL`
- 格式：`mysql+pymysql://user:pass@host:port/db?connect_timeout=10`
- 连接层只读：通过 `default_transaction_read_only=on` 或只读账号（建议）

**为什么用 pymysql 而不是 mysql 命令行：**
- 纯 Python 依赖，无需系统预装 `mysql-client`
- 查询结果直接返回 Python 数据结构，转 Markdown 表格更简单
- 错误信息结构化（`pymysql.Error`），便于 Agent 理解并修正 SQL
- 超时控制更精细（`connect_timeout` + `read_timeout`）
- 避免命令行传密码在进程列表中暴露的风险

**输出格式：**
- 成功：Markdown 表格（列头 + 数据行），最多 500 行
- 失败：错误信息字符串（如 `SQL rejected: only SELECT statements allowed`、`Query timeout: please simplify your query`）

### `describe_schema`

返回数据库表结构描述，帮助 Agent 理解可用字段。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `table_name` | str | "" | 表名，不传则返回所有核心表概览 |

**实现：**
- 从 `data/schema/` 目录加载预编写的 Markdown 描述文件
- 文件命名与表名一致（如 `defects.md`）
- 每个描述文件包含：表用途、字段列表（名称、类型、含义）、常用查询示例、注意事项
- 未找到指定表 → 返回可用表列表

**预编写 Schema 描述的优势：**
- 比 `information_schema` 查询更可控、更准确
- 可附加业务含义（如"该字段存储的是缺陷创建时间，非修复时间"）
- 避免 Agent 在列名猜测上浪费轮次

### `data_analyst.md` Prompt 核心设计

系统 Prompt 要点：

```markdown
# 角色
你是测试数据分析师，专注于从 MySQL 数据库中提取测试相关的数据洞察。

# 工作流程（必须遵守）
1. **制定分析计划**：在调用任何工具前，先明确回答以下问题：
   - 需要查询哪些表？
   - 需要计算哪些关键指标？
   - 时间范围和过滤条件是什么？
   将计划写入你的 reasoning。
2. **探索表结构**：如果不确定字段含义，先调用 `describe_schema`。
3. **执行查询**：一次可执行一条 SQL，根据结果决定是否需要补充查询。
4. **生成报告**：汇总所有查询结果，输出自然语言洞察报告。

# SQL 规范
- 只生成 SELECT 语句，禁止任何写操作
- 复杂查询优先使用 JOIN 和聚合函数
- 时间范围过滤必须包含，避免全表扫描
- 如无 LIMIT，系统会自动追加 LIMIT 500

# 输出要求
- 自然语言报告，包含数据结论、趋势判断和风险提示
- 如果查询无结果，明确说明"未找到符合条件的数据"，不得猜测
- 报告结构建议：摘要 → 关键发现 → 趋势分析 → 风险建议

# 安全提醒
- 你生成的 SQL 会经过安全校验，非 SELECT 语句会被拒绝
- 如果 SQL 被拒绝，请检查是否包含写操作或危险关键字
```

## 数据流（详细示例）

**用户请求：**"分析过去30天支付模块的缺陷趋势"

### Step 1: Planner 生成计划

```json
{
  "intent": "分析支付模块缺陷趋势",
  "steps": [
    {
      "step_id": 1,
      "agent": "data_analyst",
      "description": "查询过去30天支付模块的缺陷数据，按日期聚合统计每日新增缺陷数、已修复数、严重缺陷数，分析趋势并识别风险。",
      "output_key": "data_insight_report"
    }
  ]
}
```

### Step 2: 用户确认计划

`confirm_plan_node` 暂停，用户确认后 `plan.confirmed = true`。

### Step 3: Dispatch 构建 Worker 输入

```python
worker_input = {
    "task": "查询过去30天支付模块的缺陷数据...",
    "messages": [HumanMessage(content="查询过去30天支付模块的缺陷数据...")],
    "output_key": "data_insight_report",
    "error": "no",
    "reflection_count": 0,
    "max_reflections": 0,
    "result": ""
}
```

### Step 4: data_analyst 子图执行（ReAct 循环）

**第1轮 - agent 制定计划：**
```
我需要分析支付模块的缺陷趋势，计划如下：
1. 先了解 defects 表结构
2. 查询过去30天支付模块的缺陷数据，按日期聚合
3. 分析严重缺陷占比
4. 生成趋势报告
```
不调用工具，纯 reasoning。

**第2轮 - agent 调用 `describe_schema`：**
```python
{"table_name": "defects"}
```
tools 返回 `defects.md` 内容（字段：id, module, title, severity, status, created_at, resolved_at）。

**第3轮 - agent 调用 `query_database`：**
```sql
SELECT DATE(created_at) AS date,
       COUNT(*) AS total,
       SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) AS critical_count,
       SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved_count
FROM defects
WHERE module='payment' AND created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY DATE(created_at)
ORDER BY date
```
tools 返回 Markdown 表格（30行数据）。

**第4轮 - agent 补充查询（发现某几天缺陷激增）：**
```sql
SELECT title, severity, created_at
FROM defects
WHERE module='payment' AND severity='critical'
  AND created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
ORDER BY created_at DESC
LIMIT 50
```
tools 返回激增日期附近的详细缺陷列表。

**第5轮 - agent 生成最终报告：**
```
## 支付模块缺陷趋势分析（过去30天）

### 摘要
- 总缺陷数：XX 个，日均 X.X 个
- 严重缺陷占比：XX%，其中第 X 天出现峰值
...
```

**第6轮 - worker_reflect：**
评估报告是否回答了趋势和风险问题 → 通过 → `error: "no"` → `__end__`。

### Step 5: 结果聚合

`data_analyst_wrapper` 提取 `result`，写入 `state["outputs"]["data_insight_report"]`。

### Step 6: Supervisor Reflect

`reflect_node` 评估 `data_insight_report` 质量。若满意 → `needs_replan: false`。

### Step 7: Synthesize

`synthesize_node` 汇总输出最终答案（单 Worker 时直接透传）。

### Step 8: Save Experience

记录本次计划和执行经验到 `data/reflection_experience.md`。

## 安全策略

### 三层防护

| 层级 | 机制 | 实施位置 |
|---|---|---|
| 1. SQL 白名单 | 只允许 SELECT；禁止写关键字；禁止多语句 | `QueryDatabaseTool._invoke()` |
| 2. 连接层只读 | `default_transaction_read_only=on` 或只读账号 | MySQL 服务端配置 |
| 3. 环境变量隔离 | 连接串不走代码，通过 `TEST_AGENTS_DB_URL` 注入 | 运行时环境 |

### SQL 校验详细规则

```python
def _validate_sql(query: str) -> tuple[bool, str]:
    """返回 (is_valid, error_message)"""
    cleaned = query.strip()

    # 必须以 SELECT 开头
    if not cleaned.upper().startswith("SELECT"):
        return False, "SQL rejected: query must start with SELECT"

    # 禁止危险关键字
    forbidden = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|CALL|'
        r'INTO\s+OUTFILE|LOAD_FILE)\b',
        re.IGNORECASE
    )
    if forbidden.search(cleaned):
        return False, "SQL rejected: forbidden keyword detected"

    # 禁止分号
    if ';' in cleaned:
        return False, "SQL rejected: multiple statements not allowed"

    # 禁止注释
    if '--' in cleaned or '/*' in cleaned:
        return False, "SQL rejected: comments not allowed"

    return True, ""
```

### 行数限制

```python
def _add_limit(query: str, max_rows: int = 500) -> str:
    """如无 LIMIT 则自动追加；有 LIMIT 则截断到 max_rows"""
    # 解析现有 LIMIT
    limit_match = re.search(r'\bLIMIT\s+(\d+)\s*$', query, re.IGNORECASE)
    if limit_match:
        existing = int(limit_match.group(1))
        if existing > max_rows:
            return query[:limit_match.start()] + f" LIMIT {max_rows}"
        return query
    return f"{query} LIMIT {max_rows}"
```

## 错误处理

| 场景 | 处理策略 |
|---|---|
| 数据库连接失败 | 捕获 `pymysql.Error`，返回 `"Database connection failed: {error}"`；Worker reflect 触发重试（最多1次） |
| SQL 被安全规则拦截 | 返回 `"SQL rejected: {reason}"`，Agent 收到反馈后重写 SQL |
| 查询超时（>30s） | 返回 `"Query timeout: please simplify your query or add stricter filters"` |
| 查询结果为空 | 返回空表格 + `"No data found for the given criteria"`，Agent 据此调整查询或如实报告 |
| Schema 描述文件缺失 | `describe_schema` 返回可用表列表，提示用户补充描述文件 |
| 行数被截断 | 返回结果末尾追加 `⚠️ 结果已截断至 500 行，请添加更严格的过滤条件` |
| Agent 生成无效 SQL | MySQL 语法错误 → 返回 `"SQL error: {mysql_error}"` → Agent 修正 |

## 配置

新增环境变量（`test_agents/config.py`）：

| 变量 | 说明 | 默认 | 必填 |
|---|---|---|---|
| `TEST_AGENTS_DB_URL` | MySQL 连接串 | — | 是 |
| `TEST_AGENTS_DB_QUERY_TIMEOUT` | 查询超时（秒）| 30 | 否 |
| `TEST_AGENTS_DB_MAX_ROWS` | 最大返回行数 | 500 | 否 |
| `TEST_AGENTS_SCHEMA_DIR` | Schema 描述文件目录 | `data/schema` | 否 |

示例 `.env`：
```bash
TEST_AGENTS_DB_URL=mysql+pymysql://readonly_user:password@localhost:3306/test_db?connect_timeout=10
TEST_AGENTS_DB_QUERY_TIMEOUT=30
TEST_AGENTS_DB_MAX_ROWS=500
```

## 测试策略

| 测试类型 | 文件 | 内容 |
|---|---|---|
| **单元测试** | `test_agents/tests/test_database_tool.py` | Mock `pymysql.connect` 验证 SQL 白名单（允许 SELECT / 拒绝 INSERT/UPDATE/DELETE）、LIMIT 自动追加、超时处理、空结果处理 |
| **单元测试** | `test_agents/tests/test_schema_loader.py` | 验证 `describe_schema` 加载文件、缺失表处理、多表概览 |
| **集成测试** | `test_agents/tests/test_integration.py`（扩展） | Mock `data_analyst_graph` 验证 Supervisor → `data_analyst` → `reflect` → `synthesize` 全链路 |
| **Worker 测试** | `test_agents/tests/test_data_analyst.py` | 验证 `data_analyst_wrapper` 状态转换、结果提取、output_key 写入 |
| **路由测试** | `test_agents/tests/test_supervisor.py`（扩展） | 验证 `route_from_dispatch` 对 `data_analyst` 的正确路由 |
| **Prompt 测试** | `test_agents/tests/test_prompts.py`（扩展） | 验证 `data_analyst.md` 可被正确加载 |

### 测试依赖

- `pymysql` 需加入 `requirements.txt`
- 单元测试全程 Mock 数据库连接，不依赖真实 MySQL 实例
- E2E 测试可选使用 `testcontainers` 启动 MySQL 容器，或继续使用 Mock

## 依赖变更

`requirements.txt` 新增：
```
pymysql>=1.1.0
```

## Schema 描述文件模板

`data/schema/defects.md` 示例：

```markdown
# 表：defects（缺陷表）

## 用途
存储测试过程中发现的缺陷记录。

## 字段

| 字段名 | 类型 | 含义 |
|---|---|---|
| id | INT | 缺陷唯一编号 |
| module | VARCHAR(64) | 所属模块，如 'payment', 'order', 'user' |
| title | VARCHAR(256) | 缺陷标题 |
| severity | ENUM('critical', 'major', 'minor', 'trivial') | 严重程度 |
| status | ENUM('new', 'in_progress', 'resolved', 'closed', 'reopened') | 状态 |
| created_at | DATETIME | 创建时间 |
| resolved_at | DATETIME | 修复时间（未修复为空）|

## 常用查询

- 按模块统计缺陷数：`SELECT module, COUNT(*) FROM defects GROUP BY module`
- 严重缺陷趋势：`SELECT DATE(created_at), COUNT(*) FROM defects WHERE severity='critical' GROUP BY DATE(created_at)`

## 注意事项
- `resolved_at` 可能为 NULL，计算修复时长时需处理
- `status` 变更需关联操作日志表 `defect_history`
```

## 实施范围

本次设计聚焦新增 `data_analyst` Worker 及其配套工具，不涉及：
- Supervisor 宏观调度逻辑修改（仅增加路由分支）
- 现有 `code_analyzer` / `case_reviewer` 改动
- 前端/UI 可视化
- 数据库 schema 迁移或数据导入（假设目标数据库已就绪）