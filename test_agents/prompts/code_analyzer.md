请分析模块 {module_name} 在 commit {source_commit}..{target_commit} 之间的代码变更。

Commit 消息：{commit_msg}

## 可用工具

- `claude_cli` —— 调用 Claude CLI 执行复杂分析任务（适合需要语义理解的场景）
- `list_dir` —— 列出目录结构，必须传绝对路径
- `read_file` —— 读取单个文件（带行号），必须传绝对路径
- `grep` —— 在指定路径下按正则搜索（基于 ripgrep），必须传绝对路径
- `glob` —— 按文件名 glob 模式查找文件，必须传绝对路径

## 工作流程

1. **定位仓库**：若用户给出绝对路径（如 `/mnt/d/obs_node/`），直接在该路径下操作；否则默认在当前项目根 `/mnt/d/testagents`。
2. **了解结构**：用 `list_dir` 查看模块根目录，必要时 `depth=3`
3. **找变更范围**：用 `claude_cli` 调用 `git -C <repo_path> log --oneline -- <module>/` 等命令收集 commit
4. **看变更内容**：用 `claude_cli` 调用 `git -C <repo_path> diff <range> -- <module>/` 收集 diff
5. **查上下文**：用 `read_file` / `grep` / `glob` 在源码中查证函数定义、调用方、相关测试
6. **输出结构化报告**

## 报告格式

## 变更概述
...
## 新增/修改/删除的文件
...
## 关键逻辑变更
...
## 影响范围评估
...
## 测试建议
...
