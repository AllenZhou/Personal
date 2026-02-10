#!/usr/bin/env python3
"""
Ingest Claude.ai web conversations from an exported JSON file into Notion.

Usage::

    python scripts/ingest_claude_web.py <path-to-export.json>
    python scripts/ingest_claude_web.py <path-to-export.json> --since 2024-06-01
    python scripts/ingest_claude_web.py --help

The script:
    1. Loads conversations from the Claude.ai JSON export file
    2. Parses the linear chat_messages array into paired turns
    3. Detects language and domains from user messages
    4. Deduplicates against existing Notion records (by session_id + source=claude_web)
    5. Creates Notion pages with properties and toggle-block turn bodies

Claude.ai data export format
-----------------------------
The export is a JSON array where each element represents a conversation::

    [
      {
        "uuid": "conversation-uuid",
        "name": "Conversation title",
        "created_at": "2024-01-15T10:30:00.000000+00:00",
        "updated_at": "2024-01-15T11:00:00.000000+00:00",
        "chat_messages": [
          {
            "uuid": "message-uuid",
            "text": "message content",
            "sender": "human",
            "created_at": "2024-01-15T10:30:00.000000+00:00",
            "attachments": [],
            "files": []
          },
          ...
        ]
      },
      ...
    ]

The ``sender`` field is typically ``"human"`` or ``"assistant"``.
Attachments and files metadata may be present but are not ingested.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup -- allow importing sibling modules from the scripts/ directory
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from notion_client import NotionClient  # noqa: E402
# llm_enricher removed - use Skill mode for metadata extraction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE = "claude_web"
SCHEMA_VERSION = "1.1"
MAX_BLOCK_TEXT_LENGTH = 2000
_DATA_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "data", "conversations"))


def _save_local(conv: dict) -> None:
    """Save normalized conversation dict to local JSON file."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    session_id = conv.get("session_id", "unknown")
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    path = os.path.join(_DATA_DIR, f"{safe_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)


# Domain keyword mapping used for lightweight detection.
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "frontend": [
        "react", "vue", "angular", "css", "html", "tailwind", "nextjs",
        "next.js", "svelte", "dom", "browser", "webpack", "vite",
        "javascript", "typescript", "jsx", "tsx", "styled-components",
    ],
    "backend": [
        "express", "fastapi", "django", "flask", "spring", "rails",
        "api", "rest", "graphql", "grpc", "server", "endpoint",
        "middleware", "routing", "controller",
    ],
    "devops": [
        "docker", "kubernetes", "k8s", "ci/cd", "jenkins", "github actions",
        "terraform", "ansible", "nginx", "helm", "aws", "gcp", "azure",
        "deployment", "pipeline", "infrastructure",
    ],
    "database": [
        "sql", "postgres", "mysql", "mongodb", "redis", "sqlite",
        "migration", "schema", "query", "index", "orm", "prisma",
        "sequelize", "typeorm", "knex",
    ],
    "data-science": [
        "pandas", "numpy", "matplotlib", "jupyter", "dataset",
        "visualization", "statistics", "analysis", "csv", "dataframe",
        "seaborn", "plotly", "scipy",
    ],
    "mobile": [
        "ios", "android", "react native", "flutter", "swift",
        "kotlin", "xcode", "mobile app",
    ],
    "security": [
        "authentication", "authorization", "oauth", "jwt", "cors",
        "encryption", "vulnerability", "xss", "csrf", "ssl", "tls",
        "password", "hash", "token",
    ],
    "testing": [
        "test", "jest", "pytest", "mocha", "cypress", "playwright",
        "unittest", "coverage", "mock", "stub", "fixture", "assertion",
    ],
    "documentation": [
        "readme", "docs", "documentation", "markdown", "jsdoc",
        "docstring", "comment", "specification",
    ],
    "architecture": [
        "design pattern", "microservice", "monolith", "clean architecture",
        "dependency injection", "solid", "refactor", "modular",
        "event-driven", "message queue",
    ],
    "legal": [
        "compliance", "regulation", "license", "gdpr", "privacy",
        "terms of service", "contract", "legal",
    ],
    "finance": [
        "payment", "stripe", "invoice", "accounting", "financial",
        "transaction", "billing", "subscription",
    ],
    "design": [
        "ui", "ux", "figma", "wireframe", "prototype", "layout",
        "color", "typography", "responsive", "accessibility",
    ],
    "ai-ml": [
        "machine learning", "deep learning", "neural network", "model",
        "training", "inference", "llm", "transformer", "embedding",
        "fine-tuning", "prompt engineering", "openai", "langchain",
        "vector", "rag", "agent",
    ],
}

# Correction detection patterns (from unified-schema.md).
CORRECTION_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)^no[,.\s]", "factual"),
    (r"^不是", "factual"),
    (r"^不对", "factual"),
    (r"(?i)\bwrong\b", "factual"),
    (r"(?i)\bI meant\b", "style"),
    (r"我的意思是", "style"),
    (r"(?i)\binstead\b", "style"),
    (r"(?i)\bonly\b", "scope"),
    (r"(?i)\bjust\b", "scope"),
    (r"只需要", "scope"),
    (r"不要", "scope"),
    (r"(?i)\bdon'?t use\b", "approach"),
    (r"别用", "approach"),
    (r"换个方式", "approach"),
]

_COMPILED_CORRECTIONS = [(re.compile(pat), ctype) for pat, ctype in CORRECTION_PATTERNS]


# ---------------------------------------------------------------------------
# Helpers -- language & domain detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Detect language using CJK character ratio heuristic."""
    if not text:
        return "en"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ratio = cjk_count / max(len(text), 1)
    if ratio > 0.3:
        return "zh"
    if ratio < 0.05:
        return "en"
    return "mixed"


def detect_domains(text: str) -> List[str]:
    """Return a sorted list of domain tags matched via keyword search."""
    lower = text.lower()
    matched: set = set()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                matched.add(domain)
                break
    return sorted(matched) if matched else ["other"]


def detect_corrections(text: str) -> List[Dict[str, str]]:
    """Detect user corrections via regex pattern matching."""
    found: List[Dict[str, str]] = []
    seen_types: set = set()
    for regex, ctype in _COMPILED_CORRECTIONS:
        m = regex.search(text)
        if m and ctype not in seen_types:
            found.append({"type": ctype, "indicator": m.group()})
            seen_types.add(ctype)
    return found


def _has_code(text: str) -> bool:
    """Check whether the text contains inline code or code blocks."""
    return "```" in text or bool(re.search(r"`[^`]+`", text))


def _has_file_reference(text: str) -> bool:
    """Heuristic to detect file path references in text."""
    return bool(re.search(r"[/\\][\w.\-]+(?:[/\\][\w.\-]+)+", text))


def _word_count(text: str) -> int:
    """Count words (handles both CJK-heavy and Latin text)."""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin_words = len(re.findall(r"[a-zA-Z0-9_]+", text))
    return cjk + latin_words


def truncate(text: str, max_len: int = MAX_BLOCK_TEXT_LENGTH) -> str:
    """Truncate text to *max_len* characters, adding an ellipsis when trimmed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_timestamp(ts: Optional[str]) -> Optional[str]:
    """
    Parse an ISO-8601 timestamp string from the Claude.ai export and
    return a normalised ISO-8601 string suitable for Notion.

    Returns ``None`` if *ts* is ``None`` or cannot be parsed.
    """
    if not ts:
        return None
    for fmt in _TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    # Fallback: return the original string if it looks like a date
    if "T" in ts or re.match(r"\d{4}-\d{2}-\d{2}", ts):
        return ts
    return None


def parse_timestamp_dt(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into a datetime object, or ``None``."""
    if not ts:
        return None
    for fmt in _TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

def _extract_messages(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract the ordered list of messages from a Claude.ai conversation.

    Handles both the ``chat_messages`` key and potential alternative
    structures that may appear in different export versions.  Messages
    are returned sorted by their ``created_at`` timestamp.
    """
    messages: List[Dict[str, Any]] = []

    # Primary format: chat_messages array
    raw_messages = conversation.get("chat_messages")
    if raw_messages is None:
        # Fallback: try 'messages' key
        raw_messages = conversation.get("messages", [])

    if not isinstance(raw_messages, list):
        return messages

    for msg in raw_messages:
        if not isinstance(msg, dict):
            continue
        sender = msg.get("sender", "").lower()
        text = msg.get("text", "")

        # Handle new export format where content is an array of blocks
        if not text:
            content_blocks = msg.get("content")
            if isinstance(content_blocks, list):
                # Extract text from content blocks (new format 2025+)
                text_parts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block_text = block.get("text", "")
                        if block_text:
                            text_parts.append(block_text)
                text = "\n".join(text_parts)
            elif isinstance(content_blocks, str):
                # Old format: content is a string
                text = content_blocks

        if not isinstance(text, str):
            text = str(text) if text else ""

        # Normalise sender values
        if sender in ("human", "user"):
            role = "human"
        elif sender in ("assistant", "bot"):
            role = "assistant"
        else:
            # Skip system messages or unknown roles
            continue

        messages.append({
            "uuid": msg.get("uuid", ""),
            "role": role,
            "text": text.strip(),
            "created_at": msg.get("created_at", ""),
            "attachments": msg.get("attachments", []),
            "files": msg.get("files", []),
        })

    # Sort by created_at for deterministic ordering
    messages.sort(key=lambda m: m.get("created_at", ""))
    return messages


# ---------------------------------------------------------------------------
# Turn pairing
# ---------------------------------------------------------------------------

def _pair_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pair consecutive human/assistant messages into turns following the
    unified conversation schema.

    Each turn contains a ``user_message`` and ``assistant_response``.
    Orphan assistant messages before the first human message are skipped.
    Consecutive human messages without an assistant reply create turns
    with empty assistant responses.
    """
    turns: List[Dict[str, Any]] = []
    turn_id = 0
    i = 0

    while i < len(messages):
        msg = messages[i]

        if msg["role"] != "human":
            # Skip orphan assistant messages before the first human message
            i += 1
            continue

        user_text = msg["text"]
        user_timestamp = msg["created_at"]
        user_attachments = msg.get("attachments", [])
        user_files = msg.get("files", [])

        # Collect attachment/file info
        attachment_count = len(user_attachments) + len(user_files)

        # Look ahead for the next assistant message
        assistant_text = ""
        assistant_timestamp = ""
        j = i + 1
        if j < len(messages) and messages[j]["role"] == "assistant":
            assistant_text = messages[j]["text"]
            assistant_timestamp = messages[j]["created_at"]
            j += 1

        turn_id += 1

        # Corrections: detect in user text (skip first turn to avoid
        # false positives on greetings)
        corrections: List[Dict[str, str]] = []
        if turn_id > 1 and user_text:
            corrections = detect_corrections(user_text)

        turns.append({
            "turn_id": turn_id,
            "timestamp": parse_timestamp(user_timestamp),
            "user_message": {
                "content": user_text,
                "word_count": _word_count(user_text),
                "language": detect_language(user_text),
                "has_code": _has_code(user_text),
                "has_file_reference": _has_file_reference(user_text),
                "attachment_count": attachment_count,
            },
            "assistant_response": {
                "content": assistant_text,
                "word_count": _word_count(assistant_text),
                "tool_uses": [],
                "has_thinking": False,
            },
            "corrections": corrections,
        })

        i = j

    return turns


# ---------------------------------------------------------------------------
# Conversation normalisation
# ---------------------------------------------------------------------------

def normalise_conversation(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a single raw Claude.ai conversation dict into the unified
    schema format described in ``references/unified-schema.md``.
    """
    messages = _extract_messages(raw)
    turns = _pair_turns(messages)

    # Aggregate user message text for language and domain detection.
    all_user_text = " ".join(t["user_message"]["content"] for t in turns)

    primary_language = detect_language(all_user_text)
    detected_domains = detect_domains(all_user_text)
    total_tool_uses = sum(
        len(t["assistant_response"]["tool_uses"]) for t in turns
    )

    # Extract conversation-level identifiers
    session_id = raw.get("uuid", raw.get("id", ""))
    title = raw.get("name", raw.get("title", "")) or "(untitled)"
    created_at = parse_timestamp(raw.get("created_at"))

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "source": SOURCE,
        "model": "claude",
        "project_path": None,
        "title": title,
        "created_at": created_at,
        "git_branch": None,
        "turns": turns,
        "metadata": {
            "total_turns": len(turns),
            "total_tool_uses": total_tool_uses,
            "primary_language": primary_language,
            "detected_domains": detected_domains,
            "has_sidechains": False,
            "has_file_changes": False,
            "file_changes": None,  # Claude Web typically has no file operations
            "token_count": None,
        },
    }


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))


def load_client(config_path: Optional[str] = None) -> NotionClient:
    """Load a NotionClient from config.yaml. Exits on failure."""
    path = config_path or _CONFIG_PATH
    if not os.path.isfile(path):
        print(f"Error: config file not found at {path}", file=sys.stderr)
        print(
            "Run  python scripts/notion_setup.py --api-key <key> --parent-page <id>  first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return NotionClient.load_config(path)


# ---------------------------------------------------------------------------
# Notion interaction helpers
# ---------------------------------------------------------------------------

def fetch_existing_session_ids(client: NotionClient, db_id: str) -> set:
    """
    Query the Conversations database for all pages where Source == 'claude_web'
    and return their Session ID values as a set for O(1) dedup lookups.
    """
    existing: set = set()

    filter_payload = {
        "property": "Source",
        "select": {"equals": SOURCE},
    }

    try:
        pages = client.query_database(db_id, filter=filter_payload)
    except Exception as exc:
        print(f"Warning: failed to query existing sessions: {exc}", file=sys.stderr)
        print("Proceeding without deduplication.", file=sys.stderr)
        return existing

    for page in pages:
        props = page.get("properties", {})
        session_prop = props.get("Session ID", {})
        # Session ID is Rich Text.
        rich_texts = session_prop.get("rich_text", [])
        if rich_texts:
            sid = rich_texts[0].get("plain_text", "")
            if sid:
                existing.add(sid)

    return existing


def _build_turn_blocks(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build Notion block children representing each turn as a toggle heading
    containing the user message, assistant response, and metadata.
    """
    blocks: List[Dict[str, Any]] = []

    for turn in turns:
        turn_id = turn["turn_id"]
        user_content = truncate(turn["user_message"]["content"])
        assistant_content = truncate(turn["assistant_response"]["content"])
        tool_uses = turn["assistant_response"].get("tool_uses") or []
        corrections = turn.get("corrections") or []
        attachment_count = turn["user_message"].get("attachment_count", 0)

        # Build inner children of the toggle.
        inner: List[Dict[str, Any]] = []

        # User message paragraph.
        user_prefix = "User: "
        if attachment_count > 0:
            user_prefix = f"User ({attachment_count} attachment(s)): "

        inner.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": user_prefix}, "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": user_content}},
                ],
            },
        })

        # Assistant response paragraph.
        if assistant_content:
            inner.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Assistant: "}, "annotations": {"bold": True}},
                        {"type": "text", "text": {"content": assistant_content}},
                    ],
                },
            })

        # Tool uses as a bulleted list.
        for tu in tool_uses:
            tool_label = tu.get("tool_name", "unknown")
            inner.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"Tool: {tool_label}"}},
                    ],
                },
            })

        # Corrections as a bulleted list item.
        if corrections:
            corr_text = ", ".join(
                f"{c['type']}({c['indicator']})" for c in corrections
            )
            inner.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"Corrections: {corr_text}"}},
                    ],
                },
            })

        # Toggle heading for the turn.
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"Turn {turn_id}"}},
                ],
                "children": inner,
            },
        })

    return blocks


def create_conversation_page(
    client: NotionClient,
    db_id: str,
    conv: Dict[str, Any],
) -> str:
    """
    Create a Notion page in the Conversations database for the given
    normalised conversation.  Returns the created page ID.
    """
    meta = conv["metadata"]

    # Build properties dict matching the Conversations DB schema.
    properties: Dict[str, Any] = {
        "Title": {
            "title": [{"type": "text", "text": {"content": truncate(conv["title"])}}],
        },
        "Session ID": {
            "rich_text": [{"type": "text", "text": {"content": conv["session_id"]}}],
        },
        "Source": {
            "select": {"name": SOURCE},
        },
        "Model": {
            "rich_text": [{"type": "text", "text": {"content": conv.get("model") or "claude"}}],
        },
        "Total Turns": {
            "number": meta["total_turns"],
        },
        "Total Tool Uses": {
            "number": meta["total_tool_uses"],
        },
        "Language": {
            "select": {"name": meta["primary_language"]},
        },
        "Domains": {
            "multi_select": [{"name": d} for d in meta["detected_domains"]],
        },
        "Processed": {
            "checkbox": False,
        },
    }

    # Created At (date property).
    if conv["created_at"]:
        properties["Created At"] = {
            "date": {"start": conv["created_at"]},
        }

    # Project Path and Git Branch are None for Claude.ai web but included
    # for schema completeness.
    if conv.get("project_path"):
        properties["Project Path"] = {
            "rich_text": [{"type": "text", "text": {"content": conv["project_path"]}}],
        }
    if conv.get("git_branch"):
        properties["Git Branch"] = {
            "rich_text": [{"type": "text", "text": {"content": conv["git_branch"]}}],
        }

    # Metadata-only: skip writing conversation body blocks to Notion.
    # Full conversation data lives in local JSON files.
    page = client.create_page(
        parent_id=db_id,
        properties=properties,
    )

    return page["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Import Claude.ai web conversations into Notion.",
        epilog=(
            "Example:\n"
            "  python scripts/ingest_claude_web.py ~/Downloads/claude-export.json\n"
            "  python scripts/ingest_claude_web.py export.json --since 2024-06-01\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "export_file",
        help="Path to the Claude.ai JSON export file.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Only import conversations created on or after this date.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a custom config.yaml (default: ../config.yaml relative to script).",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip Notion sync and only save to local JSON files.",
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


def load_conversations(path: str) -> List[Dict[str, Any]]:
    """Load and return the raw conversations list from the JSON file."""
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        # Some exports may wrap the array in an object with a key
        if isinstance(data, dict):
            # Try common wrapper keys
            for key in ("conversations", "data", "results", "chat_conversations"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        print(f"Error: expected a JSON array at top level in {path}.", file=sys.stderr)
        sys.exit(1)

    return data


def filter_by_date(
    conversations: List[Dict[str, Any]],
    since: Optional[str],
) -> List[Dict[str, Any]]:
    """Filter conversations to those created on or after *since* (YYYY-MM-DD)."""
    if since is None:
        return conversations

    try:
        cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(
            f"Error: invalid --since date format: {since!r}. Use YYYY-MM-DD.",
            file=sys.stderr,
        )
        sys.exit(1)

    filtered: List[Dict[str, Any]] = []
    for conv in conversations:
        created_str = conv.get("created_at")
        if created_str is None:
            # Include conversations without a timestamp (be conservative).
            filtered.append(conv)
            continue
        conv_dt = parse_timestamp_dt(created_str)
        if conv_dt is None:
            # Cannot parse -- include to be safe
            filtered.append(conv)
            continue
        if conv_dt >= cutoff:
            filtered.append(conv)

    return filtered


def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for the Claude.ai web importer."""
    args = parse_args(argv)
    local_only = args.local_only

    # 0. Load LLM API key if enrichment is enabled.
    _llm_api_key = None
    if args.use_llm_api:
        try:
            pass  # LLM API removed - use Skill mode
        except RuntimeError:
            print("WARN: No Anthropic API key found. Skipping LLM enrichment.", file=sys.stderr)
            args.use_llm_api = False

    # 1. Load config and initialise Notion client (unless local-only).
    client = None
    conversations_db_id = None
    if not local_only:
        try:
            client = load_client(config_path=args.config)
            conversations_db_id = client.databases["conversations"]
        except Exception as exc:
            print(f"Warning: Notion unavailable ({exc}). Falling back to local-only mode.")
            local_only = True

    # 2. Load conversations from JSON.
    raw_conversations = load_conversations(args.export_file)
    print(f"Loaded {len(raw_conversations)} conversation(s) from {args.export_file}")

    # 3. Apply --since date filter.
    raw_conversations = filter_by_date(raw_conversations, args.since)
    if args.since:
        print(f"After --since {args.since} filter: {len(raw_conversations)} conversation(s)")

    if not raw_conversations:
        print("Nothing to import.")
        return

    # 4. Fetch existing session IDs for deduplication.
    existing_ids: set = set()
    if not local_only and client is not None:
        print("Querying Notion for existing Claude.ai web sessions...")
        existing_ids = fetch_existing_session_ids(client, conversations_db_id)
        print(f"Found {len(existing_ids)} existing session(s) in Notion.")
    else:
        print("Local-only mode: skipping Notion deduplication.")

    # 5. Normalise and import.
    imported = 0
    skipped = 0
    errors = 0
    total = len(raw_conversations)

    for idx, raw in enumerate(raw_conversations, start=1):
        # Extract session ID -- prefer 'uuid', fall back to 'id'
        session_id = raw.get("uuid", raw.get("id", ""))
        title = raw.get("name", raw.get("title", "")) or "(untitled)"

        if not session_id:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR: conversation has no uuid or id field, skipping.",
                file=sys.stderr,
            )
            continue

        # Dedup check.
        if session_id in existing_ids:
            skipped += 1
            print(f"  [{idx}/{total}] SKIP (exists): {title}")
            continue

        # Normalise.
        try:
            conv = normalise_conversation(raw)
        except Exception as exc:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR normalising '{title}': {exc}",
                file=sys.stderr,
            )
            continue

        # Skip conversations that produced zero turns (e.g. empty or no messages).
        if conv["metadata"]["total_turns"] == 0:
            skipped += 1
            print(f"  [{idx}/{total}] SKIP (no turns): {title}")
            continue

        # LLM metadata enrichment.
        if args.use_llm_api:
            try:
                pass  # LLM enrichment removed
            except Exception as exc:
                print(f"  [{idx}/{total}] WARN LLM enrich failed: {exc}", file=sys.stderr)

        # Save to local JSON.
        _save_local(conv)

        # Create Notion page (unless local-only).
        if local_only:
            imported += 1
            print(
                f"  [{idx}/{total}] SAVED (local): {title}  "
                f"({conv['metadata']['total_turns']} turns)"
            )
        else:
            try:
                page_id = create_conversation_page(client, conversations_db_id, conv)
                imported += 1
                existing_ids.add(session_id)  # prevent re-import within same run
                print(
                    f"  [{idx}/{total}] IMPORTED: {title}  "
                    f"({conv['metadata']['total_turns']} turns, page={page_id})"
                )
            except Exception as exc:
                errors += 1
                print(
                    f"  [{idx}/{total}] ERROR importing '{title}': {exc}",
                    file=sys.stderr,
                )

    # 6. Summary.
    print()
    print("=" * 60)
    print(f"  Total conversations : {total}")
    print(f"  Imported (new)      : {imported}")
    print(f"  Skipped (existing)  : {skipped}")
    if errors:
        print(f"  Errors              : {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
