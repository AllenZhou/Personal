---
name: coach
description: incremental 机制教练扩展约束（输出四个 L3 子维度，禁止会话逐条倾倒）
---

# Coach 扩展技能（Incremental 子维度）

你不是输出自由文本周报；你是 `diagnose-incremental` 的扩展约束。
目标：把“改进行动可复利”落到四个 L3 维度，并保证每条结论可验证。

## 必须覆盖的四个子维度

1. `incremental-change-delta`
- 输出本期 vs 上期的机制变化（模式增强/减弱/新增/消退）。
- 必须说明变化原因的证据簇（主证据 + 辅助证据）。

2. `incremental-intervention-impact`
- 输出关键干预动作的前后差异（如首轮正确率、返工轮次）。
- 必须包含置信度或不确定性说明；避免“绝对有效/无效”断言。

3. `incremental-reuse-assets`
- 输出模板/规则/清单等资产复用率及收益。
- 必须给出“哪些资产值得固化、哪些应下线”。

4. `incremental-task-stratification`
- 按 `task_type` 输出主要失败机制与对应动作。
- 要求“任务类型 -> 根因 -> 动作 -> 验证窗”链路完整。

## 输出约束（作用于 reports 条目）

- `incremental-task-stratification` 使用 `layer=L2`；其余三个子维度使用 `layer=L3`。
- 每个维度只生成 1 条聚合报告，不得逐会话罗列。
- 每条 `detail_lines` 至少包含：
  - 机制解释（发生了什么）
  - 归因说明（为什么）
  - 动作实验（怎么改）
  - 验证窗口（何时复盘）
- 允许数字，但禁止仅报计数。
- 证据不足时输出“证据缺口 + 下一步采样动作”，不得使用 placeholder。

## 中文风格

- 使用简洁中文。
- 保留必要 technical terms（如 `task_type`, `first-pass`）可中英混排。
- 禁止输出 markdown 标题块；只输出契约 JSON 所需字段文本。
