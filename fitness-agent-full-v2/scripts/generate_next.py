import argparse, random
from datetime import datetime, timezone
from scripts.lib.helpers import load_json, save_json
from scripts.lib.policy_loader import load_policy_from_skill
from scripts.lib.state_extract import extract_risk_signal, compute_weekly_variant_count, build_session_key

# Note: This generator intentionally avoids a pre-defined exercise library DB.
# It generates stable, generic actions based on pattern recipes + constraints.

EQUIPMENT_DEFAULT = {
    "Push": ["Machine", "Cable", "DB"],
    "Pull": ["Cable", "Machine"],
    "Hinge": ["Machine", "KB", "DB"],
    "Lunge": ["DB", "Bodyweight"],
    "Core": ["Cable", "Bodyweight"],
    "Cardio": ["Treadmill", "Bike", "Row", "Elliptical"]
}

def canonical_name(equipment: str, pattern: str, grip_angle: str, variant: str) -> str:
    return f"{equipment} {pattern} - {grip_angle} - {variant}"

def choose_variant_tag(pattern: str, equipment: str, allow_new: bool) -> str:
    # Stable: variant tag is mostly constant; if allow_new, occasionally introduce a new variant
    base = f"{pattern}:{equipment}:base"
    if not allow_new:
        return base
    # 30% chance to introduce a slight variant
    if random.random() < 0.30:
        return f"{pattern}:{equipment}:v1"
    return base

def build_exercise(order:int, pattern:str, allow_new_variant:bool, policy:dict) -> dict:
    equip = random.choice(EQUIPMENT_DEFAULT.get(pattern, ["Bodyweight"]))
    grip = "Neutral" if pattern in ("Pull", "Push") else "Standard"
    variant = "Controlled"
    variant_tag = choose_variant_tag(pattern, equip, allow_new_variant)

    # Dose defaults
    reps_range = policy["generator_constraints"]["intensity"]["reps_range"]
    rest_min, rest_max = policy["generator_constraints"]["intensity"]["rest_sec_range"]
    reps = f"{reps_range[0]}-{reps_range[1]}" if pattern != "Cardio" else "Talk-test steady"
    sets = 3 if pattern not in ("Core", "Cardio") else 2
    rest_sec = random.randint(rest_min, rest_max) if pattern not in ("Cardio",) else None

    intensity = policy["generator_constraints"]["intensity"]["default_rpe"] if pattern != "Cardio" else "Talk-test"
    risk_tags = []
    if pattern == "Cardio":
        risk_tags.append("LowImpact")

    return {
        "order": order,
        "name": canonical_name(equip, pattern, grip, variant),
        "pattern": pattern,
        "equipment": [equip],
        "sets": sets,
        "reps_or_time": reps,
        "intensity": intensity,
        "rest_sec": rest_sec,
        "risk_tags": risk_tags,
        "variant_tag": variant_tag,
        "notes": ""
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["A","B","C","D"])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; default today (UTC)")
    ap.add_argument("--snapshot_dir", default="snapshots/latest")
    ap.add_argument("--out", default="outputs/next_session.json")
    args = ap.parse_args()

    policy = load_policy_from_skill(".claude/skills/policy.training_plan.md")
    state = {
        "sessions": load_json(f"{args.snapshot_dir}/plan_sessions.json"),
        "exercises": load_json(f"{args.snapshot_dir}/plan_exercises.json"),
        "feedback": load_json(f"{args.snapshot_dir}/feedback.json"),
        "profile_dynamic_latest": load_json(f"{args.snapshot_dir}/profile_dynamic_latest.json"),
    }

    # Determine risk signal from feedback
    risk = extract_risk_signal(state)
    if risk:
        mode = policy["decision_rules"]["if_risk_signal"]["mode"]
        allow_new = policy["decision_rules"]["if_risk_signal"]["new_variants_allowed"] > 0
        rationale = "Risk signal detected from recent feedback -> Deload/Retreat rules applied."
    else:
        mode = policy["decision_rules"]["if_normal"]["mode"]
        allow_new = policy["decision_rules"]["if_normal"]["new_variants_allowed"] > 0
        rationale = "No risk signal detected -> Normal session within Stage 1 constraints."

    # Weekly budget
    weekly_used = compute_weekly_variant_count(state, lookback_days=policy["stability_controller"]["variant_budget"]["lookback_days"])
    # Per-session new variants cap (M)
    per_session_max_new = policy["stability_controller"]["variant_budget"]["per_session_max_new"]
    per_week_max_new = policy["stability_controller"]["variant_budget"]["per_week_max_new"]
    allow_new = allow_new and (weekly_used < per_week_max_new)

    # Build exercises from template recipe
    tmpl = policy["templates"][args.type]
    recipe = tmpl["recipe"]

    exercises = []
    new_variant_count = 0
    order = 1
    for block in recipe:
        pattern = block["pattern"]
        optional = block.get("optional", False)
        if optional:
            # include optional blocks with moderate probability
            if args.type == "A":
                include = random.random() < 0.6
            else:
                include = random.random() < 0.5
            if not include:
                continue

        allow_this_new = allow_new and (new_variant_count < per_session_max_new)
        ex = build_exercise(order, pattern, allow_this_new, policy)
        # Count as new if tag ends with ':v1'
        if ex["variant_tag"].endswith(":v1"):
            new_variant_count += 1
        exercises.append(ex)
        order += 1

    # Date
    date_str = args.date or datetime.now(timezone.utc).date().isoformat()
    session_key = build_session_key(date_str, args.type, mode)

    plan = {
        "session": {"date": date_str, "type": args.type, "mode": mode, "rationale": rationale},
        "exercises": exercises,
        "meta": {"new_variant_count": new_variant_count, "weekly_new_variant_count": weekly_used + new_variant_count, "session_key": session_key}
    }

    save_json(args.out, plan)
    print("OK: generated", args.out)

if __name__ == "__main__":
    main()
