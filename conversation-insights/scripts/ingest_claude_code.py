#!/usr/bin/env python3
"""
Import Claude Code conversation logs from ~/.claude/projects/ into Notion.

Usage::

    python scripts/ingest_claude_code.py [--since YYYY-MM-DD] [--project <project-dir-name>]

Options:
    --since YYYY-MM-DD      Only import sessions created on or after this date.
    --project <name>        Limit import to a single project directory name
                            (e.g. "-Users-allenzhou-projects-skills").

The script reads Claude Code's native log format, converts each session
into the unified conversation schema, and writes it to the Notion
Conversations database.  Sessions that already exist in Notion (matched
by session_id) are silently skipped for idempotent re-runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup -- allow ``python scripts/ingest_claude_code.py`` from the
# conversation-insights directory *or* from the repo root.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from notion_client import NotionClient  # noqa: E402
# llm_enricher removed - use Skill mode (enrich_helper.py) for metadata extraction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CONFIG_PATH = _SKILL_ROOT / "config.yaml"
SOURCE = "claude_code"
SCHEMA_VERSION = "1.1"

# Notion page body has a maximum of 100 blocks per append call.
NOTION_BLOCK_BATCH_SIZE = 100
_DATA_DIR = _SKILL_ROOT / "data" / "conversations"


def _save_local(conv: dict) -> None:
    """Save normalized conversation dict to local JSON file."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    session_id = conv.get("session_id", "unknown")
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    path = _DATA_DIR / f"{safe_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)


def load_client() -> NotionClient:
    """Load a NotionClient from config.yaml. Exits on failure."""
    if not CONFIG_PATH.exists():
        print(
            f"Error: config file not found at {CONFIG_PATH}\n"
            "Run  python scripts/notion_setup.py  first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return NotionClient.load_config(str(CONFIG_PATH))


# ---------------------------------------------------------------------------
# Language detection (heuristic, standard library only)
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_language(text: str) -> str:
    """
    Classify *text* as ``"en"``, ``"zh"``, or ``"mixed"`` based on the
    proportion of CJK characters.
    """
    if not text:
        return "en"
    total = len(text)
    cjk_count = len(_CJK_RE.findall(text))
    ratio = cjk_count / total
    if ratio > 0.30:
        return "zh"
    if ratio < 0.05:
        return "en"
    return "mixed"


# ---------------------------------------------------------------------------
# Correction detection
# ---------------------------------------------------------------------------

_CORRECTION_PATTERNS: List[Tuple[str, str]] = [
    # (regex pattern, correction type)
    # Negation openers
    (r"(?i)^no[,.\s]", "factual"),
    (r"^不是", "factual"),
    (r"^不对", "factual"),
    (r"(?i)\bwrong\b", "factual"),
    # Restatement
    (r"(?i)\bI meant\b", "scope"),
    (r"我的意思是", "scope"),
    (r"(?i)\binstead\b", "approach"),
    # Scope adjustment
    (r"(?i)^only\b", "scope"),
    (r"(?i)^just\b", "scope"),
    (r"只需要", "scope"),
    (r"不要", "scope"),
    (r"别", "scope"),
    # Method negation
    (r"(?i)\bdon'?t use\b", "approach"),
    (r"别用", "approach"),
    (r"换个方式", "approach"),
]

_COMPILED_CORRECTION_PATTERNS = [
    (re.compile(pat), ctype) for pat, ctype in _CORRECTION_PATTERNS
]


def detect_corrections(text: str) -> List[Dict[str, str]]:
    """Return a list of correction indicators found in *text*."""
    corrections: List[Dict[str, str]] = []
    seen_types: set[str] = set()
    for regex, ctype in _COMPILED_CORRECTION_PATTERNS:
        m = regex.search(text)
        if m and ctype not in seen_types:
            corrections.append({"type": ctype, "indicator": m.group()})
            seen_types.add(ctype)
    return corrections


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------

def extract_text_from_content(content: Any) -> str:
    """
    Extract plain text from a Claude Code message ``content`` field.

    ``content`` may be a plain string or a list of typed blocks.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_result":
            # tool_result may contain nested content
            inner = block.get("content", "")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                for sub in inner:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        parts.append(sub.get("text", ""))
    return "\n".join(parts)


def extract_tool_uses(content: Any) -> List[Dict[str, Any]]:
    """
    Extract tool_use entries from an assistant message content list.

    Returns a list of dicts with tool_name and input parameters.
    Success is filled in later during turn pairing.
    """
    if not isinstance(content, list):
        return []
    tools: List[Dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            raw_input = block.get("input", {})

            # Extract relevant input parameters based on tool type
            tool_input: Optional[Dict[str, Any]] = None
            if isinstance(raw_input, dict):
                file_path = raw_input.get("file_path") or raw_input.get("path")
                pattern = raw_input.get("pattern")
                command = raw_input.get("command")

                if file_path or pattern or command:
                    tool_input = {}
                    if file_path:
                        tool_input["file_path"] = file_path
                    if pattern:
                        tool_input["pattern"] = pattern
                    if command:
                        tool_input["command"] = command[:500]  # truncate long commands

            tools.append({
                "tool_name": name,
                "input": tool_input,
                "id": block.get("id", ""),  # Keep ID for success attribution
            })
    return tools


def has_thinking(content: Any) -> bool:
    """Return True if the assistant content includes a thinking block."""
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "thinking" for b in content
    )


def has_code_in_text(text: str) -> bool:
    """Heuristic: does *text* contain inline code or code fences?"""
    return "```" in text or bool(re.search(r"`[^`]+`", text))


def parse_file_history_snapshot(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse a file-history-snapshot entry into a list of file changes.

    The file-history-snapshot contains information about files that were
    added, modified, or deleted during the session.

    Returns a list of dicts with:
        - path: str (file path)
        - action: str ("add" | "modify" | "delete")
        - lines_added: int | None
        - lines_removed: int | None
    """
    file_changes: List[Dict[str, Any]] = []

    # file-history-snapshot structure varies; handle different formats
    files = obj.get("files", {})
    if isinstance(files, dict):
        for file_path, file_info in files.items():
            if not isinstance(file_info, dict):
                continue

            # Determine action from available fields
            action = "modify"  # default
            if file_info.get("added") or file_info.get("isNew"):
                action = "add"
            elif file_info.get("deleted") or file_info.get("isDeleted"):
                action = "delete"

            # Extract line counts if available
            lines_added = file_info.get("linesAdded") or file_info.get("additions")
            lines_removed = file_info.get("linesRemoved") or file_info.get("deletions")

            file_changes.append({
                "path": file_path,
                "action": action,
                "lines_added": lines_added if isinstance(lines_added, int) else None,
                "lines_removed": lines_removed if isinstance(lines_removed, int) else None,
            })

    # Also handle "changes" array format
    changes = obj.get("changes", [])
    if isinstance(changes, list):
        for change in changes:
            if not isinstance(change, dict):
                continue
            file_path = change.get("path") or change.get("file")
            if not file_path:
                continue

            action = change.get("action", "modify")
            if action not in ("add", "modify", "delete"):
                action = "modify"

            file_changes.append({
                "path": file_path,
                "action": action,
                "lines_added": change.get("linesAdded"),
                "lines_removed": change.get("linesRemoved"),
            })

    return file_changes


def has_file_reference(text: str) -> bool:
    """Heuristic: does *text* reference file paths?"""
    return bool(
        re.search(
            r"(?:^|[\s\"'(])"           # boundary
            r"(?:\.{0,2}/[\w./-]+|"     # relative or absolute path
            r"[A-Za-z]:\\[\w.\\/-]+)",   # Windows path
            text,
        )
    )


def _tool_results_from_user(content: Any) -> Dict[str, bool]:
    """
    Scan a user message content list for tool_result blocks.

    Returns a mapping of ``tool_use_id -> success`` derived from
    ``is_error`` being absent or ``false``.
    """
    results: Dict[str, bool] = {}
    if not isinstance(content, list):
        return results
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tool_use_id = block.get("tool_use_id", "")
            is_error = block.get("is_error", False)
            results[tool_use_id] = not is_error
    return results


def _tool_use_ids(content: Any) -> List[str]:
    """Extract the ``id`` of each tool_use block from assistant content."""
    if not isinstance(content, list):
        return []
    return [
        b.get("id", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# Session parsing
# ---------------------------------------------------------------------------

def parse_session(jsonl_path: Path) -> Optional[Dict[str, Any]]:
    """
    Parse a single ``.jsonl`` session file into the unified conversation
    schema dict.  Returns ``None`` if the file cannot be read or
    contains no usable turns.
    """
    if not jsonl_path.exists():
        return None

    messages: List[Dict[str, Any]] = []
    has_file_changes = False
    has_sidechains = False
    all_file_changes: List[Dict[str, Any]] = []  # NEW: collect file changes

    with open(jsonl_path, encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type", "")

            if msg_type == "file-history-snapshot":
                has_file_changes = True
                # NEW: parse file changes from snapshot
                snapshot_changes = parse_file_history_snapshot(obj)
                all_file_changes.extend(snapshot_changes)
                continue

            if msg_type in ("progress", "summary"):
                continue

            if msg_type in ("user", "assistant"):
                if obj.get("isMeta"):
                    continue
                if obj.get("isSidechain"):
                    has_sidechains = True
                messages.append(obj)

    if not messages:
        return None

    # Sort by timestamp for linear pairing
    messages.sort(key=lambda m: m.get("timestamp", ""))

    # ------------------------------------------------------------------
    # Turn pairing: walk through messages and pair consecutive
    # user -> assistant sequences.
    # ------------------------------------------------------------------
    turns: List[Dict[str, Any]] = []
    turn_id = 0
    i = 0
    all_languages: List[str] = []

    while i < len(messages):
        msg = messages[i]

        # We expect a user message to start a turn.
        if msg.get("type") != "user":
            i += 1
            continue

        user_content = msg.get("message", {}).get("content", "")
        user_text = extract_text_from_content(user_content)

        # Skip empty user messages that are purely tool results
        if not user_text.strip() and isinstance(user_content, list):
            # Still might carry tool_result info needed for previous turn
            # success attribution -- handled below.
            pass

        # Look for a following assistant message
        assistant_msg: Optional[Dict[str, Any]] = None
        if i + 1 < len(messages) and messages[i + 1].get("type") == "assistant":
            assistant_msg = messages[i + 1]

        # Attribute tool success from this user message to previous turn
        if turns and isinstance(user_content, list):
            tool_results = _tool_results_from_user(user_content)
            if tool_results:
                prev_turn = turns[-1]
                for tu in prev_turn["assistant_response"]["tool_uses"]:
                    # Match by position if IDs not available
                    if tu.get("success") is None:
                        # Mark all pending as successful if any result is ok
                        for _tid, success in tool_results.items():
                            tu["success"] = success
                            break

        # Skip turns with no meaningful text and no assistant response
        if not user_text.strip() and assistant_msg is None:
            i += 1
            continue

        lang = detect_language(user_text)
        all_languages.append(lang)

        user_wc = word_count(user_text)

        # Corrections: only detect if this is not the first turn
        corrections: List[Dict[str, str]] = []
        if turn_id > 0 and user_text.strip():
            corrections = detect_corrections(user_text)

        # Build user_message dict
        user_message: Dict[str, Any] = {
            "content": user_text[:5000],  # cap for Notion size
            "word_count": user_wc,
            "language": lang,
            "has_code": has_code_in_text(user_text),
            "has_file_reference": has_file_reference(user_text),
        }

        # Build assistant_response dict
        if assistant_msg is not None:
            a_content = assistant_msg.get("message", {}).get("content", "")
            a_text = extract_text_from_content(a_content)
            a_tools = extract_tool_uses(a_content)
            a_thinking = has_thinking(a_content)
            a_tool_ids = _tool_use_ids(a_content)

            # Try to fill tool success from the *next* user message
            next_user_idx = i + 2
            if next_user_idx < len(messages) and messages[next_user_idx].get("type") == "user":
                next_user_content = messages[next_user_idx].get("message", {}).get("content", "")
                next_results = _tool_results_from_user(next_user_content)
                if next_results and a_tool_ids:
                    for idx, tool_id in enumerate(a_tool_ids):
                        if tool_id in next_results and idx < len(a_tools):
                            a_tools[idx]["success"] = next_results[tool_id]

            assistant_response: Dict[str, Any] = {
                "content": a_text[:5000],
                "word_count": word_count(a_text),
                "tool_uses": [
                    {
                        "tool_name": t["tool_name"],
                        "success": t.get("success"),
                        "input": t.get("input"),  # NEW: include tool input
                    }
                    for t in a_tools
                ],
                "has_thinking": a_thinking,
            }
            i += 2  # consumed both user and assistant
        else:
            assistant_response = {
                "content": "",
                "word_count": 0,
                "tool_uses": [],
                "has_thinking": False,
            }
            i += 1  # consumed only user

        timestamp = msg.get("timestamp", "")

        turn: Dict[str, Any] = {
            "turn_id": turn_id,
            "timestamp": timestamp if timestamp else None,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "corrections": corrections,
        }
        turns.append(turn)
        turn_id += 1

    if not turns:
        return None

    # Determine primary language
    lang_counts: Dict[str, int] = {}
    for lang in all_languages:
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    primary_language = max(lang_counts, key=lang_counts.get) if lang_counts else "en"

    total_tool_uses = sum(
        len(t["assistant_response"]["tool_uses"]) for t in turns
    )

    # Deduplicate file_changes by path (keep last occurrence)
    seen_paths: Dict[str, Dict[str, Any]] = {}
    for fc in all_file_changes:
        seen_paths[fc["path"]] = fc
    deduped_file_changes = list(seen_paths.values()) if seen_paths else None

    metadata: Dict[str, Any] = {
        "total_turns": len(turns),
        "total_tool_uses": total_tool_uses,
        "primary_language": primary_language,
        "detected_domains": [],  # populated by analysis scripts
        "has_sidechains": has_sidechains,
        "has_file_changes": has_file_changes,
        "token_count": None,
        "file_changes": deduped_file_changes,  # NEW: detailed file changes
    }

    # Extract session-level fields from the first message
    first_msg = messages[0]
    project_path = first_msg.get("cwd", "")
    git_branch = first_msg.get("gitBranch", "")
    session_id = first_msg.get("sessionId", jsonl_path.stem)
    created_at = first_msg.get("timestamp", "")

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "source": SOURCE,
        "model": None,  # Claude Code logs don't consistently include model
        "project_path": project_path or None,
        "title": "",  # filled in by caller from sessions-index
        "created_at": created_at,
        "git_branch": git_branch or None,
        "turns": turns,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Sessions index reader
# ---------------------------------------------------------------------------

def read_sessions_index(project_dir: Path) -> List[Dict[str, Any]]:
    """Read and return entries from a project's sessions-index.json."""
    index_path = project_dir / "sessions-index.json"
    if not index_path.exists():
        return []
    try:
        with open(index_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("entries", [])


# ---------------------------------------------------------------------------
# Notion deduplication
# ---------------------------------------------------------------------------

def fetch_existing_session_ids(
    client: NotionClient, db_id: str
) -> set[str]:
    """
    Query the Notion Conversations database and return the set of
    session IDs already imported for the ``claude_code`` source.
    """
    filter_payload = {
        "property": "Source",
        "select": {"equals": SOURCE},
    }
    pages = client.query_database(db_id, filter=filter_payload)

    ids: set[str] = set()
    for page in pages:
        props = page.get("properties", {})
        sid_prop = props.get("Session ID", {})
        rt = sid_prop.get("rich_text", [])
        if rt:
            ids.add(rt[0].get("plain_text", ""))
    return ids


# ---------------------------------------------------------------------------
# Notion page builder
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 2000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def build_notion_properties(
    conversation: Dict[str, Any],
) -> Dict[str, Any]:
    """Build Notion property values for a Conversations DB page."""
    NC = NotionClient  # shorthand for static helpers

    title = conversation.get("title") or "(untitled)"
    meta = conversation.get("metadata", {})

    props: Dict[str, Any] = {
        "Title": NC.prop_title(_truncate(title)),
        "Session ID": NC.prop_rich_text(conversation["session_id"]),
        "Source": NC.prop_select(SOURCE),
        "Total Turns": NC.prop_number(meta.get("total_turns", 0)),
        "Total Tool Uses": NC.prop_number(meta.get("total_tool_uses", 0)),
        "Language": NC.prop_select(meta.get("primary_language", "en")),
        "Processed": NC.prop_checkbox(False),
    }

    if conversation.get("model"):
        props["Model"] = NC.prop_rich_text(conversation["model"])

    if conversation.get("project_path"):
        props["Project Path"] = NC.prop_rich_text(conversation["project_path"])

    if conversation.get("created_at"):
        # Notion dates need ISO-8601; strip sub-second and ensure timezone
        created = conversation["created_at"]
        props["Created At"] = NC.prop_date(created[:19] if len(created) > 19 else created)

    if conversation.get("git_branch"):
        props["Git Branch"] = NC.prop_rich_text(conversation["git_branch"])

    domains = meta.get("detected_domains", [])
    if domains:
        props["Domains"] = NC.prop_multi_select(domains[:10])

    return props


def build_notion_body_blocks(
    conversation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Build Notion block children representing the conversation body.

    Each turn becomes a toggle heading with user message, assistant
    summary, and tool call details inside.
    """
    NC = NotionClient
    blocks: List[Dict[str, Any]] = []

    # Summary header
    meta = conversation.get("metadata", {})
    summary_parts = [
        f"Turns: {meta.get('total_turns', 0)}",
        f"Tool uses: {meta.get('total_tool_uses', 0)}",
        f"Language: {meta.get('primary_language', 'en')}",
    ]
    if meta.get("has_sidechains"):
        summary_parts.append("Has sidechains")
    if meta.get("has_file_changes"):
        summary_parts.append("Has file changes")

    blocks.append(NC.paragraph(" | ".join(summary_parts)))
    blocks.append(NC.divider())

    turns = conversation.get("turns", [])

    for turn in turns:
        tid = turn["turn_id"]
        user_msg = turn.get("user_message", {})
        asst = turn.get("assistant_response", {})
        corrections = turn.get("corrections", [])

        # Build inner children for this turn's toggle
        inner: List[Dict[str, Any]] = []

        # User message
        user_content = user_msg.get("content", "")
        if user_content:
            inner.append(NC.paragraph(f"[User] {_truncate(user_content, 1900)}"))

        # Assistant response summary
        asst_content = asst.get("content", "")
        if asst_content:
            inner.append(
                NC.paragraph(f"[Assistant] {_truncate(asst_content, 1900)}")
            )

        # Tool uses
        tool_uses = asst.get("tool_uses", [])
        if tool_uses:
            tool_lines = []
            for tu in tool_uses:
                status = "ok" if tu.get("success") else ("fail" if tu.get("success") is False else "?")
                tool_lines.append(f"{tu['tool_name']} [{status}]")
            inner.append(
                NC.bulleted_list("Tools: " + ", ".join(tool_lines))
            )

        # Corrections
        if corrections:
            corr_text = ", ".join(
                f"{c['type']}({c['indicator']})" for c in corrections
            )
            inner.append(NC.bulleted_list(f"Corrections: {corr_text}"))

        # Turn header as toggle with children nested inside
        user_preview = _truncate(user_msg.get("content", ""), 80)
        toggle_text = f"Turn {tid + 1}: {user_preview}"
        blocks.append(NC.toggle(toggle_text, children=inner))

    return blocks


# ---------------------------------------------------------------------------
# Write to Notion
# ---------------------------------------------------------------------------

def write_to_notion(
    client: NotionClient,
    db_id: str,
    conversation: Dict[str, Any],
) -> str:
    """
    Create a Notion page for *conversation* in the Conversations DB.

    Returns the page ID of the created page.
    """
    properties = build_notion_properties(conversation)

    # Metadata-only: skip writing conversation body blocks to Notion.
    # Full conversation data lives in local JSON files.
    page = client.create_page(db_id, properties)
    return page["id"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Claude Code conversation logs into Notion.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Only import sessions created on or after this date.",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        metavar="DIR_NAME",
        help=(
            "Limit import to a single project directory name "
            "(e.g. -Users-allenzhou-projects-skills)."
        ),
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        default=True,
        help="Skip LLM API enrichment during import (default). Use Mode F or --use-llm-api.",
    )
    parser.add_argument(
        "--use-llm-api",
        action="store_true",
        default=False,
        help="Enable LLM metadata enrichment via Anthropic API during import.",
    )
    return parser.parse_args(argv)


def _parse_since(since_str: Optional[str]) -> Optional[datetime]:
    """Parse a ``YYYY-MM-DD`` string into a timezone-aware datetime."""
    if not since_str:
        return None
    try:
        dt = datetime.strptime(since_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: invalid --since date: {since_str!r}", file=sys.stderr)
        sys.exit(1)


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string into a datetime (best-effort)."""
    if not ts:
        return None
    # Handle various ISO-8601 flavours from Claude Code
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    since_dt = _parse_since(args.since)

    # LLM API enrichment removed - use Skill mode (enrich_helper.py) instead
    if args.use_llm_api:
        print("WARN: --use-llm-api is deprecated. Use enrich_helper.py for Skill mode.", file=sys.stderr)
        args.use_llm_api = False

    # Load configuration
    client = load_client()
    conversations_db_id = client.databases["conversations"]

    # Discover project directories
    if not CLAUDE_PROJECTS_DIR.is_dir():
        print(
            f"Claude Code projects directory not found: {CLAUDE_PROJECTS_DIR}",
            file=sys.stderr,
        )
        sys.exit(1)

    project_dirs: List[Path] = []
    for entry in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if args.project and entry.name != args.project:
            continue
        project_dirs.append(entry)

    if not project_dirs:
        if args.project:
            print(f"Project directory not found: {args.project}", file=sys.stderr)
        else:
            print("No project directories found.", file=sys.stderr)
        sys.exit(1)

    # Fetch already-imported session IDs for deduplication
    print("Fetching existing sessions from Notion for dedup...")
    try:
        existing_ids = fetch_existing_session_ids(client, conversations_db_id)
    except RuntimeError as exc:
        print(f"Error querying Notion: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  Found {len(existing_ids)} existing claude_code sessions in Notion.")

    # Counters
    total_imported = 0
    total_skipped_dedup = 0
    total_skipped_date = 0
    total_skipped_empty = 0
    total_errors = 0

    for project_dir in project_dirs:
        project_name = project_dir.name
        print(f"\nScanning project: {project_name}")

        entries = read_sessions_index(project_dir)
        if not entries:
            print("  No sessions-index.json or no entries -- skipping.")
            continue

        print(f"  Found {len(entries)} session(s) in index.")

        for entry in entries:
            session_id = entry.get("sessionId", "")
            if not session_id:
                continue

            # Date filtering
            created_str = entry.get("created", "")
            if since_dt and created_str:
                created_dt = _parse_timestamp(created_str)
                if created_dt and created_dt < since_dt:
                    total_skipped_date += 1
                    continue

            # Dedup check
            if session_id in existing_ids:
                total_skipped_dedup += 1
                continue

            # Determine title
            title = (
                entry.get("summary")
                or entry.get("firstPrompt")
                or "(untitled session)"
            )
            message_count = entry.get("messageCount", "?")

            # Parse the JSONL file
            jsonl_path = project_dir / f"{session_id}.jsonl"
            conversation = parse_session(jsonl_path)

            if conversation is None:
                total_skipped_empty += 1
                continue

            # Enrich with index metadata
            conversation["title"] = title
            conversation["session_id"] = session_id
            if not conversation.get("project_path"):
                conversation["project_path"] = entry.get("projectPath")
            if not conversation.get("git_branch"):
                conversation["git_branch"] = entry.get("gitBranch")
            if not conversation.get("created_at"):
                conversation["created_at"] = created_str

            print(
                f"  Importing session: {_truncate(title, 60)} "
                f"({message_count} messages)"
            )

            # LLM metadata enrichment removed - use Skill mode (enrich_helper.py) after import

            # Save to local JSON.
            _save_local(conversation)

            try:
                page_id = write_to_notion(client, conversations_db_id, conversation)
                total_imported += 1
                existing_ids.add(session_id)  # prevent re-import within run
            except RuntimeError as exc:
                print(f"    Error writing to Notion: {exc}", file=sys.stderr)
                total_errors += 1
            except Exception as exc:
                print(f"    Unexpected error: {exc}", file=sys.stderr)
                total_errors += 1

    # Summary
    print("\n" + "=" * 60)
    print("Import complete.")
    print(f"  Imported:          {total_imported}")
    print(f"  Skipped (exists):  {total_skipped_dedup}")
    print(f"  Skipped (date):    {total_skipped_date}")
    print(f"  Skipped (empty):   {total_skipped_empty}")
    print(f"  Errors:            {total_errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
