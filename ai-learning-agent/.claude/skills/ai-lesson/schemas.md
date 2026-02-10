# Data Schemas

## learning_log.jsonl (每行一个 JSON)
Required fields:
- timestamp (ISO8601, include timezone)
- phase (P0..P5)
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

## concept_index.yaml
- phase:
  - concept:
    definition:
    mastery:
    evidence: [lesson_id]

## review_queue.yaml
- due: YYYY-MM-DD
  phase:
  lesson_id:
  focus: [concepts...]
  drill: string
