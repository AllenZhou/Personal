---
name: conversation-insights
description: 单入口串行运行的 AI 对话洞察系统，默认增量，支持全量。
---

# Conversation Insights

## 运行入口

```bash
# 默认增量（推荐）
python3 scripts/pipeline.py

# 显式全量
python3 scripts/pipeline.py run --mode full
```

## 测试入口

```bash
python3 scripts/pipeline.py test --mode segmented
python3 scripts/pipeline.py test --mode full
```

## 关键约束

1. 不再使用 weekly 作为主流程。
2. 不再要求用户手工串联中间命令。
3. 深层结论必须有 evidence。
4. Notion 是展示层，不是事实源。
5. incremental 机制结论必须由 Skill 组合产出（`diagnose-incremental + analyze-behavior + analyze-attribution + analyze-mental + extract-pattern + coach`），Python 只做校验与写入。
