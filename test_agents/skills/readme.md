# Skills 安装说明

## 安装

将 skill 目录复制到 Claude 用户级 skill 目录：

```bash
cp -r test_agents/skills/code_analysis_skill ~/.claude/skills/
cp -r test_agents/skills/case_review_skill ~/.claude/skills/
```

## 验证

```bash
claude skill list | grep -E "code_analysis|case_review"
```
