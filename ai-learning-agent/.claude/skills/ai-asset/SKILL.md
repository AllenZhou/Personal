---
name: ai-asset
description: 将当前学习内容沉淀为可复用资产：Prompt模板、Checklist、Rubric、Eval set，并写入 learning_journal/assets/ 对应阶段目录。
argument-hint: "[asset-type: prompt|checklist|rubric|eval] [phase] [topic]"
disable-model-invocation: true
allowed-tools: Read, Write
---

# Asset Factory

## 输入
$ARGUMENTS 指定资产类型与主题。例如：
- "prompt P2 工具调用输出契约"
- "checklist P1 输入规格验收"
- "rubric P3 RAG 评估"
- "eval P4 agent 回滚与观测"

## 强制资产规范
每个资产必须包含：
- 适用范围 / 不适用范围
- 输入变量（名称、类型、约束）
- 输出结构（schema）
- 失败模式（常见错因）
- 自检清单（生成后自查）
- 最小示例（可复用）

## 写入路径
- `learning_journal/assets/<phase>/<asset-name>.yaml`（或 .md，但优先 YAML）
命名规则：kebab-case，含日期可选。

## 约束
- 不要写泛泛而谈的长文；以“可直接复制使用”为标准。
