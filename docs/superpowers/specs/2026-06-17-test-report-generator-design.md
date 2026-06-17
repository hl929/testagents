# 测试报告生成服务设计文档

**日期:** 2026-06-17
**状态:** 设计中
**范围:** 在 Test Agents v3 中新增 `test_report_generator` Worker，支持基于模板和多格式测试数据自动生成 Markdown 测试报告。

---

## 1. 目标

- 用户上传包含测试数据的文件（txt / xlsx / csv 等），指定业务线和报告模板
- Supervisor 调度 `test_report_generator` Worker
- Worker 构建超级 Prompt，通过 `claude -p` 一次性让 Claude CLI 读取数据文件和模板，生成 Markdown 测试报告
- 缺失数据在报告内用 `[待补充：<描述>]` 标注，由用户后续手动补全
- 生成的报告保存到 `reports/<业务线>/<timestamp>-<模板名>.md`

---

## 2. 架构

在现有 `Plan-and-Solve + Reflection` 架构中新增一条链路：

```
用户请求（文件路径 + 业务线 + 模板名）
  → Supervisor: intent_classifier → planner → confirm_plan → dispatch
    → test_report_generator Worker (ReAct + Reflection 子图)
      1. Wrapper 预处理：若 file 为 xlsx，pandas 转为文本表格；其余格式保留路径
      2. 加载 test_report skill prompt（system prompt 模板）
      3. 构建最终 prompt（skill 指令 + 文件内容/路径 + 模板路径 + 生成要求）
      4. Tool: claude_cli(最终 prompt) → stdout 即为 MD 报告
      5. Tool: save_report(md_content, business_line, template_name) → 写入 reports/<业务线>/<timestamp>.md
    → 产出写入 SupervisorState.outputs["test_report"]
  → Supervisor: reflect → synthesize → save_experience
```

**关键原则：** Worker 不自己解析文件或填充模板，而是把所有上下文拼进 prompt 交给 `claude -p` 处理。

---

## 3. 组件

### 3.1 Worker 包装器

新建 `test_agents/agents/test_report_generator.py`，仿照 `code_analyzer.py`：

- 接收 `SupervisorState` + plan step
- 提取 `file_path`、`business_line`、`template_name`
- xlsx 预处理（pandas 读前 N 行转文本），其余格式直接保留路径
- 加载 `test_report_generator.md` skill prompt
- 构建 `task` + `messages`，通过 `build_worker_graph()` 启动 Worker 子图
- 子图绑定工具：`claude_cli`、`save_report`

### 3.2 工具

| 工具名 | 职责 | 输入 | 输出 |
|---|---|---|---|
| `claude_cli` | 复用现有 `ClaudeCliTool` | prompt 文本 | MD 报告字符串 |
| `save_report` | 保存 MD 报告到本地目录 | content, business_line, template_name | file_path |

`save_report` 细节：
- 输出目录：`reports/<business_line>/`（自动创建）
- 文件名：`{YYYYMMDD-HHMMSS}-{template_name}.md`
- 返回 `{"file_path": "/abs/path/to/file.md"}`

### 3.3 Prompt

新建 `test_agents/prompts/test_report_generator.md`：

```markdown
你是测试报告生成专家。请根据以下信息生成测试报告：

【测试数据】
{test_data_content_or_path}

【报告模板】
{template_content_or_path}

【要求】
1. 严格按照模板结构填充内容
2. 如果模板中某部分对应的数据缺失，用 [待补充：<缺失项描述>] 标注
3. 生成完整的 Markdown 格式测试报告
4. 不要省略模板的章节，保持结构完整
```

Worker wrapper 调用 `load_prompt("test_report_generator", ...)` 填入变量。

### 3.4 模板存储规范

```
templates/
├── order/              # 业务线目录
│   ├── summary.md      # 模板文件
│   └── detail.md
└── payment/
    └── regression.md
```

- 目录名 = `business_line`
- 文件名（不含 `.md`）= `template_name`
- 模板内占位符用自由文本描述，不强制 `${...}` 语法

### 3.5 状态变更

- `IntentExtraction.needs_test_report: bool = Field(default=False, ...)`
- `PlanStep.agent` 允许 `"test_report_generator"`
- `dispatch_node` / `route_from_dispatch` 支持路由到 `test_report_generator`

---

## 4. 数据流

以请求 `"用 order/summary 模板，根据 /tmp/test_data.xlsx 生成测试报告"` 为例：

1. **SupervisorState 初始化**
   - `user_request = "..."`
   - `outputs = {}`

2. **Planner 生成 ExecutionPlan**
   ```json
   {
     "steps": [{
       "step_id": 1,
       "agent": "test_report_generator",
       "description": "根据上传的测试数据生成测试报告",
       "input_mapping": {
         "file_path": "/tmp/test_data.xlsx",
         "business_line": "order",
         "template_name": "summary"
       },
       "output_key": "test_report"
     }]
   }
   ```

3. **confirm_plan → dispatch → worker_input**
   - `task`: `"根据上传的测试数据生成测试报告"`
   - `messages`: `[HumanMessage(content="测试数据: /tmp/test_data.xlsx\n业务线: order\n模板: summary")]`
   - `output_key`: `"test_report"`

4. **Worker 子图执行**
   - `agent` → `claude_cli`（prompt 含数据 + 模板路径 + skill 指令）
     - `claude -p` 读取文件 → 返回 MD 报告
   - `agent` → `save_report`（content, `"order"`, `"summary"`）
     - 写入 `reports/order/20250617-103045-summary.md`
   - `reflect` → 质量通过 → `END`

5. **aggregate_worker_result**
   - `SupervisorState.outputs["test_report"] = md_content`

6. **Supervisor reflect → synthesize → 最终答案**

---

## 5. 错误处理

| 场景 | 处理方式 |
|---|---|
| 文件不存在 | `claude -p` 返回错误，Worker `reflect` 检测空/错误结果，error 重试；超限后返回错误摘要 |
| 模板不存在 | Worker wrapper 构建 prompt 前检查路径，不存在直接构建 error result，不调用 `claude_cli` |
| xlsx 预处理失败 | 跳过预处理，保留路径让 CLI 自行处理；CLI 无法解析则返回错误 |
| `claude -p` 超时/失败 | 复用现有超时和重试机制，失败后返回错误信息 |
| 报告内容为空 | `reflect` 检测到空 result，判定失败，重试或标记失败 |
| 缺失项过多 | 正常输出，报告内包含 `[待补充：xxx]`，由用户后续人工补全 |

---

## 6. 边界情况

1. **大文件**：xlsx > 10MB 时，pandas 预处理可能 OOM。限制预处理最大行数（5000 行），超限则跳过预处理直接传路径。
2. **模板变量**：模板中 `${placeholder}` 语法由 `claude -p` 自行识别替换，Worker 不预处理。
3. **多次生成**：同业务线同模板多次调用时，文件名用 timestamp 区分，不覆盖旧文件。
4. **非结构化 txt**：如日志文件无明确格式，`claude -p` 自行理解内容，Worker 不做假设。
5. **路径安全**：`save_report` 中 `business_line` 仅允许 `[a-zA-Z0-9_-]+`，防止路径穿越。

---

## 7. 测试策略

- **Worker 单元测试**：Mock `claude_cli` 和 `save_report`，验证 wrapper 构建 prompt 的逻辑、xlsx 预处理分支
- **集成测试**：用真实 xlsx + 模板文件跑完整 Worker 子图，验证输出文件存在且内容包含预期章节
- **边界测试**：文件不存在、模板不存在、空 xlsx、超大 xlsx 等场景
- **路由测试**：验证 Supervisor 路由 `test_report_generator` 正确走到新 Worker 节点

---

## 8. 文件变更清单

| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `test_agents/agents/test_report_generator.py` | Worker 包装器 |
| 新增 | `test_agents/tools/save_report.py` | SaveReportTool |
| 新增 | `test_agents/prompts/test_report_generator.md` | Skill prompt |
| 新增 | `templates/` | 业务线模板目录（gitignored 或 tracked 视项目决定） |
| 新增 | `reports/` | 报告输出目录（gitignored） |
| 修改 | `test_agents/graph/state.py` | `IntentExtraction` 新增 `needs_test_report` |
| 修改 | `test_agents/agents/supervisor.py` | `route_from_dispatch` 支持 `test_report_generator`；`_default_output_key` 新增映射 |
| 修改 | `test_agents/agents/worker_base.py` | `build_worker_task` 支持新 input_mapping 字段（如有需要） |
| 修改 | `test_agents/graph/builder.py` | 注册 `test_report_generator` Worker 子图 |
| 新增 | `test_agents/tests/test_test_report_generator.py` | Worker 单元 + 集成测试 |

---

## 9. 未来扩展

- **平台化**：前端上传文件 → API 接收 → 触发 Supervisor，报告生成后返回下载链接
- **模板管理 UI**：业务线模板增删改查，模板内占位符可视化编辑
- **报告版本管理**：同一批次多次生成，保留历史版本
- **报告审阅**：生成后进入审阅态，支持人工在线编辑缺失项并重新保存
