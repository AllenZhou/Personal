#!/usr/bin/env python3
import sys, json, yaml
from pathlib import Path

payload = json.load(open(0, "r", encoding="utf-8"))
domain = payload.get("domain", "default")
phase = payload["phase"]
lesson_id = payload["lesson_id"]
concepts = payload.get("concepts", [])

project_root = Path(__file__).parent.parent.parent.parent
path = project_root / f"learning_journal/{domain}/concept_index.yaml"

if not path.exists():
    raise FileNotFoundError(f"concept_index.yaml missing for domain {domain}")

with path.open("r", encoding="utf-8") as f:
    index_data = yaml.safe_load(f) or {}

# 支持多领域结构
if "domains" not in index_data:
    # 兼容旧格式，迁移到新格式
    index_data = {"domains": {domain: index_data}}

domains_index = index_data.get("domains", {})
if domain not in domains_index:
    domains_index[domain] = {}

domain_index = domains_index[domain]

if phase not in domain_index:
    domain_index[phase] = []

phase_list = domain_index.get(phase, []) or []
if not isinstance(phase_list, list):
    phase_list = []

def find_concept(name):
    for c in phase_list:
        if c.get("concept") == name:
            return c
    return None

for item in concepts:
    name = item.get("concept")
    if not name:
        continue
    definition = item.get("definition", "")
    delta = int(item.get("mastery_delta", 0))

    existing = find_concept(name)
    if existing:
        existing["mastery"] = max(0, min(5, int(existing.get("mastery", 0)) + delta))
        if definition and not existing.get("definition"):
            existing["definition"] = definition
        ev = existing.setdefault("evidence", [])
        if lesson_id not in ev:
            ev.append(lesson_id)
    else:
        phase_list.append({
            "concept": name,
            "definition": definition,
            "mastery": max(0, min(5, delta)),
            "evidence": [lesson_id]
        })

domain_index[phase] = phase_list
domains_index[domain] = domain_index
index_data["domains"] = domains_index

with path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(index_data, f, allow_unicode=True, sort_keys=False)
