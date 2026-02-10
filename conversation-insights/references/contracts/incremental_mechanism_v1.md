# IncrementalMechanismV1 契约

## 用途

增量机制洞察 sidecar，路径：`data/insights/incremental/<period_id>.json`。

## Schema

```json
{
  "schema_version": "incremental-mechanism.v1",
  "period_id": "string",
  "week": "string (optional compatibility alias of period_id)",
  "period": {
    "since": "YYYY-MM-DD",
    "until": "YYYY-MM-DD"
  },
  "generated_at": "ISO-8601",
  "source_run_id": "string",
  "coverage": {
    "sessions_total": 0,
    "sessions_with_mechanism": 0
  },
  "reports": [
    {
      "dimension": "string",
      "layer": "L2|L3|L4|L5",
      "title": "string",
      "key_insights": "string",
      "detail_lines": ["string"],
      "detail_text": "string (optional fallback)",
      "conversations_analyzed": 0,
      "period": "string",
      "date": "YYYY-MM-DD"
    }
  ],
  "guardrails": ["string"],
  "next_review_date": "YYYY-MM-DD"
}
```

## 必填约束

1. `schema_version` 必须为 `incremental-mechanism.v1`。
2. `period_id` 必须非空（`week` 仅用于兼容旧文件）。
3. `coverage` 必须存在，且 `sessions_with_mechanism <= sessions_total`。
4. `reports` 必须非空。
5. `reports[*]` 必须包含：`dimension/layer/title/key_insights`。
6. `reports[*]` 必须包含 `detail_lines`（非空）或 `detail_text`（非空）。
7. `conversations_analyzed` 若存在，必须为非负整数。
8. `reports` 不允许出现重复自然键：`dimension + period`。

## 维度与层级映射（当前标准）

### L2
- `incremental-trigger-chains`
- `incremental-first-pass-diagnostics`
- `incremental-coverage-gap`
- `incremental-task-stratification`

### L3
- `incremental-root-causes`
- `incremental-change-delta`
- `incremental-interventions`
- `incremental-intervention-impact`
- `incremental-validation-loop`
- `incremental-reuse-assets`
- `incremental-compounding`

说明：
- 上述维度为当前支持维度，`layer` 必须与维度映射一致。
- 建议输出完整维度集合；证据不足时应输出“证据缺口 + 下一步动作”，而非 placeholder。

## 运行原则

- 深层机制结论由 Skill 直接产出（中文）。
- Python 仅做契约校验、落盘、排序与 Notion upsert，不生成归因/干预文案。
