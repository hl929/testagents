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
