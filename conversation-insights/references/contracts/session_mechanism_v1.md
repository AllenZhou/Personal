# SessionMechanismV1 契约

## 用途

会话级机制洞察 sidecar，文件路径：`data/insights/session/<session_id>.json`。

## Schema

```json
{
  "schema_version": "session-mechanism.v1",
  "session_id": "string",
  "created_at": "ISO-8601",
  "period_id": "string",
  "week": "YYYY-Www (optional compatibility field)",
  "summary": "string",
  "what_happened": ["string"],
  "why": [
    {
      "hypothesis": "string",
      "confidence": 0.0,
      "evidence": [
        {
          "session_id": "string",
          "turn_id": 1,
          "snippet": "string"
        }
      ]
    }
  ],
  "how_to_improve": [
    {
      "trigger": "string",
      "action": "string",
      "expected_gain": "string",
      "validation_window": "string"
    }
  ],
  "labels": ["string"],
  "generated_by": {
    "engine": "api",
    "provider": "claude_cli|codex_cli|anthropic|openai",
    "model": "string",
    "run_id": "string",
    "generated_at": "ISO-8601"
  }
}
```

## 必填约束

1. `why` 至少 1 条，且每条必须包含 evidence。  
2. evidence 必须包含 `session_id + turn_id + snippet`。  
3. `how_to_improve` 每条必须包含 `trigger/action/expected_gain/validation_window`。  
4. 不允许无证据心理结论。
