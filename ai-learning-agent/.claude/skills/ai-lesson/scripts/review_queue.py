#!/usr/bin/env python3
import json
from datetime import date, timedelta
from pathlib import Path
import yaml

payload = json.load(open(0, "r", encoding="utf-8"))

def add_days(tag: str) -> int:
    return int(tag.replace("D+",""))

items = []
today = date.today()
schedule = payload.get("schedule", ["D+1","D+3","D+7","D+14"])
for tag in schedule:
    items.append({
        "due": str(today + timedelta(days=add_days(tag))),
        "phase": payload["phase"],
        "lesson_id": payload["lesson_id"],
        "focus": payload.get("focus", []),
        "drill": payload.get("drill", "主动回忆三题")
    })

path = Path("learning_journal/review_queue.yaml")
if path.exists():
    with path.open("r", encoding="utf-8") as f:
        existing = yaml.safe_load(f) or []
else:
    existing = []

if not isinstance(existing, list):
    existing = []

existing.extend(items)

with path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)
