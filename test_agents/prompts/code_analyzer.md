请分析模块 {module_name} 在 commit {source_commit}..{target_commit} 之间的代码变更。

Commit 消息：{commit_msg}

请按以下步骤操作：
1. 先执行 `git diff {source_commit}..{target_commit} -- {module_name}/` 获取变更内容
2. 基于变更内容输出结构化分析报告

报告格式：
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
