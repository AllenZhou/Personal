#!/usr/bin/env python3
import json
from datetime import date, timedelta
from pathlib import Path
import yaml

payload = json.load(open(0, "r", encoding="utf-8"))
domain = payload.get("domain", "default")

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

project_root = Path(__file__).parent.parent.parent.parent
path = project_root / f"learning_journal/{domain}/review_queue.yaml"

if path.exists():
    with path.open("r", encoding="utf-8") as f:
        queue_data = yaml.safe_load(f) or {}
else:
    queue_data = {}

# 支持多领域结构
if "domains" not in queue_data:
    # 兼容旧格式，迁移到新格式
    if isinstance(queue_data, list):
        queue_data = {"domains": {domain: queue_data}}
    else:
        queue_data = {"domains": {domain: []}}

domains_queue = queue_data.get("domains", {})
if domain not in domains_queue:
    domains_queue[domain] = []

existing = domains_queue[domain]
if not isinstance(existing, list):
    existing = []

existing.extend(items)
domains_queue[domain] = existing
queue_data["domains"] = domains_queue

with path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(queue_data, f, allow_unicode=True, sort_keys=False)
