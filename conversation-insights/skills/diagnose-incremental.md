---
name: diagnose-incremental
description: 基于 SessionMechanismV1 产出 IncrementalMechanismV1（中文机制结论，reports 必填）
---

# Incremental 机制诊断 Skill

目标：从会话级机制诊断中输出可直接写入 Notion 的增量机制洞察。输出必须是 `IncrementalMechanismV1`，并以机制解释为中心（发生了什么 / 为什么 / 怎么改），不是会话逐条罗列。

## 输入

- `IncrementalInputV1`
  - `period_id`
  - `coverage`
  - `sessions`（每条为会话级机制摘要，字段可能是压缩结构）
    - 常见字段：`session_id`、`labels`、`mechanism.hypothesis`、`mechanism.evidence_refs`、`action_ref`
    - 若字段压缩，不得臆造缺失信息；应基于已有证据做聚合机制结论

## 输出（必须 JSON）

```json
{
  "schema_version": "incremental-mechanism.v1",
  "period_id": "rolling_all-time",
  "generated_at": "ISO-8601",
  "source_run_id": "run-id",
  "coverage": {
    "sessions_total": 623,
    "sessions_with_mechanism": 181
  },
  "reports": [
    {
      "dimension": "incremental-root-causes",
      "layer": "L3",
      "title": "增量根因假设 - rolling_all-time",
      "key_insights": "一句中文机制结论（不是纯计数）",
      "detail_lines": [
        "机制变化：......",
        "证据簇：主证据 + 辅助证据（聚合表述，不逐会话平铺）",
        "动作：......；验证窗：......"
      ],
      "conversations_analyzed": 181,
      "period": "rolling_all-time",
      "date": "2026-02-10"
    }
  ],
  "guardrails": [
    "Every root-cause hypothesis must include concrete evidence.",
    "Do not infer psychological state without textual support."
  ]
}
```

## 强约束

1. 输出文案必须中文（字段名保持英文契约）。
2. `reports` 必须非空，且每条必须有：`dimension/layer/title/key_insights/detail_lines`。
3. `detail_lines` 必须是“机制聚合结论”，不要逐 session 倾倒。
4. 可引用数字，但数字只能作为证据，不可替代解释。
5. 禁止无证据心理判断。
6. 同一维度只输出一条聚合报告；避免重复维度。

## 维度清单（当前标准）

按以下维度输出（建议完整覆盖）：

### L2
1. `incremental-trigger-chains`
2. `incremental-first-pass-diagnostics`
3. `incremental-coverage-gap`
4. `incremental-task-stratification`

### L3
5. `incremental-root-causes`
6. `incremental-change-delta`
7. `incremental-interventions`
8. `incremental-intervention-impact`
9. `incremental-validation-loop`
10. `incremental-reuse-assets`
11. `incremental-compounding`

## 质量要求

- 每条报告应包含“现象 + 机制解释 + 动作 + 验证窗”。
- 有证据不足时，明确写“证据缺口 + 下一步采集动作”，不要用 placeholder。
- `key_insights` 1-2 句总结；详细内容放 `detail_lines`。
