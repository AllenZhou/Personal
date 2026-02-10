#!/usr/bin/env python3
import json, sys
from pathlib import Path

raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit("ERROR: No JSON input provided on stdin")

record = json.loads(raw)
domain = record.get("domain", "default")

project_root = Path(__file__).parent.parent.parent.parent
log_path = project_root / f"learning_journal/{domain}/learning_log.jsonl"

log_path.parent.mkdir(parents=True, exist_ok=True)

with log_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")
