#!/usr/bin/env python3
"""
Backfill local JSON conversation files from source data.

Re-runs the normalization logic from each ingest script but only saves
local JSON files — does NOT create Notion pages.  Use this to populate
data/conversations/ for conversations that were imported to Notion
before local storage was added.

Usage:
    # Backfill all platforms that have auto-discoverable data
    python scripts/backfill_local.py

    # Backfill only specific platforms
    python scripts/backfill_local.py --platform claude_code
    python scripts/backfill_local.py --platform codex
    python scripts/backfill_local.py --platform chatgpt --chatgpt-json /path/to/conversations.json

    # Dry run — show what would be backfilled
    python scripts/backfill_local.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "data", "conversations"))
sys.path.insert(0, _SCRIPT_DIR)


def _save_local(conv: dict) -> str:
    """Save normalized conversation dict to local JSON file. Returns path."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    session_id = conv.get("session_id", "unknown")
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    path = os.path.join(_DATA_DIR, f"{safe_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)
    return path


def _existing_local_ids() -> set:
    """Return set of session IDs already saved locally."""
    ids: set = set()
    if not os.path.isdir(_DATA_DIR):
        return ids
    for filename in os.listdir(_DATA_DIR):
        if filename.endswith(".json"):
            # session_id is stored inside the JSON, but for speed we can also
            # derive it from the filename (filename = safe_id + .json)
            ids.add(filename[:-5])  # strip .json
    return ids


# ---------------------------------------------------------------------------
# Claude Code backfill
# ---------------------------------------------------------------------------

def backfill_claude_code(dry_run: bool = False) -> int:
    """Re-parse Claude Code sessions and save local JSON files."""
    try:
        from ingest_claude_code import (
            CLAUDE_PROJECTS_DIR,
            parse_session,
            read_sessions_index,
        )
    except ImportError as exc:
        print(f"  Cannot import ingest_claude_code: {exc}")
        return 0

    if not CLAUDE_PROJECTS_DIR.is_dir():
        print(f"  Claude Code projects dir not found: {CLAUDE_PROJECTS_DIR}")
        return 0

    existing = _existing_local_ids()
    saved = 0

    for project_dir in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if not project_dir.is_dir():
            continue

        entries = read_sessions_index(project_dir)
        if not entries:
            continue

        for entry in entries:
            session_id = entry.get("sessionId", "")
            if not session_id:
                continue

            safe_id = session_id.replace("/", "_").replace("\\", "_")
            if safe_id in existing:
                continue

            jsonl_path = project_dir / f"{session_id}.jsonl"
            if not jsonl_path.exists():
                continue

            if dry_run:
                title = entry.get("summary") or entry.get("firstPrompt") or "(untitled)"
                print(f"    Would save: {title[:60]}")
                saved += 1
                continue

            conversation = parse_session(jsonl_path)
            if conversation is None:
                continue

            # Enrich with index metadata
            conversation["title"] = (
                entry.get("summary")
                or entry.get("firstPrompt")
                or "(untitled session)"
            )
            conversation["session_id"] = session_id
            if not conversation.get("project_path"):
                conversation["project_path"] = entry.get("projectPath")
            if not conversation.get("git_branch"):
                conversation["git_branch"] = entry.get("gitBranch")
            if not conversation.get("created_at"):
                conversation["created_at"] = entry.get("created", "")

            _save_local(conversation)
            saved += 1

    return saved


# ---------------------------------------------------------------------------
# Codex backfill
# ---------------------------------------------------------------------------

def backfill_codex(dry_run: bool = False) -> int:
    """Re-parse Codex sessions and save local JSON files."""
    try:
        from ingest_codex import (
            CODEX_SESSIONS_DIR,
            discover_session_files,
            normalise_session,
            parse_jsonl_file,
        )
    except ImportError as exc:
        print(f"  Cannot import ingest_codex: {exc}")
        return 0

    sessions_dir = os.path.expanduser(CODEX_SESSIONS_DIR)
    if not os.path.isdir(sessions_dir):
        print(f"  Codex sessions dir not found: {sessions_dir}")
        return 0

    existing = _existing_local_ids()
    session_files = discover_session_files(sessions_dir)
    saved = 0

    for file_path in session_files:
        try:
            session = parse_jsonl_file(file_path)
        except (ValueError, OSError):
            continue

        session_id = session.get("session_id", "")
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        if safe_id in existing:
            continue

        if dry_run:
            print(f"    Would save: {os.path.basename(file_path)}")
            saved += 1
            continue

        try:
            conv = normalise_session(session)
        except Exception:
            continue

        if conv["metadata"]["total_turns"] == 0:
            continue

        _save_local(conv)
        saved += 1

    return saved


# ---------------------------------------------------------------------------
# ChatGPT backfill
# ---------------------------------------------------------------------------

def backfill_chatgpt(json_path: str, dry_run: bool = False) -> int:
    """Re-parse ChatGPT conversations.json and save local JSON files."""
    if not json_path:
        print("  No --chatgpt-json path provided. Skipping ChatGPT backfill.")
        return 0

    if not os.path.isfile(json_path):
        print(f"  ChatGPT JSON not found: {json_path}")
        return 0

    try:
        from ingest_chatgpt import normalise_conversation as normalise_chatgpt
    except ImportError as exc:
        print(f"  Cannot import ingest_chatgpt: {exc}")
        return 0

    print(f"  Loading {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        raw_conversations = json.load(f)

    if not isinstance(raw_conversations, list):
        print("  Error: conversations.json is not a list.")
        return 0

    existing = _existing_local_ids()
    saved = 0

    for raw in raw_conversations:
        session_id = raw.get("id", "")
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        if safe_id in existing:
            continue

        if dry_run:
            title = raw.get("title") or "(untitled)"
            print(f"    Would save: {title[:60]}")
            saved += 1
            continue

        try:
            conv = normalise_chatgpt(raw)
        except Exception:
            continue

        if conv["metadata"]["total_turns"] == 0:
            continue

        _save_local(conv)
        saved += 1

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill local JSON files from source conversation data.",
    )
    parser.add_argument(
        "--platform",
        choices=["claude_code", "codex", "chatgpt", "all"],
        default="all",
        help="Which platform(s) to backfill. (default: all)",
    )
    parser.add_argument(
        "--chatgpt-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to ChatGPT conversations.json (required for ChatGPT backfill).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be backfilled without writing files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    platform = args.platform
    dry_run = args.dry_run

    print("=" * 60)
    print("  Backfill Local Conversation Files")
    print("=" * 60)
    if dry_run:
        print("  ** DRY RUN — no files will be written **")
    print()

    total_saved = 0

    if platform in ("claude_code", "all"):
        print("[Claude Code]")
        count = backfill_claude_code(dry_run=dry_run)
        print(f"  {'Would save' if dry_run else 'Saved'}: {count} conversation(s)")
        total_saved += count
        print()

    if platform in ("codex", "all"):
        print("[Codex]")
        count = backfill_codex(dry_run=dry_run)
        print(f"  {'Would save' if dry_run else 'Saved'}: {count} conversation(s)")
        total_saved += count
        print()

    if platform in ("chatgpt", "all"):
        print("[ChatGPT]")
        count = backfill_chatgpt(args.chatgpt_json or "", dry_run=dry_run)
        print(f"  {'Would save' if dry_run else 'Saved'}: {count} conversation(s)")
        total_saved += count
        print()

    print("=" * 60)
    print(f"  Total: {total_saved} conversation(s) {'would be saved' if dry_run else 'saved'}")
    print(f"  Output directory: {_DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
