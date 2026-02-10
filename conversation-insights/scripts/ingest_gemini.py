#!/usr/bin/env python3
"""
Ingest Gemini conversations from a Google Takeout export directory into Notion.

Usage:
    python scripts/ingest_gemini.py <path-to-takeout-dir>
    python scripts/ingest_gemini.py <path-to-takeout-dir> --since 2024-06-01
    python scripts/ingest_gemini.py --help

The script:
    1. Recursively scans the Takeout directory for conversation JSON files
    2. Parses each conversation with flexible field detection (multiple
       field-name patterns are tried to handle Takeout format variations)
    3. Detects language and domains from user messages
    4. Deduplicates against existing Notion records (by session_id + source=gemini)
    5. Creates Notion pages with properties and toggle-block turn bodies

Google Takeout exports Gemini conversations as individual JSON files:

    Takeout/Gemini Apps/conversations/
    ├── 2024-01-15T10_30_00-conversation.json
    ├── 2024-02-20T14_00_00-conversation.json
    └── ...

Each file contains a single conversation object with messages.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

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
SOURCE = "gemini"
DEFAULT_MODEL = "gemini-pro"
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
DOMAIN_KEYWORDS: dict[str, list[str]] = {
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
CORRECTION_PATTERNS: list[dict[str, str]] = [
    {"type": "factual", "indicator": r"(?i)^no[,.\s]"},
    {"type": "factual", "indicator": r"^不是"},
    {"type": "factual", "indicator": r"^不对"},
    {"type": "factual", "indicator": r"(?i)\bwrong\b"},
    {"type": "style", "indicator": r"(?i)\bI meant\b"},
    {"type": "style", "indicator": r"我的意思是"},
    {"type": "style", "indicator": r"(?i)\binstead\b"},
    {"type": "scope", "indicator": r"(?i)\bonly\b"},
    {"type": "scope", "indicator": r"(?i)\bjust\b"},
    {"type": "scope", "indicator": r"只需要"},
    {"type": "scope", "indicator": r"不要"},
    {"type": "approach", "indicator": r"(?i)\bdon'?t use\b"},
    {"type": "approach", "indicator": r"别用"},
    {"type": "approach", "indicator": r"换个方式"},
]

# Alternate field names that Gemini Takeout exports may use.
# Each tuple is (preferred_name, *alternates).
_TITLE_KEYS = ("title", "name", "conversationTitle", "conversation_title")
_CREATE_TIME_KEYS = ("create_time", "createTime", "created", "createdTime",
                     "creation_timestamp", "startTime", "start_time")
_UPDATE_TIME_KEYS = ("update_time", "updateTime", "updated", "updatedTime",
                     "last_update_timestamp", "endTime", "end_time")
_MESSAGES_KEYS = ("messages", "turns", "entries", "conversation", "parts")
_ROLE_KEYS = ("role", "author", "sender", "participant")
_CONTENT_KEYS = ("content", "text", "body", "message", "response")
_MSG_TIME_KEYS = ("create_time", "createTime", "timestamp", "time", "created")
_MODEL_KEYS = ("model", "model_id", "modelId", "model_name", "modelName")


# ---------------------------------------------------------------------------
# Helpers -- flexible field access
# ---------------------------------------------------------------------------

def _get_first(obj: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    """Return the value for the first key found in *obj*, else *default*.

    This enables resilience against Takeout format variations where the
    same semantic field may appear under different JSON keys.
    """
    for key in keys:
        if key in obj:
            return obj[key]
    return default


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


def detect_domains(text: str) -> list[str]:
    """Return a sorted list of domain tags matched via keyword search."""
    lower = text.lower()
    matched: set[str] = set()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                matched.add(domain)
                break
    return sorted(matched) if matched else ["other"]


def detect_corrections(text: str) -> list[dict[str, str]]:
    """Detect user corrections via regex pattern matching."""
    found: list[dict[str, str]] = []
    for pattern in CORRECTION_PATTERNS:
        if re.search(pattern["indicator"], text):
            found.append({"type": pattern["type"], "indicator": pattern["indicator"]})
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

def _parse_timestamp(value: Any) -> Optional[str]:
    """Parse a timestamp from various formats into ISO-8601 string.

    Handles:
      - Unix timestamps (int or float, in seconds)
      - Unix timestamps in milliseconds (>1e12)
      - ISO-8601 datetime strings
      - ``None`` / missing values

    Returns an ISO-8601 string or ``None``.
    """
    if value is None:
        return None

    # Numeric timestamps (Unix epoch).
    if isinstance(value, (int, float)):
        # Millisecond timestamps are > 1e12; convert to seconds.
        if value > 1e12:
            value = value / 1000.0
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None

    # String timestamps -- try ISO-8601 parsing.
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None

        # Try common ISO formats.
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(cleaned, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

        # As a last resort try numeric interpretation of the string.
        try:
            numeric = float(cleaned)
            return _parse_timestamp(numeric)
        except ValueError:
            pass

    return None


def _generate_session_id(title: str, created_at: Optional[str], filepath: str) -> str:
    """Generate a deterministic session ID for a Gemini conversation.

    Uses a hash of the title, creation date, and source file path so that
    re-running the importer on the same export folder produces stable IDs.
    """
    components = f"{title}|{created_at or ''}|{os.path.basename(filepath)}"
    return hashlib.sha256(components.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

def _normalise_role(raw_role: Any) -> Optional[str]:
    """Map a raw role string to a canonical role.

    Returns ``"user"``, ``"model"``, or ``None`` for unrecognised roles.
    System / tool roles are intentionally skipped since Gemini exports
    do not reliably expose them.
    """
    if not isinstance(raw_role, str):
        return None

    lower = raw_role.lower().strip()

    if lower in ("user", "human"):
        return "user"
    if lower in ("model", "assistant", "ai", "gemini", "bot"):
        return "model"

    # Skip system, tool, or other roles.
    return None


def _extract_content(msg: dict[str, Any]) -> str:
    """Extract text content from a message object.

    Handles both flat string content and nested structures (e.g. a list of
    parts or a dict with a ``text`` sub-field).
    """
    raw = _get_first(msg, _CONTENT_KEYS)

    if raw is None:
        return ""

    # Simple string content.
    if isinstance(raw, str):
        return raw.strip()

    # List of parts (some formats use [{text: "..."}, ...]).
    if isinstance(raw, list):
        text_parts: list[str] = []
        for part in raw:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                # Try common sub-field names.
                for sub_key in ("text", "content", "body", "value"):
                    if sub_key in part and isinstance(part[sub_key], str):
                        text_parts.append(part[sub_key])
                        break
        return "\n".join(text_parts).strip()

    # Dict with a text sub-field.
    if isinstance(raw, dict):
        for sub_key in ("text", "content", "body", "value", "parts"):
            if sub_key in raw:
                # Recurse one level.
                inner = raw[sub_key]
                if isinstance(inner, str):
                    return inner.strip()
                if isinstance(inner, list):
                    return "\n".join(
                        p if isinstance(p, str) else str(p) for p in inner
                    ).strip()

    return str(raw).strip()


def _extract_messages(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the message list from a conversation object.

    Tries multiple common field names and validates that the result is a
    list of dicts.  Returns an empty list on failure with a warning.
    """
    raw_messages = _get_first(data, _MESSAGES_KEYS)

    if raw_messages is None:
        # Some formats nest messages one level deeper.
        for nested_key in ("data", "payload", "result"):
            if nested_key in data and isinstance(data[nested_key], dict):
                raw_messages = _get_first(data[nested_key], _MESSAGES_KEYS)
                if raw_messages is not None:
                    break

    if raw_messages is None:
        print("  Warning: no messages array found in conversation.", file=sys.stderr)
        return []

    if not isinstance(raw_messages, list):
        print(
            f"  Warning: messages field is {type(raw_messages).__name__}, "
            f"expected list.",
            file=sys.stderr,
        )
        return []

    return [m for m in raw_messages if isinstance(m, dict)]


# ---------------------------------------------------------------------------
# Conversation parsing
# ---------------------------------------------------------------------------

def parse_conversation(data: dict[str, Any], filepath: str) -> list[dict[str, Any]]:
    """Parse a Gemini conversation into a list of turn dicts.

    Each turn pairs a user message with the subsequent model response,
    following the same unified schema structure as the ChatGPT importer.

    Parameters
    ----------
    data : dict
        The parsed JSON content of a single conversation file.
    filepath : str
        Path to the source file (used for diagnostics).

    Returns
    -------
    list[dict]
        Ordered list of turn dicts.
    """
    raw_messages = _extract_messages(data)

    if not raw_messages:
        return []

    # Build a list of (role, text, timestamp) tuples, skipping empty/system.
    ordered: list[dict[str, Any]] = []
    for msg in raw_messages:
        role_raw = _get_first(msg, _ROLE_KEYS)
        role = _normalise_role(role_raw)
        if role is None:
            continue

        text = _extract_content(msg)
        if not text:
            continue

        msg_time = _get_first(msg, _MSG_TIME_KEYS)

        ordered.append({
            "role": role,
            "text": text,
            "timestamp": msg_time,
        })

    # Pair user/model messages into turns.
    turns: list[dict[str, Any]] = []
    turn_id = 0
    i = 0

    while i < len(ordered):
        msg = ordered[i]

        if msg["role"] == "user":
            user_text = msg["text"]
            model_text = ""
            model_time: Any = None

            # Consume subsequent model messages (Gemini may split responses).
            j = i + 1
            model_parts: list[str] = []
            while j < len(ordered) and ordered[j]["role"] == "model":
                model_parts.append(ordered[j]["text"])
                model_time = ordered[j]["timestamp"]
                j += 1

            if model_parts:
                model_text = "\n\n".join(model_parts)

            turn_id += 1
            turns.append({
                "turn_id": turn_id,
                "timestamp": _parse_timestamp(msg["timestamp"]),
                "user_message": {
                    "content": user_text,
                    "word_count": _word_count(user_text),
                    "language": detect_language(user_text),
                    "has_code": _has_code(user_text),
                    "has_file_reference": _has_file_reference(user_text),
                },
                "assistant_response": {
                    "content": model_text,
                    "word_count": _word_count(model_text),
                    "tool_uses": [],
                    "has_thinking": False,
                },
                "corrections": detect_corrections(user_text),
            })

            i = j
        else:
            # Orphan model message before first user message -- skip.
            i += 1

    return turns


def normalise_conversation(
    data: dict[str, Any],
    filepath: str,
) -> dict[str, Any]:
    """
    Convert a single raw Gemini conversation dict into the unified schema
    format described in ``references/unified-schema.md``.

    Parameters
    ----------
    data : dict
        Parsed JSON content of a conversation file.
    filepath : str
        Source file path (used for session ID generation and diagnostics).

    Returns
    -------
    dict
        Normalised conversation in unified schema format.
    """
    turns = parse_conversation(data, filepath)

    # Extract title with fallback.
    title = _get_first(data, _TITLE_KEYS) or "(untitled)"
    if not isinstance(title, str):
        title = str(title)
    title = title.strip() or "(untitled)"

    # Extract timestamps.
    created_at = _parse_timestamp(_get_first(data, _CREATE_TIME_KEYS))

    # If no top-level create_time, try the first message timestamp.
    if created_at is None and turns:
        created_at = turns[0].get("timestamp")

    # Extract model name.
    model = _get_first(data, _MODEL_KEYS)
    if model is not None and not isinstance(model, str):
        model = str(model)
    if not model:
        model = DEFAULT_MODEL

    # Generate a stable session ID.
    session_id = _generate_session_id(title, created_at, filepath)

    # Aggregate user message text for language and domain detection.
    all_user_text = " ".join(t["user_message"]["content"] for t in turns)

    primary_language = detect_language(all_user_text)
    detected_domains = detect_domains(all_user_text)

    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "source": SOURCE,
        "model": model,
        "project_path": None,
        "title": title,
        "created_at": created_at,
        "git_branch": None,
        "turns": turns,
        "metadata": {
            "total_turns": len(turns),
            "total_tool_uses": 0,
            "primary_language": primary_language,
            "detected_domains": detected_domains,
            "has_sidechains": False,
            "has_file_changes": False,
            "token_count": None,
        },
    }


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_conversation_files(takeout_dir: str) -> list[str]:
    """Recursively scan *takeout_dir* for JSON files that look like conversations.

    Files are returned sorted by name for deterministic ordering.

    Parameters
    ----------
    takeout_dir : str
        Root directory of the Google Takeout export.

    Returns
    -------
    list[str]
        Absolute paths to candidate conversation JSON files.
    """
    candidates: list[str] = []

    for dirpath, _dirnames, filenames in os.walk(takeout_dir):
        for fname in filenames:
            if not fname.lower().endswith(".json"):
                continue
            full_path = os.path.join(dirpath, fname)
            candidates.append(full_path)

    candidates.sort()
    return candidates


def _is_conversation_file(data: Any) -> bool:
    """Heuristic check: does *data* look like a Gemini conversation?

    Returns True if the parsed JSON is a dict containing either a messages
    array or recognisable conversation-level fields.
    """
    if not isinstance(data, dict):
        return False

    # Has a messages-like array.
    if _get_first(data, _MESSAGES_KEYS) is not None:
        return True

    # Has both a title and a timestamp -- likely a conversation.
    has_title = _get_first(data, _TITLE_KEYS) is not None
    has_time = _get_first(data, _CREATE_TIME_KEYS) is not None
    if has_title and has_time:
        return True

    return False


def load_conversation_file(filepath: str) -> Optional[dict[str, Any]]:
    """Load and validate a single conversation JSON file.

    Returns the parsed dict if the file looks like a conversation, or
    ``None`` if parsing fails or the content does not match expected
    structure.  Warnings are printed for skipped files.

    Parameters
    ----------
    filepath : str
        Absolute path to the JSON file.

    Returns
    -------
    dict or None
        Parsed conversation data, or None.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(
            f"  Warning: skipping {os.path.basename(filepath)} "
            f"(invalid JSON: {exc})",
            file=sys.stderr,
        )
        return None
    except OSError as exc:
        print(
            f"  Warning: skipping {os.path.basename(filepath)} "
            f"(read error: {exc})",
            file=sys.stderr,
        )
        return None

    if not _is_conversation_file(data):
        # Silently skip non-conversation JSON files (e.g. metadata, settings).
        return None

    return data


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))


def load_client(config_path: Optional[str] = None) -> NotionClient:
    """Load a NotionClient from config.yaml. Exits on failure.

    Parameters
    ----------
    config_path : str, optional
        Override path to the YAML config file.  Falls back to the
        default ``config.yaml`` location relative to this script.
    """
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

def fetch_existing_session_ids(client: NotionClient, db_id: str) -> set[str]:
    """
    Query the Conversations database for all pages where Source == 'gemini'
    and return their Session ID values as a set for O(1) dedup lookups.
    """
    existing: set[str] = set()

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


def _build_turn_blocks(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build Notion block children representing each turn as a toggle heading
    containing the user message, assistant response, and tool uses.
    """
    blocks: list[dict[str, Any]] = []

    for turn in turns:
        turn_id = turn["turn_id"]
        user_content = truncate(turn["user_message"]["content"])
        assistant_content = truncate(turn["assistant_response"]["content"])
        tool_uses = turn["assistant_response"].get("tool_uses") or []

        # Build inner children of the toggle.
        inner: list[dict[str, Any]] = []

        # User message paragraph.
        inner.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "User: "}, "annotations": {"bold": True}},
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
    conv: dict[str, Any],
) -> str:
    """
    Create a Notion page in the Conversations database for the given
    normalised conversation.  Returns the created page ID.
    """
    meta = conv["metadata"]

    # Build properties dict matching the Conversations DB schema.
    properties: dict[str, Any] = {
        "Title": {
            "title": [{"type": "text", "text": {"content": conv["title"]}}],
        },
        "Session ID": {
            "rich_text": [{"type": "text", "text": {"content": conv["session_id"]}}],
        },
        "Source": {
            "select": {"name": SOURCE},
        },
        "Model": {
            "rich_text": [{"type": "text", "text": {"content": conv["model"] or ""}}],
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

    # Project Path and Git Branch are None for Gemini but included for
    # schema completeness.
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
# Date filtering
# ---------------------------------------------------------------------------

def filter_by_date(
    conversations: list[tuple[str, dict[str, Any]]],
    since: Optional[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Filter conversations to those created on or after *since* (YYYY-MM-DD).

    Parameters
    ----------
    conversations : list[tuple[str, dict]]
        List of (filepath, parsed_data) tuples.
    since : str or None
        ISO date string cutoff.  If None, all conversations are returned.

    Returns
    -------
    list[tuple[str, dict]]
        Filtered list of (filepath, parsed_data) tuples.
    """
    if since is None:
        return conversations

    try:
        cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: invalid --since date format: {since!r}. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    filtered: list[tuple[str, dict[str, Any]]] = []
    for filepath, data in conversations:
        raw_time = _get_first(data, _CREATE_TIME_KEYS)
        iso_time = _parse_timestamp(raw_time)

        if iso_time is None:
            # Include conversations without a timestamp (be conservative).
            filtered.append((filepath, data))
            continue

        try:
            conv_dt = datetime.fromisoformat(iso_time)
            if conv_dt.tzinfo is None:
                conv_dt = conv_dt.replace(tzinfo=timezone.utc)
            if conv_dt >= cutoff:
                filtered.append((filepath, data))
        except ValueError:
            # Cannot parse -- include to be safe.
            filtered.append((filepath, data))

    return filtered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Import Gemini conversations from a Google Takeout export into Notion.",
    )
    parser.add_argument(
        "takeout_dir",
        help=(
            "Path to the Google Takeout export directory containing Gemini "
            "conversation JSON files (e.g. 'Takeout/Gemini Apps/conversations/')."
        ),
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only import conversations created on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a custom config.yaml file (default: ../config.yaml relative to script).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse and validate files without writing to Notion.",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 0. Load LLM API key if enrichment is enabled.
    _llm_api_key = None
    if args.use_llm_api:
        try:
            pass  # LLM API removed - use Skill mode
        except RuntimeError:
            print("WARN: No Anthropic API key found. Skipping LLM enrichment.", file=sys.stderr)
            args.use_llm_api = False

    # 1. Validate takeout directory.
    takeout_dir = os.path.abspath(args.takeout_dir)
    if not os.path.isdir(takeout_dir):
        print(f"Error: directory not found: {takeout_dir}", file=sys.stderr)
        sys.exit(1)

    # 2. Discover JSON files.
    print(f"Scanning {takeout_dir} for conversation files...")
    json_files = discover_conversation_files(takeout_dir)
    print(f"Found {len(json_files)} JSON file(s).")

    if not json_files:
        print("No JSON files found. Nothing to import.")
        return

    # 3. Load and validate conversation files.
    print("Parsing conversation files...")
    conversations: list[tuple[str, dict[str, Any]]] = []
    skipped_files = 0

    for filepath in json_files:
        data = load_conversation_file(filepath)
        if data is not None:
            conversations.append((filepath, data))
        else:
            skipped_files += 1

    print(
        f"Parsed {len(conversations)} conversation(s) "
        f"({skipped_files} non-conversation file(s) skipped)."
    )

    if not conversations:
        print("No valid conversations found. Nothing to import.")
        return

    # 4. Apply --since date filter.
    conversations = filter_by_date(conversations, args.since)
    if args.since:
        print(f"After --since {args.since} filter: {len(conversations)} conversation(s)")

    if not conversations:
        print("Nothing to import after date filtering.")
        return

    # 5. Dry-run mode: summarise and exit.
    if args.dry_run:
        print()
        print("=== DRY RUN ===")
        for filepath, data in conversations:
            title = _get_first(data, _TITLE_KEYS) or "(untitled)"
            raw_time = _get_first(data, _CREATE_TIME_KEYS)
            iso_time = _parse_timestamp(raw_time) or "unknown date"
            msgs = _extract_messages(data)
            print(f"  {os.path.basename(filepath)}: {title!r} ({iso_time}, {len(msgs)} messages)")
        print(f"\nTotal: {len(conversations)} conversation(s) would be imported.")
        return

    # 6. Load config and initialise Notion client.
    client = load_client(args.config)
    conversations_db_id: str = client.databases["conversations"]

    # 7. Fetch existing session IDs for deduplication.
    print("Querying Notion for existing Gemini sessions...")
    existing_ids = fetch_existing_session_ids(client, conversations_db_id)
    print(f"Found {len(existing_ids)} existing session(s) in Notion.")

    # 8. Normalise and import.
    imported = 0
    skipped = 0
    errors = 0
    total = len(conversations)

    for idx, (filepath, data) in enumerate(conversations, start=1):
        title = _get_first(data, _TITLE_KEYS) or "(untitled)"
        basename = os.path.basename(filepath)

        # Normalise.
        try:
            conv = normalise_conversation(data, filepath)
        except Exception as exc:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR normalising '{title}' ({basename}): {exc}",
                file=sys.stderr,
            )
            continue

        session_id = conv["session_id"]

        # Dedup check.
        if session_id in existing_ids:
            skipped += 1
            print(f"  [{idx}/{total}] SKIP (exists): {title}")
            continue

        # Skip conversations that produced zero turns.
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

        # Create Notion page.
        try:
            page_id = create_conversation_page(client, conversations_db_id, conv)
            imported += 1
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

    # 9. Summary.
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
