#!/usr/bin/env python3
"""
Upgrade local JSON conversation files to schema v1.1.

This script adds the new fields (tool_uses.input, metadata.file_changes)
to existing conversation JSON files without requiring access to the original
source data (ChatGPT export, Claude Code directories, etc.).

Since the original raw data is not available, this script:
- Adds empty/None placeholders for new fields to maintain schema compatibility
- Updates schema_version to "1.1"
- Preserves all existing data

Usage:
    python scripts/upgrade_local_schema.py
    python scripts/upgrade_local_schema.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).parent
_DATA_DIR = _SCRIPT_DIR.parent / "data" / "conversations"


def upgrade_conversation(conv: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Upgrade a conversation dict to schema v1.1.

    Returns the upgraded conversation and a list of changes made.
    """
    changes: list[str] = []

    # Check current schema version
    current_version = conv.get("schema_version", "1.0")
    if current_version == "1.1":
        return conv, ["已是 v1.1 版本"]

    # Upgrade schema_version
    conv["schema_version"] = "1.1"
    changes.append("schema_version: 1.0 -> 1.1")

    # Upgrade turns: add input field to tool_uses
    turns = conv.get("turns", [])
    tool_uses_upgraded = 0
    for turn in turns:
        assistant_response = turn.get("assistant_response", {})
        tool_uses = assistant_response.get("tool_uses", [])
        for tu in tool_uses:
            if "input" not in tu:
                tu["input"] = None
                tool_uses_upgraded += 1

    if tool_uses_upgraded > 0:
        changes.append(f"tool_uses.input：已添加到 {tool_uses_upgraded} 个工具调用")

    # Upgrade metadata: add file_changes field
    metadata = conv.get("metadata", {})
    if "file_changes" not in metadata:
        metadata["file_changes"] = None
        changes.append("metadata.file_changes：已添加 (None)")

    return conv, changes


def process_file(file_path: Path, dry_run: bool = False) -> tuple[bool, list[str]]:
    """
    Process a single JSON file.

    Returns (was_modified, changes_list).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            conv = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, [f"读取错误：{e}"]

    upgraded, changes = upgrade_conversation(conv)

    if not changes or changes == ["已是 v1.1 版本"]:
        return False, changes

    if not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(upgraded, f, ensure_ascii=False, indent=2)

    return True, changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upgrade local conversation JSON files to schema v1.1"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing files"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  升级本地对话文件至 Schema v1.1")
    print("=" * 60)
    if args.dry_run:
        print("  ** 试运行模式 - 不会修改任何文件 **")
    print()

    if not _DATA_DIR.is_dir():
        print(f"未找到数据目录：{_DATA_DIR}")
        return

    json_files = sorted(_DATA_DIR.glob("*.json"))
    print(f"找到 {len(json_files)} 个对话文件")
    print()

    upgraded_count = 0
    skipped_count = 0
    error_count = 0

    for file_path in json_files:
        was_modified, changes = process_file(file_path, dry_run=args.dry_run)

        if was_modified:
            upgraded_count += 1
            if args.dry_run:
                print(f"  将升级：{file_path.name}")
                for c in changes:
                    print(f"    - {c}")
        elif "已是 v1.1 版本" in changes:
            skipped_count += 1
        elif any("错误" in c for c in changes):
            error_count += 1
            print(f"  错误：{file_path.name} - {changes}")
        else:
            skipped_count += 1

    print()
    print("=" * 60)
    print(f"  {'将升级' if args.dry_run else '已升级'}：{upgraded_count}")
    print(f"  已跳过（已是 v1.1）：{skipped_count}")
    if error_count:
        print(f"  错误数：{error_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
