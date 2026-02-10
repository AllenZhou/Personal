#!/usr/bin/env bash
set -euo pipefail

mkdir -p learning_journal/assets
touch learning_journal/learning_log.jsonl

if [ ! -f learning_journal/concept_index.yaml ]; then
  cat > learning_journal/concept_index.yaml <<'YAML'
P0: []
P1: []
P2: []
P3: []
P4: []
P5: []
YAML
fi

if [ ! -f learning_journal/review_queue.yaml ]; then
  cat > learning_journal/review_queue.yaml <<'YAML'
# review items will be appended by ai-log
YAML
fi

if [ ! -f learning_journal/phase_gates.yaml ]; then
  cat > learning_journal/phase_gates.yaml <<'YAML'
policy:
  pass_mastery: 3
  covered_ratio: 0.8
  freshness_days: 14
  min_mastery_floor: 2

gates:
  P0:
    required_concepts:
      - 概率生成
      - 上下文窗口
      - 不可见世界状态
      - 输出契约
      - 可验证协作
  P1:
    required_concepts:
      - 目标-约束-假设-验收
      - 输入输出Schema
      - 反例与评估集
  P2:
    required_concepts:
      - 指令层级
      - few-shot
      - 工具调用
      - 结构化输出(JSON/YAML)
      - 自检清单
  P3:
    required_concepts:
      - 检索策略
      - chunking
      - 引用与证据链
      - RAG评估
      - prompt injection
  P4:
    required_concepts:
      - 规划-执行
      - 状态机
      - 工具编排
      - 观测与回滚
      - MCP权限/沙箱
  P5:
    required_concepts:
      - Prompt资产库
      - 评估集与回归测试
      - 周复盘机制
      - 知识索引
      - 复习队列
YAML
fi

echo "Initialized learning_journal/"
