#!/usr/bin/env python3
import sys, json, yaml
from pathlib import Path

payload = json.load(open(0, "r", encoding="utf-8"))
phase = payload["phase"]
lesson_id = payload["lesson_id"]
concepts = payload.get("concepts", [])

path = Path("learning_journal/concept_index.yaml")
if not path.exists():
    raise FileNotFoundError("learning_journal/concept_index.yaml missing")

with path.open("r", encoding="utf-8") as f:
    index = yaml.safe_load(f) or {}

if phase not in index:
    raise ValueError(f"Invalid phase: {phase}")

phase_list = index.get(phase, []) or []
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

index[phase] = phase_list

with path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(index, f, allow_unicode=True, sort_keys=False)
