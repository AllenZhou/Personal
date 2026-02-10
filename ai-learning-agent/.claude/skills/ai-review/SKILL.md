---
name: ai-review
description: 从 learning_journal/review_queue.yaml 读取到期条目，按主动回忆进行复习测验，并把结果写回 learning_log（通过 ai-log）。
argument-hint: "[optional: due=YYYY-MM-DD] [optional: limit=N]"
disable-model-invocation: true
allowed-tools: Read, Write, Bash
---

# Spaced Review Runner

## 流程
1) 读取 `learning_journal/review_queue.yaml`
2) 选择到期（due <= today）的条目（可按参数覆盖 due），默认最多 5 条
3) 对每条生成 ≤3 道主动回忆题（围绕 focus）
4) 等用户回答后：
   - 生成一条新的 learning_log（phase=原phase，lesson_id 标记为 `REVIEW:<lesson_id>`）
   - mastery 根据表现更新（遵循 pedagogy.md）
   - 调用 `/ai-log` 写入并更新复习队列（答错则追加 D+1）

## 输出要求
- 先列出本次复习清单（lesson_id + focus）
- 然后逐条出题，等待用户作答（不要一次性给答案）
