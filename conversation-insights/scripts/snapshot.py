#!/usr/bin/env python3
"""Deprecated thin wrapper for snapshot generation."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _snapshot_core import main as snapshot_main


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    print(
        "[DEPRECATION] snapshot.py is kept as thin wrapper. "
        "Prefer `python3 scripts/_snapshot_core.py`.",
        file=sys.stderr,
    )
    return int(snapshot_main(args))


if __name__ == "__main__":
    sys.exit(main())
