#!/usr/bin/env python3
"""Deprecated thin wrapper for Notion stats sync."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _sync_notion_stats_core import main as sync_main


def main(argv: list[str] | None = None) -> int:
    raw_args = argv if argv is not None else sys.argv[1:]
    passthrough: list[str] = ["--append", "--period", "all-time"]
    if "--dry-run" in raw_args and "--dry-run" not in passthrough:
        passthrough.append("--dry-run")
    if "--append" in raw_args and "--append" not in passthrough:
        passthrough.append("--append")
    if "--period" in raw_args:
        idx = raw_args.index("--period")
        if idx + 1 < len(raw_args):
            # Replace default period with explicit one.
            passthrough = [arg for arg in passthrough if arg not in {"--period", "all-time"}]
            passthrough.extend(["--period", raw_args[idx + 1]])
    print(
        "[DEPRECATION] sync_notion_stats.py is kept as thin wrapper. "
        "Prefer `python3 scripts/_sync_notion_stats_core.py`.",
        file=sys.stderr,
    )
    return int(sync_main(passthrough))


if __name__ == "__main__":
    sys.exit(main())
