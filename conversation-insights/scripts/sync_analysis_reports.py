#!/usr/bin/env python3
"""Deprecated thin wrapper for incremental analysis reports sync."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _sync_analysis_reports_core import main as sync_main


def main(argv: list[str] | None = None) -> int:
    raw_args = argv if argv is not None else sys.argv[1:]
    passthrough: list[str] = []
    skip_next = False
    for idx, arg in enumerate(raw_args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--mode":
            # Legacy wrapper compatibility: ignore pipeline-only arg.
            if idx + 1 < len(raw_args):
                skip_next = True
            continue
        passthrough.append(arg)
    print(
        "[DEPRECATION] sync_analysis_reports.py is kept as thin wrapper. "
        "Prefer `python3 scripts/_sync_analysis_reports_core.py`.",
        file=sys.stderr,
    )
    return int(sync_main(passthrough))


if __name__ == "__main__":
    sys.exit(main())
