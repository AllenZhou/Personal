---
name: ai-status
description: 只读展示当前 AI 学习状态：阶段进度、掌握度、待复习条目与已产出资产。
argument-hint: "[optional: phase=P0..P5] [optional: limit=N]"
disable-model-invocation: true
allowed-tools: Read, Bash
---

# AI Learning Status Dashboard

## 数据来源（只读）
- learning_journal/learning_log.jsonl
- learning_journal/concept_index.yaml
- learning_journal/review_queue.yaml
- learning_journal/assets/

## 展示内容（固定顺序）
1) 当前学习位置（最近一次 lesson_id / phase / session_goal）
2) 各 Phase 掌握度概览（平均 mastery；概念数）
3) 待复习队列（按 due 升序，默认 5 条）
4) 已产出资产概览（按 phase 分组）

## 行为约束
- 不生成教学内容
- 不更新 mastery
- 不调用 ai-log / ai-lesson / ai-asset
