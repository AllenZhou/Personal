#!/usr/bin/env python3
import json, sys

raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit("ERROR: No JSON input provided on stdin")

record = json.loads(raw)

with open("learning_journal/learning_log.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")