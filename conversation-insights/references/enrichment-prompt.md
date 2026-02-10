# LLM Metadata Enrichment — 分析指令

给定一段对话摘要（compact text digest），按以下要求生成结构化 JSON。**仅输出合法 JSON，不要 markdown 围栏或额外说明。**

## 输出 Schema

```json
{
  "conversation_intent": "用户想要完成什么（简短描述）",
  "task_type": "debugging | new-feature | research | learning | refactoring | documentation | deployment | configuration | brainstorming | code-review | data-analysis | writing | design | other",
  "actual_domains": ["backend.auth", "frontend.react"],
  "difficulty": 5,
  "outcome": "resolved | partial | abandoned | exploratory",
  "key_topics": ["topic1", "topic2"],
  "prompt_quality": {
    "score": 65,
    "strengths": ["clear goal"],
    "weaknesses": ["missing context"]
  },
  "correction_analysis": [
    {
      "turn_id": 3,
      "reason": "ai_error | user_changed_mind | scope_change | style_preference",
      "description": "简要说明"
    }
  ],
  "cognitive_patterns": [
    {
      "pattern": "anchoring | sunk_cost | scope_creep | confirmation_bias | perfectionism | decision_fatigue",
      "evidence": "发生了什么",
      "severity": "mild | moderate | significant"
    }
  ],
  "conversation_summary": "1-2 句总结",

  "problem_framing": {
    "has_context": true,
    "has_goal": true,
    "has_constraints": false,
    "has_output_format": false,
    "completeness_score": 50
  },
  "correction_details": [
    {
      "turn_id": 3,
      "type": "add_info | negate_retry | direction_change | detail_fix",
      "root_cause": "missing_context | ai_misunderstand | user_changed_mind | scope_change",
      "preventable": true,
      "prevention_hint": "首轮提供约束条件"
    }
  ],
  "interaction_dynamics": {
    "control_pattern": "user_led | ai_led | collaborative",
    "rhythm": "short_fast | long_deep | mixed",
    "repair_count": 2,
    "initiative_shifts": 3
  },
  "cognitive_signals": {
    "message_length_trend": "stable | decreasing | increasing",
    "detail_level_trend": "stable | declining | improving",
    "fatigue_indicators": ["shortened_messages", "skipped_verification", "accepted_suboptimal"],
    "flow_indicators": ["deep_followup", "proactive_exploration", "stable_rhythm"]
  },
  "success_factors": {
    "what_worked": ["clear_role_setting", "structured_request"],
    "what_hindered": ["missing_constraints", "scope_creep"],
    "reusable_pattern": "角色设定 + 背景 + 约束"
  }
}
```

## 字段规则

### 基础字段

| 字段 | 说明 |
|------|------|
| `actual_domains` | 使用层级格式，如 `backend.auth`、`devops.docker`、`legal.corporate`、`writing.business`。具体而非泛化。 |
| `difficulty` | 1=简单提问，5=中等任务，10=复杂多步骤工程 |
| `prompt_quality.score` | 0-100，基于清晰度、完整性、可执行性。在已有项目上下文中的简短 prompt 也可以得高分。 |
| `correction_analysis` | 仅在确实发生纠正时填写。空数组 `[]` 完全可以。`reason` 必须为 4 个枚举值之一。 |
| `cognitive_patterns` | 仅在确实检测到时填写。空数组 `[]` 完全可以。不要强行套用。 |
| `conversation_summary` | 使用对话的主要语言撰写。 |
| 所有字符串值 | 保持简洁。 |

### 深度分析字段（v2 新增）

| 字段 | 说明 |
|------|------|
| `problem_framing` | 评估用户问题框架的完整性。`completeness_score` = (has_context + has_goal + has_constraints + has_output_format) * 25 |
| `correction_details` | 比 `correction_analysis` 更详细。`type`: add_info=补充信息, negate_retry=否定重试, direction_change=方向调整, detail_fix=细节修正 |
| `correction_details.root_cause` | missing_context=首轮信息不足, ai_misunderstand=AI理解错误, user_changed_mind=用户改变想法, scope_change=范围变化 |
| `correction_details.preventable` | 如果首轮提供更多信息能避免此纠正，则为 true |
| `interaction_dynamics.control_pattern` | user_led=用户主导, ai_led=AI主导, collaborative=协作式 |
| `interaction_dynamics.rhythm` | short_fast=短问短答快速迭代, long_deep=长问长答深度探索, mixed=混合 |
| `cognitive_signals.fatigue_indicators` | 疲劳信号：shortened_messages, skipped_verification, accepted_suboptimal, repeated_questions |
| `cognitive_signals.flow_indicators` | 心流信号：deep_followup, proactive_exploration, stable_rhythm, detailed_feedback |
| `success_factors` | 仅在 outcome=resolved 时填写。提取可复用的成功模式。 |
