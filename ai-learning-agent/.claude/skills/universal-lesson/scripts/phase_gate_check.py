#!/usr/bin/env python3
import json
import yaml
import sys
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

def load_last_activity_days(log_path: str, phase: str, domain: str):
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
            # 检查 domain 和 phase
            if rec.get("domain") != domain or rec.get("phase") != phase:
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
    # 支持命令行参数或 stdin JSON
    if len(sys.argv) >= 3:
        domain = sys.argv[1]
        current_phase = sys.argv[2]
        target_phase = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        payload = json.load(open(0, "r", encoding="utf-8"))
        domain = payload.get("domain", "default")
        current_phase = payload["current_phase"]
        target_phase = payload.get("target_phase")
    
    project_root = Path(__file__).parent.parent.parent.parent
    gates_path = project_root / f"learning_journal/{domain}/phase_gates.yaml"
    concept_index_path = project_root / f"learning_journal/{domain}/concept_index.yaml"
    log_path = project_root / f"learning_journal/{domain}/learning_log.jsonl"

    if not gates_path.exists():
        print(json.dumps({"ok": False, "error": f"phase_gates.yaml missing for domain {domain}"}, ensure_ascii=False))
        return
    if not concept_index_path.exists():
        print(json.dumps({"ok": False, "error": f"concept_index.yaml missing for domain {domain}"}, ensure_ascii=False))
        return

    gates_data = load_yaml(gates_path) or {}
    domains_data = gates_data.get("domains", {})
    domain_gates = domains_data.get(domain, {})
    
    policy = domain_gates.get("policy", {})
    gates_map = domain_gates.get("gates", {})

    required = (gates_map.get(current_phase) or {}).get("required_concepts", [])
    pass_mastery = int(policy.get("pass_mastery", 3))
    covered_ratio_req = float(policy.get("covered_ratio", 0.8))
    freshness_days = int(policy.get("freshness_days", 14))
    min_floor = int(policy.get("min_mastery_floor", 2))

    index_data = load_yaml(concept_index_path) or {}
    domains_index = index_data.get("domains", {})
    domain_index = domains_index.get(domain, {})
    phase_concepts = domain_index.get(current_phase, []) or []
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

    days_since = load_last_activity_days(str(log_path), current_phase, domain)
    fresh_ok = (days_since is not None) and (days_since <= freshness_days)

    pass_ok = (covered_ratio >= covered_ratio_req) and (min_mastery is not None and min_mastery >= min_floor) and fresh_ok

    weakest = []
    for c in required:
        weakest.append((mastery_map.get(c, 0), c))
    weakest.sort(key=lambda x: x[0])
    remediation = [{"concept": c, "mastery": m} for (m, c) in weakest[:3]]

    out = {
        "ok": True,
        "domain": domain,
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
