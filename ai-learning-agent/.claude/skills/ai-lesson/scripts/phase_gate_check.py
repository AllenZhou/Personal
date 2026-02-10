#!/usr/bin/env python3
import json
import yaml
from datetime import datetime, timezone
from pathlib import Path

def load_yaml(p):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def load_last_activity_days(log_path: str, phase: str):
    p = Path(log_path)
    if not p.exists():
        return None
    last = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("phase") != phase:
                continue
            ts = parse_ts(rec.get("timestamp",""))
            if ts is None:
                continue
            if last is None or ts > last:
                last = ts
    if last is None:
        return None
    now = datetime.now(tz=last.tzinfo) if last.tzinfo else datetime.now(timezone.utc)
    delta = now - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))
    return delta.days

def main():
    gates_path = "learning_journal/phase_gates.yaml"
    concept_index_path = "learning_journal/concept_index.yaml"
    log_path = "learning_journal/learning_log.jsonl"

    if not Path(gates_path).exists():
        print(json.dumps({"ok": False, "error": "phase_gates.yaml missing"}, ensure_ascii=False))
        return
    if not Path(concept_index_path).exists():
        print(json.dumps({"ok": False, "error": "concept_index.yaml missing"}, ensure_ascii=False))
        return

    gates = load_yaml(gates_path) or {}
    policy = gates.get("policy", {})
    gates_map = gates.get("gates", {})

    payload = json.load(open(0, "r", encoding="utf-8"))
    current_phase = payload["current_phase"]
    target_phase = payload.get("target_phase")

    required = (gates_map.get(current_phase) or {}).get("required_concepts", [])
    pass_mastery = int(policy.get("pass_mastery", 3))
    covered_ratio_req = float(policy.get("covered_ratio", 0.8))
    freshness_days = int(policy.get("freshness_days", 14))
    min_floor = int(policy.get("min_mastery_floor", 2))

    index = load_yaml(concept_index_path) or {}
    phase_concepts = index.get(current_phase, []) or []
    mastery_map = {c.get("concept"): int(c.get("mastery", 0)) for c in phase_concepts if c.get("concept")}

    covered, missing, below = [], [], []
    for c in required:
        m = mastery_map.get(c)
        if m is None:
            missing.append({"concept": c, "mastery": None})
        else:
            if m >= pass_mastery:
                covered.append({"concept": c, "mastery": m})
            else:
                below.append({"concept": c, "mastery": m})

    total = max(1, len(required))
    covered_ratio = len(covered) / total

    min_mastery = None
    if required:
        vals = [mastery_map.get(c, 0) for c in required]
        min_mastery = min(vals) if vals else None

    days_since = load_last_activity_days(log_path, current_phase)
    fresh_ok = (days_since is not None) and (days_since <= freshness_days)

    pass_ok = (covered_ratio >= covered_ratio_req) and (min_mastery is not None and min_mastery >= min_floor) and fresh_ok

    weakest = []
    for c in required:
        weakest.append((mastery_map.get(c, 0), c))
    weakest.sort(key=lambda x: x[0])
    remediation = [{"concept": c, "mastery": m} for (m, c) in weakest[:3]]

    out = {
        "ok": True,
        "current_phase": current_phase,
        "target_phase": target_phase,
        "policy": {
            "pass_mastery": pass_mastery,
            "covered_ratio_req": covered_ratio_req,
            "freshness_days": freshness_days,
            "min_mastery_floor": min_floor
        },
        "metrics": {
            "covered_ratio": covered_ratio,
            "covered": covered,
            "below": below,
            "missing": missing,
            "min_mastery_in_gate": min_mastery,
            "days_since_last_activity": days_since,
            "fresh_ok": fresh_ok
        },
        "pass": pass_ok,
        "remediation_top3": remediation
    }
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
