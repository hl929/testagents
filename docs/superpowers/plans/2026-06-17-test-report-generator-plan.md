<!-- /autoplan restore point: /home/hl/.gstack/projects/testagents/main-autoplan-restore-20260617-110605.md -->
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

## GSTACK REVIEW REPORT

Generated by /autoplan on 2026-06-17.
Branch: main | Mode: SELECTIVE EXPANSION | Codex: unavailable [single-model]

---

## Phase 1: CEO Review (Strategy & Scope)

### 0A. Premise Challenge

**Premises evaluated:**

1. **Users need automated test report generation from structured data files.** — VALID. The existing system handles code analysis and case review but has no path for producing human-readable test reports from raw data. This fills a real gap.

2. **`claude -p` is the right tool to do the actual report generation.** — VALID with caveats. Offloading template filling and Markdown generation to Claude CLI avoids building a template engine. The tradeoff: we depend on the CLI being installed and responsive. Acceptable for v3 architecture which already uses `claude_cli` extensively.

3. **Missing data should be annotated in-place rather than blocking generation.** — VALID. This keeps the automation flowing and surfaces gaps explicitly for human triage. Better than failing silently or producing incomplete-looking reports.

### 0B. Existing Code Leverage

| Sub-problem | Existing Code | Reuse?
|---|---|---|
| Worker subgraph lifecycle | `build_worker_graph()` in `worker_base.py` | Yes — identical pattern
| Worker → Supervisor result aggregation | `aggregate_worker_result()` in `worker_base.py` | Yes — may need `post_processor` if report needs parsing
| Tool auto-registration | `TestAgentTool` + `ToolRegistry` in `tools/base.py` | Yes — `SaveReportTool` inherits this
| CLI invocation | `ClaudeCliTool` in `tools/claude_cli.py` | Yes — direct reuse
| Prompt templating | `load_prompt()` in `prompts/loader.py` | Yes — simple `{var}` replacement
| Supervisor routing | `route_from_dispatch()` in `supervisor.py` | Needs extension
| State definitions | `IntentExtraction`, `PlanStep` in `graph/state.py` | Needs extension
| Graph assembly | `build_graph()` in `graph/builder.py` | Needs extension

### 0C. Dream State Mapping

```
CURRENT STATE                  THIS PLAN                  12-MONTH IDEAL
─────────────────────────────────────────────────────────────────────────────────
Manual report writing    →   Auto-generated MD      →   Platform with:
from test data                 reports from              - Frontend upload
No standard template           uploaded files +          - Template visual editor
structure                      local MD templates        - Real-time preview
                               with [待补充] tags        - Report versioning
                                                         - Collaborative editing
                                                         - Export to PDF/HTML
```

### 0D. SELECTIVE EXPANSION Analysis

**Held scope (baseline):** New worker, save tool, prompt template, routing updates, tests.

**Expansion opportunities surfaced (cherry-pick):**

| # | Proposal | Effort | Recommendation |
|---|---|---|---|
| 1 | **Template validation CLI** — validate templates before runtime (check placeholder consistency, required sections) | S | DEFER to TODOS.md. Nice but not blocking. |
| 2 | **Report index / manifest** — maintain a JSON index of generated reports (path, timestamp, template, business_line) for querying | S | DEFER to TODOS.md. Useful for platform phase. |
| 3 | **Multi-file aggregation** — allow multiple test data files in one report (e.g., combine unit + integration results) | M | DEFER to TODOS.md. Can workaround with merged files. |
| 4 | **Template inheritance** — base template + business-line overrides to reduce duplication | M | DEFER to TODOS.md. Current flat structure is fine for <10 templates. |
| 5 | **Direct worker keywords** — add test report keywords to `main.py` `_SINGLE_AGENT_KEYWORDS` for simple-request bypass | S | ACCEPT. One-line addition, matches existing pattern. |

**Accepted expansions:** #5 (direct worker keywords)
**Deferred expansions:** #1-4

### 0E. Temporal Interrogation

| Horizon | State |
|---|---|
| **Hour 1** | Worker wrapper exists, `save_report` tool registered, basic prompt works. Can generate a report from a local file + template. |
| **Hour 6** | All routing wired, intent classifier recognizes report requests, tests pass (unit + integration + routing). |
| **Week 1** | Used in practice for 2-3 business lines. Edge cases surface: oversized files, malformed xlsx, missing templates. |
| **Month 1** | Template library stabilizes. Users request template inheritance and multi-file support. |
| **6 months** | Either integrated into frontend platform or remains CLI-only. If CLI-only, may be underutilized compared to a web UI. |

**6-month regret scenario:** If the frontend platform never materializes, the CLI-only workflow may feel clunky for non-technical users who just want to upload a file and get a report. The current design is developer-centric, which is correct for v3 but may limit adoption.

### Phase 1 Completion Summary

| Checkpoint | Status |
|---|---|
| Premises valid? | Yes, with CLI dependency caveat |
| Right problem? | Yes — fills real gap in Test Agents v3 |
| Scope calibrated? | Yes, minimal viable addition |
| Alternatives explored? | Design doc considers prompt-based vs template-engine approach; prompt-based chosen for leverage |
| Competitive risks? | Low — internal tool, not productized |
| 6-month trajectory? | Sound if platform integration happens; risk of underuse if stays CLI-only |

---

## Phase 2: Design Review

**Skipped — no UI scope detected.** (Plan contains zero view/rendering terms matching component, screen, form, button, modal, layout, dashboard, sidebar, nav, dialog.)

---

## Phase 3: Eng Review (Architecture, Code Quality, Tests, Performance, Security)

### 3.0. Scope Challenge

**Files touched by plan:** 9 (new + modified). Under the 8-file smell threshold if we don't count tests and prompts.
**New classes/services:** 2 (`SaveReportTool`, worker wrapper). Under the 2-class threshold.

Verdict: Scope is appropriately tight.

### 3.1. Architecture

```
New components (bold) and their relationships:

┌─────────────────────────────────────────────────────────────┐
│  Supervisor Graph (existing)                                │
│    └── route_from_dispatch ──→ test_report_generator        │
│                                   wrapper                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  **test_report_generator Worker Subgraph** (new)            │
│    ├── agent_node ──→ claude_cli (existing tool)            │
│    │                    └── "claude -p <super prompt>"      │
│    └── agent_node ──→ **save_report** (new tool)            │
│                           └── writes to reports/<bl>/       │
└─────────────────────────────────────────────────────────────┘
```

**Coupling assessment:** Low. New worker follows identical pattern to `data_analyst`. No changes to existing workers. Only Supervisor routing and state models get extended.

**Scaling concern:** The super prompt could exceed context limits if test data files are large. The design addresses xlsx >5000 rows, but does NOT address txt/csv >~100KB. `claude -p` has its own token limit (~200K for most models). A 10MB CSV would fail. Mitigation: add a size check in the wrapper, skip content injection for files >100KB and pass path only.

### 3.2. Code Quality

**DRY violation spotted:** `build_worker_task()` in `worker_base.py` has hardcoded context part generation for specific keys (`module_name`, `code_change_report`, `test_cases`, etc.). The new `file_path` / `business_line` / `template_name` keys won't appear in the task message unless `build_worker_task` is extended. The design doc flags this as "如有需要" — it IS needed.

**Fix:** Add `file_path`, `business_line`, `template_name` handling to `build_worker_task`, OR have the worker wrapper construct its own messages rather than relying on `build_worker_task`.

### 3.3. Test Review

**Test diagram:**

| Codepath | Test Type | Exists? | Gap |
|---|---|---|---|
| Worker wrapper builds prompt with file content | Unit (mock claude_cli + save_report) | No | **GAP** — planned in design |
| Worker wrapper handles xlsx preprocessing | Unit | No | **GAP** — planned in design |
| Worker wrapper skips preprocessing for large xlsx | Unit | No | **GAP** — not explicitly tested |
| Worker wrapper handles template missing | Unit | No | **GAP** — planned in design |
| Worker wrapper handles file missing | Unit | No | **GAP** — planned in design |
| Supervisor routes to test_report_generator | Unit (`test_integration.py`) | No | **GAP** — needs `route_from_dispatch` test case |
| Intent classifier sets `needs_test_report` | Unit (`test_integration.py` or intent tests) | No | **GAP** — prompt change must be tested |
| SaveReportTool creates directory + writes file | Unit | No | **GAP** — planned in design |
| SaveReportTool rejects path-traversal business_line | Unit | No | **GAP** — security-critical |
| Full pipeline: request → plan → worker → report | Integration | No | **GAP** — planned in design |
| Report content includes [待补充] markers | Integration | No | **GAP** — quality assertion |

**Test plan artifact:** `test_agents/tests/test_test_report_generator.py` (planned) should cover all rows above.

### 3.4. Performance

- **No N+1 queries** — no database access in this worker.
- **Memory risk:** xlsx preprocessing loads file into pandas DataFrame. With 5000-row cap, memory is bounded but depends on column count. A 5000x5000 xlsx would still be ~200MB in memory. Recommend capping by cell count (rows * cols) rather than row count alone.
- **I/O risk:** `save_report` creates directories. Use `os.makedirs(exist_ok=True)` — cheap.

### 3.5. Security

| Threat | Status | Mitigation |
|---|---|---|
| Path traversal via `business_line` | Addressed in design | Regex `[a-zA-Z0-9_-]+` in `save_report` |
| Path traversal via `template_name` | **NOT addressed** | Should apply same regex to `template_name` |
| Arbitrary file read via `file_path` | Accepted risk | `claude -p` reads whatever path is given; this is by design (user provides their own file) |
| Prompt injection via file content | Partially addressed | File content is passed as context, not instructions. Low risk but non-zero. |
| Symlink attack in `reports/` | Not addressed | `os.path.realpath()` check recommended |

### 3.6. Error & Rescue Registry

| Error | Trigger | Caught By | User Sees | Tested?
|---|---|---|---|---|
| File not found | `file_path` doesn't exist | `claude_cli` stderr → worker reflect → error result | Error summary in final answer | Planned |
| Template not found | `templates/<bl>/<name>.md` missing | Worker wrapper pre-check | Error result without calling CLI | Planned |
| xlsx parse failure | Corrupt / malformed xlsx | pandas exception → fallback to path | CLI may fail; reflected | Planned |
| xlsx too large | >5000 rows or >cell cap | Wrapper skip preprocess | Path passed instead of content | **Not tested** |
| `claude` CLI not installed | `FileNotFoundError` | `ClaudeCliTool._run()` | "Claude CLI 未找到" | **Not tested** |
| `claude -p` timeout | Network/model slowness | `subprocess.TimeoutExpired` | "Claude CLI 超时" | Reuses existing |
| Report empty | `claude -p` returns empty | Worker reflect | Retry or mark failed | Planned |
| Path traversal in business_line | Malicious input | `save_report` regex | Rejected / error | **Not tested** |
| `reports/` dir not writable | Permission denied | `os.makedirs` / `open` exception | Exception bubbles up | **Not tested** |

### Phase 3 Completion Summary

| Dimension | Verdict |
|---|---|
| Architecture sound? | Yes, low coupling, follows existing pattern |
| Test coverage sufficient? | **No — 4 untested security/error paths** (see registry) |
| Performance risks addressed? | Partial — recommend cell-count cap, not just row cap |
| Security threats covered? | Partial — `template_name` sanitization missing |
| Error paths handled? | Yes for main paths; edge cases need tests |
| Deployment risk manageable? | Yes — additive change, no migrations |

---

## Phase 3.5: DX Review (Developer Experience)

**DX scope detected:** Yes — this is a developer-facing agent system (Claude Code skills, CLI invocation, AI agent workflows).

### DX Dimensions

| Pass | Dimension | Score | Finding |
|---|---|---|---|
| 1 | Getting started (< 5 min) | 7/10 | After implementation, a dev can run `python -m test_agents "生成测试报告"` but needs to know about `templates/` directory structure. Missing: getting-started doc for template authors. |
| 2 | API/CLI naming | 8/10 | `test_report_generator` is clear. `save_report` tool name is guessable. Business line + template name convention is intuitive. |
| 3 | Error messages | 6/10 | Current `ClaudeCliTool` returns Chinese error messages. `save_report` should follow same pattern: problem + cause + fix. Design doesn't specify error message format for new tool. |
| 4 | Documentation | 5/10 | Design doc exists but no developer-facing "how to write a template" guide. Template authors need to know: directory structure, placeholder conventions, what data `claude -p` sees. |
| 5 | Upgrade path | 9/10 | Purely additive. No breaking changes to existing workers or state. |
| 6 | Dev environment | 8/10 | Requires `pandas` for xlsx preprocessing. Design doesn't mention adding to `requirements.txt`. |
| 7 | Escape hatches | 7/10 | User can always bypass the worker and run `claude -p` manually with the same prompt. No programmatic escape hatch for template path resolution (hardcoded `templates/`). |
| 8 | Observability | 8/10 | Fits into existing observability system (callback-based tracing). No new instrumentation needed. |

**Overall DX score: 72/100** — Good, held back by missing template authoring docs and incomplete error message specification.

---

## NOT in Scope (Deferred)

| Item | Reason | Target |
|---|---|---|
| Template validation CLI | Nice-to-have, not blocking | TODOS.md / future |
| Report index / manifest | Platform-phase feature | TODOS.md / future |
| Multi-file aggregation | Can workaround | TODOS.md / future |
| Template inheritance | Overkill for <10 templates | TODOS.md / future |
| Frontend upload UI | Out of v3 scope | Phase 2 platform project |
| PDF/HTML export | Out of v3 scope | Phase 2 platform project |
| Report versioning | Out of v3 scope | Phase 2 platform project |
| Online collaborative editing | Out of v3 scope | Phase 2 platform project |

---

## Consensus Tables

### CEO DUAL VOICES — CONSENSUS TABLE
[codex-unavailable — single-model review]

| Dimension | Claude | Consensus |
|---|---|---|
| Premises valid? | Yes | CONFIRMED |
| Right problem to solve? | Yes | CONFIRMED |
| Scope calibration correct? | Yes | CONFIRMED |
| Alternatives sufficiently explored? | Yes | CONFIRMED |
| 6-month trajectory sound? | Yes, with platform risk | CONFIRMED |

### ENG DUAL VOICES — CONSENSUS TABLE
[codex-unavailable — single-model review]

| Dimension | Claude | Consensus |
|---|---|---|
| Architecture sound? | Yes | CONFIRMED |
| Test coverage sufficient? | No — 4 gaps | **FLAGGED** |
| Performance risks addressed? | Partial | **FLAGGED** |
| Security threats covered? | Partial — template_name missing | **FLAGGED** |
| Error paths handled? | Main paths yes | CONFIRMED |
| Deployment risk manageable? | Yes | CONFIRMED |

---

## Action Items (Must Fix Before Implementation)

1. **[BLOCKING]** Update `intent_classifier.md` to recognize test report requests and set `needs_test_report: true`.
2. **[BLOCKING]** Update `build_worker_task()` in `worker_base.py` to include `file_path`, `business_line`, `template_name` in context messages.
3. **[BLOCKING]** Add `test_report_generator` to `_default_output_key()` in `supervisor.py`.
4. **[BLOCKING]** Add `test_report_generator` routing in `route_from_dispatch()` in `supervisor.py`.
5. **[BLOCKING]** Add `needs_test_report` to `_format_intent_analysis()` in `supervisor.py`.
6. **[BLOCKING]** Add `test_report_generator` keywords to `_SINGLE_AGENT_KEYWORDS` in `main.py`.
7. **[HIGH]** Sanitize `template_name` with same regex as `business_line` in `save_report`.
8. **[HIGH]** Add cell-count cap (not just row cap) for xlsx preprocessing.
9. **[HIGH]** Add `pandas` to `requirements.txt`.
10. **[MEDIUM]** Add `os.path.realpath()` check in `save_report` to prevent symlink attacks.
11. **[MEDIUM]** Write "how to write a template" developer guide (can be short).
12. **[MEDIUM]** Add tests for: path traversal rejection, symlink attack, missing CLI, oversized file fallback.

## 9. 未来扩展

- **平台化**：前端上传文件 → API 接收 → 触发 Supervisor，报告生成后返回下载链接
- **模板管理 UI**：业务线模板增删改查，模板内占位符可视化编辑
- **报告版本管理**：同一批次多次生成，保留历史版本
- **报告审阅**：生成后进入审阅态，支持人工在线编辑缺失项并重新保存
