---
name: analyze-behavior
description: 分析跨对话行为链模式，识别健康循环与问题模式
---

# 行为链分析

分析用户跨对话的行为序列，识别健康的工作模式和需要改进的问题模式。

## 执行步骤

### Step 1: 加载数据

使用 Glob 列出 `agents/conversation-insights/data/conversations/*.json`
使用 Read 读取每个文件，提取 `llm_metadata` 字段

### Step 2: 构建时间序列

1. 按 `created_at` 排序所有对话
2. 24 小时内的连续对话归为一个 session
3. 提取每个对话的关键字段:
   - `task_type`: debugging / new-feature / research / refactoring / etc.
   - `outcome`: resolved / partial / abandoned / exploratory
   - `cognitive_patterns`: scope_creep / perfectionism / anchoring / etc.
   - `total_turns`: 对话轮数

### Step 3: 识别行为模式

检测以下模式：

**健康循环**（目标模式）:

- `research → new-feature → resolved`: 先调研再实施
- `debugging → resolved` (turns ≤ 5): 高效调试
- `new-feature → resolved` (turns ≤ 8): 清晰的需求执行

**问题模式**:

| 模式 | 检测条件 | 风险 |
|------|----------|------|
| 冲动模式 | `new-feature → abandoned/partial` 且无前置 research | 需求不清就开始 |
| 分析瘫痪 | `research → research → research → abandoned` | 过度分析不行动 |
| 调试循环 | 连续 3+ 个 `debugging` 且同一领域 | 卡在同一问题 |
| 范围蔓延 | session 内 `scope_creep` 出现 ≥3 次 | 不断扩大范围 |
| 长对话陷阱 | 单个对话 turns ≥ 15 且 outcome ≠ resolved | 应该拆分或重启 |

### Step 4: 计算统计指标

- 各模式出现次数和占比
- 与上周对比的趋势（↑/↓/→）
- 平均 session 长度（对话数）
- 平均单对话轮数

### Step 5: 输出分析报告

## 行为链分析报告

### 概览

- 分析时间范围: [最早对话日期] - [最新对话日期]
- 总 session 数: X
- 总对话数: Y
- 平均 session 长度: Z 个对话

### 模式分布

| 模式 | 次数 | 占比 | 趋势 |
|------|------|------|------|
| 健康循环 | - | - | ↑/↓/→ |
| 冲动模式 | - | - | - |
| 分析瘫痪 | - | - | - |
| 调试循环 | - | - | - |
| 范围蔓延 | - | - | - |
| 长对话陷阱 | - | - | - |

### 典型案例

**[模式名称] 案例**:

- Session: [日期范围]
- 对话序列: [task_type1 → task_type2 → ...]
- 问题: [具体描述]
- 建议: [如何避免]

### 改进建议

基于数据分析，本周建议关注：

1. **[最高频问题模式]**: [具体可操作的建议]
2. **[次高频问题模式]**: [具体可操作的建议]

### 健康指标

- 健康循环占比: X% (目标: ≥60%)
- 问题模式占比: Y% (目标: ≤20%)
- 平均调试轮数: Z (目标: ≤5)
