---
name: ai-log
description: 后台：把本回合 learning_log 写入 learning_journal，并更新 concept_index 与 review_queue。
user-invocable: false
disable-model-invocation: true
allowed-tools: Read, Write, Bash
---

# AI Learning Journal Writer

## 输入
本技能通过 $ARGUMENTS 接收一个“单条 learning_log JSON”（或指向临时文件路径）。
优先策略：
1) 若 $ARGUMENTS 看起来是 JSON，直接使用；
2) 若是文件路径，读取其内容作为 JSON。

## 动作（必须按顺序）
1) 确保 `learning_journal/` 存在；否则运行：
   `bash .claude/skills/ai-lesson/scripts/journal_init.sh`

2) 追加写入 learning_log：
   `python3 .claude/skills/ai-lesson/scripts/journal_append.py`

3) 更新 review_queue：
   - 从 learning_log 取 phase/lesson_id/key_concepts/next_review
   - 调用 `python3 .claude/skills/ai-lesson/scripts/review_queue.py`

4) 更新 concept_index（通过脚本，防止 YAML 漂移）：
   - 从 learning_log 中抽取：
     - phase
     - lesson_id
     - key_concepts
     - mastery_before / mastery_after
   - 计算 mastery_delta = mastery_after - mastery_before（若 mastery_after 为空则 delta=0）
   - 构造 JSON 输入，调用：
     `python3 .claude/skills/ai-lesson/scripts/concept_index_update.py`

## 约束
- 不要重写历史日志，只允许追加。
- concept_index 更新采用保守策略：字段缺失就不更新，不要臆造。
