# policy.training_plan (Skill)

This file is the **runtime policy source** for the agent.
The orchestrator loads this YAML section as `PolicyContext`.

```yaml
version: "1.0"
priority_order:
  - safety
  - sustainability
  - physique_feedback
  - performance

hard_rules:
  prohibited:
    - failure_sets
    - forced_reps
    - pr_tests
    - compensatory_heavy_loads
    - spinal_axial_compression_heavy
    - high_impact_intervals
    - overhead_high_risk_or_high_speed_press
  retreat_triggers:
    - name: pain_persist_48h
      rule: "back_or_shoulder_pain_persists_over_48h"
      action: "deload_or_retreat"
    - name: sleep_worse
      rule: "sleep_quality_significantly_worse"
      action: "reduce_volume_or_density"
    - name: two_high_fatigue
      rule: "two_consecutive_sessions_high_fatigue"
      action: "reduce_volume_or_density"

stage_1:
  intensity_anchor:
    rpe: "6-7"
    reps_in_reserve: "3-4"
  stop_criteria:
    - "sweat_obvious"
    - "fatigue_controllable"
    - "next_day_no_strong_soreness"

templates:
  A:
    duration_min: 30
    duration_max: 45
    recipe:
      - pattern: Push
        count: 1
        notes: "horizontal push, non-failure"
      - pattern: Pull
        count: 1
        notes: "horizontal pull, scap control"
      - pattern: Pull
        count: 1
        optional: true
        notes: "vertical pull if shoulder ok"
      - pattern: Pull
        count: 1
        notes: "scap/RC endurance (face-pull-like), low risk"
      - pattern: Core
        count: 1
        notes: "anti-rotation or anti-extension"
  B:
    duration_min: 20
    duration_max: 35
    recipe:
      - pattern: Cardio
        count: 1
        notes: "low-impact steady state; talk-test; optional mild surges, no sprint"
  C:
    duration_min: 30
    duration_max: 45
    recipe:
      - pattern: Hinge
        count: 1
        notes: "hip-dominant, avoid axial compression"
      - pattern: Lunge
        count: 1
        notes: "split stance / single-leg stability"
      - pattern: Hinge
        count: 1
        notes: "ham/glute accessory (e.g., leg curl machine style)"
      - pattern: Core
        count: 1
        notes: "anti-extension"
  D:
    duration_min: 30
    duration_max: 45
    recipe:
      - pattern: Cardio
        count: 1
        optional: true
        notes: "steady supplement OR"
      - pattern: Core
        count: 1
        optional: true
      - pattern: Pull
        count: 1
        optional: true
      - pattern: Push
        count: 1
        optional: true
    notes: "low-risk circuit 3-5 moves x2-3 rounds OR steady cardio; no high impact/complexity"

stability_controller:
  variant_budget:
    per_session_max_new: 1
    per_week_max_new: 2
    lookback_days: 7
  change_order:
    - quality
    - rest_density
    - volume
    - variant
    - new_action
  canonical_naming:
    template: "Equipment + Pattern + GripOrAngle + Variant"
    required_fields: ["pattern", "equipment", "variant_tag", "risk_tags"]

decision_rules:
  risk_signal_definition:
    - "pain == Significant"
    - "next_day == Bad"
    - "two_consecutive_difficulty == Hard"
  if_risk_signal:
    mode: Deload
    new_variants_allowed: 0
    adjust: ["reduce_volume_or_density"]
  if_normal:
    mode: Normal
    new_variants_allowed: 1

generator_constraints:
  avoid:
    - "spinal_axial_compression"
    - "high_impact"
    - "high_risk_overhead"
  intensity:
    default_rpe: "6-7"
    rest_sec_range: [45, 90]
    reps_range: [8, 15]
  cardio:
    talk_test: true
    duration_range_min: 20
    duration_range_max: 35
```