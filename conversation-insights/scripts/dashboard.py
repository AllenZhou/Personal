#!/usr/bin/env python3
"""Deprecated thin wrapper for dashboard generation."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _dashboard_core import main as dashboard_main


def main(argv: list[str] | None = None) -> int:
    raw_args = argv if argv is not None else sys.argv[1:]
    args: list[str] = []
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
        args.append(arg)
    print(
        "[DEPRECATION] dashboard.py is kept as thin wrapper. "
        "Prefer `python3 scripts/_dashboard_core.py`.",
        file=sys.stderr,
    )
    return int(dashboard_main(args))


if __name__ == "__main__":
    sys.exit(main())
