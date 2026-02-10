# Data Schemas (Multi-Domain Support)

## learning_log.jsonl (每行一个 JSON)
Required fields:
- domain (string)  # 领域标识符（新增）
- timestamp (ISO8601, include timezone)
- phase (P0..Pn)   # 动态阶段编号（不限于 P0-P5）
- lesson_id (e.g., P0-L1)
- session_goal (string)
- success_criteria (string[])
- key_concepts (string[])
- quiz (array of {q, user_a, score})
- mastery_before (0..5)
- mastery_after (0..5 or null)
- misconceptions (string[])
- assets_created (string[])
- next_review (string[] like ["D+1","D+3"])
- gate (optional): { pass: bool, metrics_summary: object }

## concept_index.yaml (按领域组织)
domains:
  {domain_identifier}:
    phase:
      - concept:
        definition:
        mastery:
        evidence: [lesson_id]

示例：
domains:
  ai-llm-agent:
    P0:
      - concept: "概率生成"
        definition: "LLM 基于概率分布生成文本的特性"
        mastery: 3
        evidence: ["P0-L1"]
  python-programming:
    P0:
      - concept: "变量"
        definition: "存储数据的容器"
        mastery: 0
        evidence: []

## review_queue.yaml (按领域组织)
domains:
  {domain_identifier}:
    - due: YYYY-MM-DD
      phase:
      lesson_id:
      focus: [concepts...]
      drill: string

示例：
domains:
  ai-llm-agent:
    - due: 2024-01-15
      phase: P0
      lesson_id: P0-L1
      focus: ["概率生成", "上下文窗口"]
      drill: "主动回忆三题"
  python-programming:
    - due: 2024-01-16
      phase: P0
      lesson_id: P0-L1
      focus: ["变量", "数据类型"]
      drill: "代码练习"

## phase_gates.yaml (按领域组织，从 domain_config 同步)
domains:
  {domain_identifier}:
    policy:
      pass_mastery: 3
      covered_ratio: 0.8
      freshness_days: 14
      min_mastery_floor: 2
    gates:
      phase:
        required_concepts: [string...]
