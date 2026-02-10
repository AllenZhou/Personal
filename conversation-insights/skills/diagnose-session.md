---
name: diagnose-session
description: 基于 SessionDigestV1 产出 SessionMechanismV1，回答发生了什么/为什么/怎么改
---

# Session 机制诊断 Skill

目标：对单条会话输出 **可证据追溯** 的机制洞察，不做无证据心理判断。

## 输入

- 文件：`output/skill_jobs/<run_id>/session_digests.json`
- 单条记录：`SessionDigestV1`

## 输出（必须 JSON）

每条会话产出一个 `SessionMechanismV1`：

```json
{
  "schema_version": "session-mechanism.v1",
  "session_id": "...",
  "created_at": "ISO-8601",
  "period_id": "2026-02-10_to_2026-02-10",
  "summary": "一句话总结",
  "what_happened": ["发生了什么（事实）"],
  "why": [
    {
      "hypothesis": "为什么发生（机制假设）",
      "confidence": 0.0,
      "evidence": [
        {
          "session_id": "...",
          "turn_id": 1,
          "snippet": "原始文本证据"
        }
      ]
    }
  ],
  "how_to_improve": [
    {
      "trigger": "触发条件",
      "action": "具体动作",
      "expected_gain": "预期收益",
      "validation_window": "next-7-days"
    }
  ],
  "labels": ["pattern-tag"],
  "generated_by": {
    "engine": "api",
    "provider": "claude_cli",
    "model": "skill",
    "run_id": "<run_id>",
    "generated_at": "ISO-8601"
  }
}
```

## 约束

1. `why` 每一项必须有 evidence。  
2. `how_to_improve` 每一项必须包含 `trigger/action/expected_gain/validation_window`。  
3. 不得输出“情绪状态/人格标签”等无证据结论。  
4. 置信度低于 0.5 时，应明确写成“待验证假设”。
5. 输出文案默认使用中文（字段名保持契约定义不变）。

## 建议流程

1. 先写事实层（what_happened）
2. 再写机制层（why + evidence）
3. 最后写干预层（how_to_improve）
4. 控制数量：`what` 3-5 条，`why` 1-3 条，`how` 1-3 条
