import argparse
from jsonschema import Draft7Validator
from scripts.lib.helpers import load_json, save_json
from scripts.lib.policy_loader import load_policy_from_skill

FORBIDDEN_HINTS = [
    "PR", "failure", "forced", "sprint", "jump", "overhead explosive",
    "axial compression", "back squat", "heavy squat"
]

def validate(plan: dict, schema: dict, policy: dict) -> list:
    errors = []
    v = Draft7Validator(schema)
    for e in sorted(v.iter_errors(plan), key=str):
        errors.append(f"SCHEMA: {e.message}")

    # Hard rule keyword scan (basic safeguard)
    text_blob = (str(plan.get("session", {})) + str(plan.get("exercises", []))).lower()
    for hint in FORBIDDEN_HINTS:
        if hint.lower() in text_blob:
            errors.append(f"HARD_RULE: forbidden hint detected: {hint}")

    # Stability budget
    vb = policy["stability_controller"]["variant_budget"]
    per_session = vb["per_session_max_new"]
    per_week = vb["per_week_max_new"]
    new_cnt = plan.get("meta", {}).get("new_variant_count", 0)
    weekly_cnt = plan.get("meta", {}).get("weekly_new_variant_count", 0)
    if new_cnt > per_session:
        errors.append(f"STABILITY: new_variant_count {new_cnt} exceeds per_session_max_new {per_session}")
    if weekly_cnt > per_week:
        errors.append(f"STABILITY: weekly_new_variant_count {weekly_cnt} exceeds per_week_max_new {per_week}")

    return errors

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="outputs/next_session.json")
    ap.add_argument("--schema", default="assets/output_schema.json")
    ap.add_argument("--out", default="outputs/validation_report.json")
    args = ap.parse_args()

    plan = load_json(args.plan)
    schema = load_json(args.schema)
    policy = load_policy_from_skill(".claude/skills/policy.training_plan.md")

    errors = validate(plan, schema, policy)
    report = {"ok": len(errors) == 0, "errors": errors}
    save_json(args.out, report)
    if report["ok"]:
        print("OK: validation pass")
    else:
        print("FAIL: validation errors:", len(errors))
        for e in errors:
            print(" -", e)

if __name__ == "__main__":
    main()
