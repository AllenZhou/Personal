---
name: extract-pattern
description: 从对话中提取成功/失败模式，写入知识库
---

# 模式提取

分析对话，识别值得复用的成功模式或需要避免的失败模式，写入知识库供后续参考。

## 提取条件

### 成功模式

满足以下条件的对话可提取为成功模式：

| 条件 | 阈值 | 说明 |
|------|------|------|
| outcome | resolved | 任务成功完成 |
| total_turns | ≤ 5 | 高效解决 |
| prompt_quality.score | ≥ 70 | Prompt 质量高 |
| cognitive_patterns | 空 | 无认知偏差 |

### 失败模式

满足以下条件的对话可提取为失败模式：

| 条件 | 阈值 | 说明 |
|------|------|------|
| outcome | abandoned 或 partial | 任务未完成 |
| total_turns | ≥ 10 | 对话过长 |
| correction_count | ≥ 3 | 多次纠正 |

### Prompt 模板候选

满足以下条件的首条消息可提取为模板：

| 条件 | 阈值 | 说明 |
|------|------|------|
| prompt_quality.score | ≥ 80 | 高质量 Prompt |
| outcome | resolved | 导致成功结果 |
| 结构清晰 | 有背景、目标、约束 | 结构完整 |

## 执行步骤

### Step 1: 分析对话

读取指定对话（或最近 N 个未分析的对话），检查是否符合提取条件。

**输入**:

- 指定 session_id: 分析特定对话
- 无参数: 分析最近 10 个未提取的对话

### Step 2: 判断模式类型

```text
if outcome == "resolved" and turns <= 5 and prompt_quality >= 70:
    type = "success"
elif outcome in ["abandoned", "partial"] and (turns >= 10 or corrections >= 3):
    type = "failure"
elif prompt_quality >= 80 and outcome == "resolved":
    type = "template"
else:
    type = "neutral"  # 不提取
```

### Step 3: 提取模式信息

**成功模式**:

```json
{
  "id": "pattern_success_001",
  "type": "success",
  "name": "[自动生成: task_type + 关键特征]",
  "task_type": "[从对话提取]",
  "trigger_conditions": [
    "首条消息结构清晰",
    "目标明确",
    "提供了必要上下文"
  ],
  "evidence": "[session_id]",
  "lesson": "[从对话分析: 为什么成功]",
  "metrics": {
    "turns": 4,
    "prompt_quality": 85,
    "first_turn_acceptance": true
  },
  "created_at": "[ISO-8601]"
}
```

**失败模式**:

```json
{
  "id": "pattern_failure_001",
  "type": "failure",
  "name": "[自动生成: task_type + 失败特征]",
  "task_type": "[从对话提取]",
  "failure_reasons": [
    "首条消息缺少关键信息",
    "中途频繁改变方向",
    "未定义成功标准"
  ],
  "evidence": "[session_id]",
  "lesson": "[从对话分析: 如何避免]",
  "avoidance_tips": [
    "具体可操作的建议1",
    "具体可操作的建议2"
  ],
  "created_at": "[ISO-8601]"
}
```

**Prompt 模板**:

```json
{
  "id": "template_001",
  "type": "template",
  "name": "[task_type] 高效 Prompt 模板",
  "task_type": "[从对话提取]",
  "content": "[首条消息内容，脱敏处理]",
  "structure": {
    "has_background": true,
    "has_goal": true,
    "has_constraints": true,
    "has_context": true
  },
  "evidence": "[session_id]",
  "success_rate": "[如果有多次使用: 成功率]",
  "avg_turns": "[平均解决轮数]",
  "created_at": "[ISO-8601]"
}
```

### Step 4: 写入知识库

1. 读取 `data/knowledge_base/patterns.json`
2. 检查去重（基于 evidence session_id）
3. 追加新模式
4. 写回文件

### Step 5: 确认输出

## 模式提取结果

### 提取成功

**[成功/失败/模板] 模式已入库**

- ID: pattern_xxx
- 名称: [模式名称]
- 来源: session_xxx
- 经验: [一句话总结]

### 跳过（不符合提取条件）

- session_xxx: outcome=partial, turns=6 (不满足成功条件)
- session_yyy: outcome=resolved, turns=12 (不满足高效条件)

### 已存在（跳过重复）

- session_zzz: 已在 pattern_xxx 中记录

---

## 知识库 Schema

`data/knowledge_base/patterns.json`:

```json
{
  "patterns": [
    {
      "id": "string",
      "type": "success | failure",
      "name": "string",
      "task_type": "string",
      "trigger_conditions": ["string"],
      "failure_reasons": ["string"],
      "evidence": "session_id",
      "lesson": "string",
      "avoidance_tips": ["string"],
      "metrics": {},
      "created_at": "ISO-8601"
    }
  ],
  "templates": [
    {
      "id": "string",
      "name": "string",
      "task_type": "string",
      "content": "string",
      "structure": {},
      "evidence": "session_id",
      "success_rate": "number",
      "avg_turns": "number",
      "created_at": "ISO-8601"
    }
  ],
  "metadata": {
    "last_updated": "ISO-8601",
    "total_patterns": 0,
    "total_templates": 0
  }
}
```
