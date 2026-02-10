#!/usr/bin/env python3
"""Helper for skill-based LLM metadata enrichment (Mode F).

Provides file I/O operations so Claude Code can focus on analysis.

Subcommands:
    status                          Show enrichment progress
    list   [--pending] [--limit N]  List conversations
    digest <session_id>             Print compact digest for LLM analysis
    write  <session_id> <json>      Write llm_metadata to a conversation file
    verify <session_id>             Validate llm_metadata fields

Usage:
    python scripts/enrich_helper.py status
    python scripts/enrich_helper.py list --pending --limit 20
    python scripts/enrich_helper.py digest abc-123-def
    python scripts/enrich_helper.py write abc-123-def /tmp/meta.json
    python scripts/enrich_helper.py verify abc-123-def
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_DATA_DIR = os.path.join(_SCRIPT_DIR, os.pardir, "data", "conversations")


def build_conversation_digest(conv: Dict[str, Any]) -> str:
    """Build a compact text digest of a conversation for LLM analysis.

    Returns a formatted string summary suitable for metadata extraction.
    """
    lines = []

    # Header
    title = conv.get("title", "Untitled")
    source = conv.get("source", "unknown")
    model = conv.get("model") or "unknown"
    created = conv.get("created_at", "")[:10]
    lines.append(f"=== {title} ===")
    lines.append(f"Source: {source} | Model: {model} | Date: {created}")

    turns = conv.get("turns", [])
    meta = conv.get("metadata", {})
    lines.append(f"Turns: {len(turns)} | Language: {meta.get('primary_language', 'unknown')}")
    lines.append(f"Detected domains: {', '.join(meta.get('detected_domains', []))}")
    lines.append("")

    # Tool usage summary
    tool_counts: Dict[str, int] = {}
    for t in turns:
        for tu in t.get("assistant_response", {}).get("tool_uses", []):
            tn = tu.get("tool_name", "")
            if tn:
                tool_counts[tn] = tool_counts.get(tn, 0) + 1
    if tool_counts:
        top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
        lines.append(f"Top tools: {', '.join(f'{t}({c})' for t, c in top_tools)}")
        lines.append("")

    # Conversation flow (first 10 turns, abbreviated)
    lines.append("--- Conversation Flow ---")
    for i, turn in enumerate(turns[:10]):
        user_msg = turn.get("user_message", {}).get("content", "")[:150]
        assist_msg = turn.get("assistant_response", {}).get("content", "")[:100]
        corrections = turn.get("corrections", [])

        lines.append(f"[T{i+1}] User: {user_msg}")
        if corrections:
            lines.append(f"  [CORRECTION: {corrections[0].get('type', 'unknown')}]")
        lines.append(f"  Assistant: {assist_msg}...")

    if len(turns) > 10:
        lines.append(f"... ({len(turns) - 10} more turns)")

    # Last turn (for outcome detection)
    if len(turns) > 1:
        last_user = turns[-1].get("user_message", {}).get("content", "")[:200]
        lines.append("")
        lines.append(f"[Last User Message]: {last_user}")

    return "\n".join(lines)

# Required top-level keys in llm_metadata (the user-supplied part).
_REQUIRED_FIELDS = {
    "conversation_intent": str,
    "task_type": str,
    "actual_domains": list,
    "difficulty": (int, float),
    "outcome": str,
    "key_topics": list,
    "prompt_quality": dict,
    "correction_analysis": list,
    "cognitive_patterns": list,
    "conversation_summary": str,
}

_VALID_TASK_TYPES = {
    "debugging", "new-feature", "research", "learning", "refactoring",
    "documentation", "deployment", "configuration", "brainstorming",
    "code-review", "data-analysis", "writing", "design", "other",
}

_VALID_OUTCOMES = {"resolved", "partial", "abandoned", "exploratory"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_conversations() -> List[Dict[str, Any]]:
    """Yield (filepath, basic_info) for all conversation JSON files."""
    data_dir = os.path.normpath(_DATA_DIR)
    if not os.path.isdir(data_dir):
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    results = []
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                conv = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        has_meta = bool(conv.get("metadata", {}).get("llm_metadata"))
        results.append({
            "file": fpath,
            "session_id": conv.get("session_id", fname.replace(".json", "")),
            "source": conv.get("source", "unknown"),
            "title": (conv.get("title") or "")[:60],
            "turns": len(conv.get("turns", [])),
            "enriched": has_meta,
        })
    return results


def _load_conversation(session_id: str) -> tuple:
    """Load a conversation by session_id. Returns (filepath, conv_dict)."""
    data_dir = os.path.normpath(_DATA_DIR)
    fpath = os.path.join(data_dir, f"{session_id}.json")
    if not os.path.isfile(fpath):
        print(f"Error: file not found: {fpath}", file=sys.stderr)
        sys.exit(1)
    with open(fpath, "r", encoding="utf-8") as fh:
        return fpath, json.load(fh)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    """Show enrichment progress."""
    convs = _iter_conversations()
    total = len(convs)
    enriched = sum(1 for c in convs if c["enriched"])
    pending = total - enriched

    by_source: Dict[str, Dict[str, int]] = {}
    for c in convs:
        src = c["source"]
        if src not in by_source:
            by_source[src] = {"total": 0, "enriched": 0, "pending": 0}
        by_source[src]["total"] += 1
        if c["enriched"]:
            by_source[src]["enriched"] += 1
        else:
            by_source[src]["pending"] += 1

    print(f"Total: {total}  |  Enriched: {enriched}  |  Pending: {pending}")
    print()
    print(f"{'Source':<16} {'Total':>6} {'Enriched':>9} {'Pending':>8}")
    print("-" * 42)
    for src in sorted(by_source):
        s = by_source[src]
        print(f"{src:<16} {s['total']:>6} {s['enriched']:>9} {s['pending']:>8}")


def cmd_list(args: argparse.Namespace) -> None:
    """List conversations as JSON array."""
    convs = _iter_conversations()

    if args.pending:
        convs = [c for c in convs if not c["enriched"]]

    if args.source:
        convs = [c for c in convs if c["source"] == args.source]

    if args.limit and args.limit > 0:
        convs = convs[:args.limit]

    # Output compact info (drop 'file' and 'enriched' for cleaner output)
    output = [
        {
            "session_id": c["session_id"],
            "source": c["source"],
            "title": c["title"],
            "turns": c["turns"],
        }
        for c in convs
    ]
    print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_digest(args: argparse.Namespace) -> None:
    """Print compact text digest for a conversation."""
    _fpath, conv = _load_conversation(args.session_id)
    digest = build_conversation_digest(conv)
    print(digest)


def cmd_batch_digest(args: argparse.Namespace) -> None:
    """Print compact digests for multiple conversations (Agent Skill batch mode).

    Outputs a JSON array where each item has session_id + compact_digest.
    Filters to conversations missing quality metadata (heuristic or none).
    """
    convs = _iter_conversations()
    # Filter to only heuristic or un-enriched
    pending = []
    data_dir = os.path.normpath(_DATA_DIR)
    for c in convs:
        fpath = c["file"]
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                conv = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        meta = conv.get("metadata", {}).get("llm_metadata")
        if meta and meta.get("model_used") != "heuristic-v1":
            continue  # Already has quality metadata
        pending.append((c, conv))

    if args.source:
        pending = [(c, conv) for c, conv in pending if c["source"] == args.source]

    limit = args.limit or 20
    pending = pending[:limit]

    results = []
    for c, conv in pending:
        title = conv.get("title", "")
        source = conv.get("source", "")
        model = conv.get("model") or ""
        turns = conv.get("turns", [])
        meta = conv.get("metadata", {})
        lang = meta.get("primary_language", "")

        # First user message (compact)
        first_msg = ""
        if turns:
            first_msg = turns[0].get("user_message", {}).get("content", "")[:200]

        # Tool summary
        tool_names = []
        for t in turns:
            for tu in t.get("assistant_response", {}).get("tool_uses", []):
                tn = tu.get("tool_name", "")
                if tn and tn not in tool_names:
                    tool_names.append(tn)

        # Corrections count
        corr_count = sum(1 for t in turns if t.get("corrections"))

        # Last user message (for outcome detection)
        last_msg = ""
        if len(turns) > 1:
            last_msg = turns[-1].get("user_message", {}).get("content", "")[:100]

        results.append({
            "sid": c["session_id"],
            "src": source,
            "model": model[:30],
            "title": title[:80],
            "lang": lang,
            "turns": len(turns),
            "first": first_msg,
            "last": last_msg,
            "tools": tool_names[:10],
            "corrections": corr_count,
            "domains": meta.get("detected_domains", []),
        })

    print(json.dumps(results, indent=1, ensure_ascii=False))


def cmd_batch_write(args: argparse.Namespace) -> None:
    """Write llm_metadata for multiple conversations from a JSON file.

    Expects a JSON object: { "session_id": { ...llm_metadata_fields... }, ... }
    """
    json_path = args.json_file
    if json_path == "-":
        raw = sys.stdin.read()
    else:
        if not os.path.isfile(json_path):
            print(f"Error: JSON file not found: {json_path}", file=sys.stderr)
            sys.exit(1)
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = fh.read()

    try:
        batch_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(batch_data, dict):
        print("Error: expected JSON object { session_id: metadata, ... }", file=sys.stderr)
        sys.exit(1)

    data_dir = os.path.normpath(_DATA_DIR)
    ok = 0
    fail = 0

    for session_id, llm_data in batch_data.items():
        fpath = os.path.join(data_dir, f"{session_id}.json")
        if not os.path.isfile(fpath):
            print(f"SKIP: {session_id} (file not found)")
            fail += 1
            continue

        errors = _validate_llm_data(llm_data)
        if errors:
            print(f"FAIL: {session_id} — {'; '.join(errors)}")
            fail += 1
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                conv = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"FAIL: {session_id} — {exc}")
            fail += 1
            continue

        llm_metadata = {
            "version": "1.0",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "model_used": "claude-code-skill",
            **llm_data,
        }

        if "metadata" not in conv:
            conv["metadata"] = {}
        conv["metadata"]["llm_metadata"] = llm_metadata
        conv["schema_version"] = "1.2"

        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(conv, fh, indent=2, ensure_ascii=False)

        summary = llm_data.get("conversation_summary", "")[:50]
        print(f"OK: {session_id} -> {llm_data.get('task_type', '?')} | {summary}")
        ok += 1

    print(f"\nBatch write: {ok} OK, {fail} failed, {ok + fail} total")


def cmd_write(args: argparse.Namespace) -> None:
    """Write llm_metadata to a conversation file."""
    fpath, conv = _load_conversation(args.session_id)

    # Load the metadata JSON
    json_path = args.json_file
    if json_path == "-":
        raw = sys.stdin.read()
    else:
        if not os.path.isfile(json_path):
            print(f"Error: JSON file not found: {json_path}", file=sys.stderr)
            sys.exit(1)
        with open(json_path, "r", encoding="utf-8") as fh:
            raw = fh.read()

    try:
        llm_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    # Validate required fields
    errors = _validate_llm_data(llm_data)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Wrap with version info
    llm_metadata = {
        "version": "1.0",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "claude-code-skill",
        **llm_data,
    }

    # Write to conversation
    if "metadata" not in conv:
        conv["metadata"] = {}
    conv["metadata"]["llm_metadata"] = llm_metadata
    conv["schema_version"] = "1.2"

    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(conv, fh, indent=2, ensure_ascii=False)

    summary = llm_data.get("conversation_summary", "")[:60]
    print(f"OK: {args.session_id} -> {llm_data.get('task_type', '?')} | {summary}")


def cmd_verify(args: argparse.Namespace) -> None:
    """Validate llm_metadata fields in a conversation."""
    _fpath, conv = _load_conversation(args.session_id)

    llm_meta = conv.get("metadata", {}).get("llm_metadata")
    if not llm_meta:
        print(f"FAIL: {args.session_id} — no llm_metadata found")
        sys.exit(1)

    errors = _validate_llm_data(llm_meta)
    if errors:
        print(f"FAIL: {args.session_id}")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"PASS: {args.session_id}")
    print(f"  task_type: {llm_meta.get('task_type')}")
    print(f"  outcome: {llm_meta.get('outcome')}")
    print(f"  difficulty: {llm_meta.get('difficulty')}")
    print(f"  domains: {llm_meta.get('actual_domains')}")
    print(f"  summary: {llm_meta.get('conversation_summary', '')[:80]}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_llm_data(data: dict) -> List[str]:
    """Validate llm_metadata fields. Returns list of error messages."""
    errors: List[str] = []

    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"missing required field: {field}")
            continue
        val = data[field]
        if not isinstance(val, expected_type):
            errors.append(
                f"{field}: expected {expected_type}, got {type(val).__name__}"
            )

    # Value checks
    task_type = data.get("task_type")
    if task_type and task_type not in _VALID_TASK_TYPES:
        errors.append(f"task_type '{task_type}' not in valid set: {_VALID_TASK_TYPES}")

    outcome = data.get("outcome")
    if outcome and outcome not in _VALID_OUTCOMES:
        errors.append(f"outcome '{outcome}' not in valid set: {_VALID_OUTCOMES}")

    difficulty = data.get("difficulty")
    if isinstance(difficulty, (int, float)) and not (1 <= difficulty <= 10):
        errors.append(f"difficulty {difficulty} out of range [1, 10]")

    pq = data.get("prompt_quality")
    if isinstance(pq, dict):
        score = pq.get("score")
        if score is not None and not (0 <= score <= 100):
            errors.append(f"prompt_quality.score {score} out of range [0, 100]")

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Helper for skill-based LLM metadata enrichment (Mode F).",
    )
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show enrichment progress")

    # list
    p_list = sub.add_parser("list", help="List conversations")
    p_list.add_argument("--pending", action="store_true", help="Only unenriched")
    p_list.add_argument("--limit", type=int, default=0, help="Max results")
    p_list.add_argument("--source", type=str, help="Filter by source platform")

    # digest
    p_digest = sub.add_parser("digest", help="Print compact digest for LLM analysis")
    p_digest.add_argument("session_id", help="Conversation session ID")

    # write
    p_write = sub.add_parser("write", help="Write llm_metadata to conversation file")
    p_write.add_argument("session_id", help="Conversation session ID")
    p_write.add_argument("json_file", help="Path to JSON file with llm_metadata (or '-' for stdin)")

    # verify
    p_verify = sub.add_parser("verify", help="Validate llm_metadata fields")
    p_verify.add_argument("session_id", help="Conversation session ID")

    # batch-digest
    p_bd = sub.add_parser("batch-digest", help="Print compact digests for batch Agent Skill processing")
    p_bd.add_argument("--limit", type=int, default=20, help="Max conversations (default 20)")
    p_bd.add_argument("--source", type=str, help="Filter by source platform")

    # batch-write
    p_bw = sub.add_parser("batch-write", help="Write llm_metadata for multiple conversations")
    p_bw.add_argument("json_file", help="JSON file: { session_id: metadata, ... } (or '-' for stdin)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "status": cmd_status,
        "list": cmd_list,
        "digest": cmd_digest,
        "write": cmd_write,
        "verify": cmd_verify,
        "batch-digest": cmd_batch_digest,
        "batch-write": cmd_batch_write,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
