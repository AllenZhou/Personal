#!/usr/bin/env python3
"""
Ingest OpenAI Codex conversation logs from ~/.codex/sessions/ into Notion.

Usage:
    python scripts/ingest_codex.py [--since YYYY-MM-DD]

The script:
    1. Walks ~/.codex/sessions/ recursively to find all JSONL rollout files
    2. Parses session_meta, event_msg, response_item, and turn_context records
    3. Pairs user_message -> agent_message events into conversation turns
    4. Extracts agent_reasoning as "thinking", tracks token_count and turn_aborted
    5. Deduplicates against existing Notion records (by session_id + source=codex)
    6. Creates Notion pages with properties and toggle-block turn bodies

Directory structure:
    ~/.codex/sessions/YYYY/MM/DD/rollout-{ISO-timestamp}-{session-uuid}.jsonl
"""

import argparse
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
SOURCE = "codex"
DEFAULT_MODEL = "gpt-5.2-codex"
CODEX_SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
MAX_TITLE_LENGTH = 100
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


# Domain keyword mapping -- shared with ingest_chatgpt.py.
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


# ---------------------------------------------------------------------------
# Helpers -- language, domain, and correction detection
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
# JSONL discovery and parsing
# ---------------------------------------------------------------------------

def discover_session_files(
    sessions_dir: str,
    since: Optional[datetime] = None,
) -> list[str]:
    """Walk the sessions directory and return sorted paths to JSONL rollout files.

    The directory structure is ``YYYY/MM/DD/rollout-*.jsonl``.  When *since*
    is provided, only directories on or after that date are traversed.

    Parameters
    ----------
    sessions_dir : str
        Root sessions directory (typically ``~/.codex/sessions``).
    since : datetime, optional
        Only include sessions from this date onward.

    Returns
    -------
    list[str]
        Absolute paths to JSONL files, sorted lexicographically (oldest first).
    """
    if not os.path.isdir(sessions_dir):
        return []

    files: list[str] = []

    for root, _dirs, filenames in os.walk(sessions_dir):
        for fname in filenames:
            if not fname.endswith(".jsonl"):
                continue
            if not fname.startswith("rollout-"):
                continue

            full_path = os.path.join(root, fname)

            # Apply date filter based on directory structure YYYY/MM/DD.
            if since is not None:
                try:
                    rel = os.path.relpath(root, sessions_dir)
                    parts = rel.split(os.sep)
                    if len(parts) >= 3:
                        dir_date = datetime(
                            int(parts[0]), int(parts[1]), int(parts[2]),
                            tzinfo=timezone.utc,
                        )
                        if dir_date.date() < since.date():
                            continue
                except (ValueError, IndexError):
                    # If directory structure does not match, include the file
                    # to be safe.
                    pass

            files.append(full_path)

    files.sort()
    return files


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts/lists. Returns *default* on any miss."""
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current


def parse_jsonl_file(path: str) -> dict[str, Any]:
    """Parse a Codex rollout JSONL file into a structured session dict.

    Returns a dict with keys:
        session_id, timestamp, cwd, model, git_branch, git_repo,
        originator, summary, events, token_count, had_abort
    where ``events`` is a list of parsed event records.

    Parameters
    ----------
    path : str
        Absolute path to the JSONL file.

    Returns
    -------
    dict
        Parsed session data.

    Raises
    ------
    ValueError
        If the file contains no valid session_meta record and the session
        ID cannot be extracted from the filename.
    """
    session_id: Optional[str] = None
    timestamp: Optional[str] = None
    cwd: Optional[str] = None
    model: Optional[str] = None
    git_branch: Optional[str] = None
    git_repo: Optional[str] = None
    originator: Optional[str] = None
    summary: Optional[str] = None

    events: list[dict[str, Any]] = []
    total_tokens: int = 0
    had_abort: bool = False

    with open(path, "r", encoding="utf-8") as fh:
        for line_num, raw_line in enumerate(fh, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                # Skip malformed lines silently.
                continue

            record_type = record.get("type", "")
            payload = record.get("payload") or {}

            if record_type == "session_meta":
                session_id = payload.get("id") or session_id
                timestamp = payload.get("timestamp") or timestamp
                cwd = payload.get("cwd") or cwd
                originator = payload.get("originator") or originator
                model = model or payload.get("model")
                git_branch = _safe_get(payload, "git", "branch") or git_branch
                git_repo = _safe_get(payload, "git", "repository_url") or git_repo

            elif record_type == "event_msg":
                event_subtype = payload.get("type", "")

                if event_subtype == "user_message":
                    message_text = payload.get("message", "")
                    events.append({
                        "kind": "user_message",
                        "text": message_text,
                        "has_images": bool(
                            payload.get("images") or payload.get("local_images")
                        ),
                    })

                elif event_subtype == "agent_message":
                    message_text = payload.get("message", "")
                    events.append({
                        "kind": "agent_message",
                        "text": message_text,
                    })

                elif event_subtype == "agent_reasoning":
                    reasoning_text = payload.get("message", "") or payload.get("text", "")
                    events.append({
                        "kind": "agent_reasoning",
                        "text": reasoning_text,
                    })

                elif event_subtype == "token_count":
                    # Accumulate token usage.  Payload may contain
                    # total_tokens directly, or input_tokens + output_tokens.
                    direct_total = payload.get("total_tokens", 0)
                    if direct_total:
                        total_tokens += direct_total
                    else:
                        total_tokens += (
                            payload.get("input_tokens", 0)
                            + payload.get("output_tokens", 0)
                        )

                elif event_subtype == "turn_aborted":
                    had_abort = True
                    events.append({"kind": "turn_aborted"})

            elif record_type == "turn_context":
                # Extract model and summary from turn-level metadata.
                turn_model = payload.get("model")
                if turn_model:
                    model = turn_model
                turn_summary = payload.get("summary")
                if turn_summary:
                    summary = turn_summary

            elif record_type == "response_item":
                # response_item records duplicate content from event_msg
                # in raw API format.  We use them only as a fallback when
                # no event_msg user/agent records are found.
                events.append({
                    "kind": "response_item",
                    "role": payload.get("role", ""),
                    "content": payload.get("content") or [],
                })

    if session_id is None:
        # Try to extract session ID from the filename as a fallback.
        # Filename format: rollout-{ISO-timestamp}-{uuid}.jsonl
        basename = os.path.basename(path)
        match = re.search(
            r"rollout-\d{4}-\d{2}-\d{2}T[\d:.Z+-]+-([0-9a-f-]{36})\.jsonl$",
            basename,
        )
        if match:
            session_id = match.group(1)
        else:
            raise ValueError(f"No session_meta found and cannot parse ID from: {path}")

    return {
        "session_id": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "model": model or DEFAULT_MODEL,
        "git_branch": git_branch,
        "git_repo": git_repo,
        "originator": originator,
        "summary": summary,
        "events": events,
        "token_count": total_tokens if total_tokens > 0 else None,
        "had_abort": had_abort,
        "source_file": path,
    }


# ---------------------------------------------------------------------------
# Turn pairing -- convert flat event list into conversation turns
# ---------------------------------------------------------------------------

def _extract_response_item_text(content_list: list[dict[str, Any]]) -> str:
    """Extract plain text from a response_item content array.

    Content entries have ``type`` of ``input_text`` or ``output_text`` with a
    ``text`` field.
    """
    parts: list[str] = []
    for item in content_list:
        text = item.get("text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)


def build_turns(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a parsed session's event list into unified-schema turns.

    Turn pairing logic:
        - Walk events in order
        - Each ``user_message`` starts a new turn
        - Subsequent ``agent_reasoning`` events are collected as thinking
        - Subsequent ``agent_message`` events form the assistant response
        - ``turn_aborted`` marks the turn as aborted
        - If no event_msg user/agent messages were found, fall back to
          response_item records

    Parameters
    ----------
    session : dict
        Output of :func:`parse_jsonl_file`.

    Returns
    -------
    list[dict]
        Turns in the unified schema format.
    """
    events = session.get("events", [])

    # Check whether we have proper event_msg records or need to fall back
    # to response_item records.
    has_event_msgs = any(
        e["kind"] in ("user_message", "agent_message") for e in events
    )

    if has_event_msgs:
        return _build_turns_from_events(events)
    else:
        return _build_turns_from_response_items(events)


def _build_turns_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair user_message and agent_message events into turns."""
    turns: list[dict[str, Any]] = []
    turn_id = 0
    i = 0

    while i < len(events):
        event = events[i]

        if event["kind"] == "user_message":
            user_text = event["text"]
            assistant_text = ""
            reasoning_text = ""
            has_thinking = False
            was_aborted = False

            # Consume subsequent agent_reasoning, agent_message, and
            # turn_aborted events that belong to this turn.
            j = i + 1
            while j < len(events):
                next_ev = events[j]
                if next_ev["kind"] == "user_message":
                    # Next user turn starts -- stop here.
                    break
                elif next_ev["kind"] == "agent_reasoning":
                    has_thinking = True
                    reasoning_text += (
                        ("\n" if reasoning_text else "") + next_ev.get("text", "")
                    )
                elif next_ev["kind"] == "agent_message":
                    # Take the last (or only) agent message as the response.
                    assistant_text = next_ev.get("text", "")
                elif next_ev["kind"] == "turn_aborted":
                    was_aborted = True
                # Skip response_item when event_msg records are present.
                j += 1

            turn_id += 1
            turns.append({
                "turn_id": turn_id,
                "timestamp": None,
                "user_message": {
                    "content": user_text,
                    "word_count": _word_count(user_text),
                    "language": detect_language(user_text),
                    "has_code": _has_code(user_text),
                    "has_file_reference": _has_file_reference(user_text),
                },
                "assistant_response": {
                    "content": assistant_text,
                    "word_count": _word_count(assistant_text),
                    "tool_uses": [],
                    "has_thinking": has_thinking,
                },
                "corrections": detect_corrections(user_text),
                "_reasoning": reasoning_text,
                "_aborted": was_aborted,
            })

            i = j
        else:
            # Skip events that appear before the first user message
            # (e.g. orphan agent_reasoning or response_item records).
            i += 1

    return turns


def _build_turns_from_response_items(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fallback: build turns from response_item records when no event_msg data."""
    turns: list[dict[str, Any]] = []
    turn_id = 0
    i = 0

    # Collect only response_item events.
    ri_events = [e for e in events if e["kind"] == "response_item"]

    while i < len(ri_events):
        event = ri_events[i]

        if event.get("role") == "user":
            user_text = _extract_response_item_text(event.get("content", []))
            assistant_text = ""

            j = i + 1
            while j < len(ri_events):
                next_ev = ri_events[j]
                if next_ev.get("role") == "user":
                    break
                if next_ev.get("role") == "assistant":
                    assistant_text = _extract_response_item_text(
                        next_ev.get("content", [])
                    )
                j += 1

            if user_text:
                turn_id += 1
                turns.append({
                    "turn_id": turn_id,
                    "timestamp": None,
                    "user_message": {
                        "content": user_text,
                        "word_count": _word_count(user_text),
                        "language": detect_language(user_text),
                        "has_code": _has_code(user_text),
                        "has_file_reference": _has_file_reference(user_text),
                    },
                    "assistant_response": {
                        "content": assistant_text,
                        "word_count": _word_count(assistant_text),
                        "tool_uses": [],
                        "has_thinking": False,
                    },
                    "corrections": detect_corrections(user_text),
                    "_reasoning": "",
                    "_aborted": False,
                })

            i = j
        else:
            i += 1

    return turns


# ---------------------------------------------------------------------------
# Session normalisation -- build the unified schema dict
# ---------------------------------------------------------------------------

def normalise_session(session: dict[str, Any]) -> dict[str, Any]:
    """Convert a parsed Codex session into the unified schema format.

    Parameters
    ----------
    session : dict
        Output of :func:`parse_jsonl_file`.

    Returns
    -------
    dict
        Normalised conversation in the unified schema format described
        in ``references/unified-schema.md``.
    """
    turns = build_turns(session)

    # Derive title from the first user message, truncated, or from the
    # turn_context summary if available.
    title = "(untitled)"
    if session.get("summary"):
        title = session["summary"][:MAX_TITLE_LENGTH]
    elif turns:
        first_user_msg = turns[0]["user_message"]["content"]
        if first_user_msg:
            title = first_user_msg[:MAX_TITLE_LENGTH]

    # Aggregate user text for language and domain detection.
    all_user_text = " ".join(
        t["user_message"]["content"] for t in turns if t["user_message"]["content"]
    )

    primary_language = detect_language(all_user_text)
    detected_domains = detect_domains(all_user_text)
    total_tool_uses = sum(
        len(t["assistant_response"]["tool_uses"]) for t in turns
    )

    # Clean up internal keys from turns before returning.
    clean_turns: list[dict[str, Any]] = []
    for t in turns:
        clean_turn = {
            "turn_id": t["turn_id"],
            "timestamp": t["timestamp"],
            "user_message": t["user_message"],
            "assistant_response": t["assistant_response"],
            "corrections": t["corrections"],
        }
        clean_turns.append(clean_turn)

    return {
        "schema_version": "1.1",
        "session_id": session["session_id"],
        "source": SOURCE,
        "model": session["model"],
        "project_path": session.get("cwd"),
        "title": title,
        "created_at": session.get("timestamp"),
        "git_branch": session.get("git_branch"),
        "turns": clean_turns,
        "metadata": {
            "total_turns": len(clean_turns),
            "total_tool_uses": total_tool_uses,
            "primary_language": primary_language,
            "detected_domains": detected_domains,
            "has_sidechains": False,
            "has_file_changes": False,
            "token_count": session.get("token_count"),
            "file_changes": None,  # Codex doesn't track file changes
        },
        # Keep internal data for richer Notion page body.
        "_raw_turns": turns,
        "_had_abort": session.get("had_abort", False),
        "_originator": session.get("originator"),
    }


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))


def load_client() -> NotionClient:
    """Load a NotionClient from config.yaml.  Exits on failure."""
    if not os.path.isfile(_CONFIG_PATH):
        print(f"Error: config file not found at {_CONFIG_PATH}", file=sys.stderr)
        print(
            "Run  python scripts/notion_setup.py --api-key <key> --parent-page <id>  first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return NotionClient.load_config(_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Notion interaction helpers
# ---------------------------------------------------------------------------

def fetch_existing_session_ids(client: NotionClient, db_id: str) -> set[str]:
    """Query the Conversations database for all pages where Source == 'codex'
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
        rich_texts = session_prop.get("rich_text", [])
        if rich_texts:
            sid = rich_texts[0].get("plain_text", "")
            if sid:
                existing.add(sid)

    return existing


def _build_turn_blocks(
    conv: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build Notion block children representing each turn as a toggle heading.

    Each toggle contains the user message, optional thinking/reasoning,
    and the assistant response.  Aborted turns are marked in the toggle title.

    Parameters
    ----------
    conv : dict
        Normalised conversation dict (with ``_raw_turns`` for internal data).

    Returns
    -------
    list[dict]
        Notion block objects ready for page creation.
    """
    blocks: list[dict[str, Any]] = []
    raw_turns = conv.get("_raw_turns", conv.get("turns", []))

    for turn in raw_turns:
        turn_id = turn["turn_id"]
        user_content = truncate(turn["user_message"]["content"])
        assistant_content = truncate(
            turn.get("assistant_response", {}).get("content", "")
        )
        reasoning = turn.get("_reasoning", "")
        was_aborted = turn.get("_aborted", False)

        # Build toggle title.
        toggle_title = f"Turn {turn_id}"
        if was_aborted:
            toggle_title += " [ABORTED]"

        # Build inner children of the toggle.
        inner: list[dict[str, Any]] = []

        # User message paragraph.
        inner.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": "User: "},
                        "annotations": {"bold": True},
                    },
                    {
                        "type": "text",
                        "text": {"content": user_content},
                    },
                ],
            },
        })

        # Thinking/reasoning block (if present).
        if reasoning:
            inner.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": "Thinking: "},
                            "annotations": {"bold": True, "italic": True},
                        },
                        {
                            "type": "text",
                            "text": {"content": truncate(reasoning)},
                            "annotations": {"italic": True},
                        },
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
                        {
                            "type": "text",
                            "text": {"content": "Assistant: "},
                            "annotations": {"bold": True},
                        },
                        {
                            "type": "text",
                            "text": {"content": assistant_content},
                        },
                    ],
                },
            })

        # Toggle block for the turn.
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {"type": "text", "text": {"content": toggle_title}},
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
    """Create a Notion page in the Conversations database for the given
    normalised Codex conversation.  Returns the created page ID.

    Parameters
    ----------
    client : NotionClient
        Initialised Notion API client.
    db_id : str
        Conversations database ID.
    conv : dict
        Normalised conversation dict.

    Returns
    -------
    str
        The ID of the created Notion page.
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
    if conv.get("created_at"):
        properties["Created At"] = {
            "date": {"start": conv["created_at"]},
        }

    # Project Path.
    if conv.get("project_path"):
        properties["Project Path"] = {
            "rich_text": [
                {"type": "text", "text": {"content": conv["project_path"]}}
            ],
        }

    # Git Branch.
    if conv.get("git_branch"):
        properties["Git Branch"] = {
            "rich_text": [
                {"type": "text", "text": {"content": conv["git_branch"]}}
            ],
        }

    # Metadata-only: skip writing conversation body blocks to Notion.
    # Full conversation data lives in local JSON files.
    page = client.create_page(
        parent_id=db_id,
        properties=properties,
    )

    return page.get("id", "")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Import OpenAI Codex session logs into Notion.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only import sessions created on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--sessions-dir",
        type=str,
        default=CODEX_SESSIONS_DIR,
        help=(
            f"Path to the Codex sessions directory. "
            f"Default: {CODEX_SESSIONS_DIR}"
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
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # 1. Load config and initialise Notion client.
    client = load_client()
    conversations_db_id: str = client.databases["conversations"]

    # 2. Parse --since date filter.
    since_dt: Optional[datetime] = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            print(
                f"Error: invalid --since date format: {args.since!r}. Use YYYY-MM-DD.",
                file=sys.stderr,
            )
            sys.exit(1)

    # 3. Discover session files.
    sessions_dir = os.path.expanduser(args.sessions_dir)
    print(f"Scanning Codex sessions in: {sessions_dir}")

    session_files = discover_session_files(sessions_dir, since=since_dt)

    if not session_files:
        print("No Codex session files found.")
        if not os.path.isdir(sessions_dir):
            print(f"  Directory does not exist: {sessions_dir}", file=sys.stderr)
        elif args.since:
            print(f"  No sessions found on or after {args.since}.")
        return

    print(f"Found {len(session_files)} session file(s).")
    if args.since:
        print(f"  (filtered to sessions on or after {args.since})")

    # 4. Fetch existing session IDs for deduplication.
    print("Querying Notion for existing Codex sessions...")
    existing_ids = fetch_existing_session_ids(client, conversations_db_id)
    print(f"Found {len(existing_ids)} existing Codex session(s) in Notion.")

    # 5. Parse, normalise, and import each session.
    imported = 0
    skipped_existing = 0
    skipped_empty = 0
    errors = 0
    total = len(session_files)

    for idx, file_path in enumerate(session_files, start=1):
        rel_path = os.path.relpath(file_path, sessions_dir)

        # 5a. Parse the JSONL file.
        try:
            session = parse_jsonl_file(file_path)
        except (ValueError, OSError) as exc:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR parsing '{rel_path}': {exc}",
                file=sys.stderr,
            )
            continue

        session_id = session["session_id"]

        # 5b. Dedup check.
        if session_id in existing_ids:
            skipped_existing += 1
            print(f"  [{idx}/{total}] SKIP (exists): {rel_path}")
            continue

        # 5c. Normalise into unified schema.
        try:
            conv = normalise_session(session)
        except Exception as exc:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR normalising '{rel_path}': {exc}",
                file=sys.stderr,
            )
            continue

        # 5d. Skip sessions with zero turns.
        if conv["metadata"]["total_turns"] == 0:
            skipped_empty += 1
            print(f"  [{idx}/{total}] SKIP (no turns): {rel_path}")
            continue

        # 5d-2. LLM metadata enrichment.
        if args.use_llm_api:
            try:
                pass  # LLM enrichment removed
            except Exception as exc:
                print(f"  [{idx}/{total}] WARN LLM enrich failed: {exc}", file=sys.stderr)

        # 5d-3. Save to local JSON.
        _save_local(conv)

        # 5e. Create Notion page.
        try:
            page_id = create_conversation_page(client, conversations_db_id, conv)
            imported += 1
            turn_count = conv["metadata"]["total_turns"]
            token_info = ""
            if conv["metadata"].get("token_count"):
                token_info = f", {conv['metadata']['token_count']} tokens"
            print(
                f"  [{idx}/{total}] IMPORTED: {conv['title'][:60]}  "
                f"({turn_count} turns{token_info}, page={page_id})"
            )
        except Exception as exc:
            errors += 1
            print(
                f"  [{idx}/{total}] ERROR importing '{rel_path}': {exc}",
                file=sys.stderr,
            )

    # 6. Summary.
    print()
    print("=" * 60)
    print("  Codex Session Import Summary")
    print("=" * 60)
    print(f"  Total session files  : {total}")
    print(f"  Imported (new)       : {imported}")
    print(f"  Skipped (existing)   : {skipped_existing}")
    print(f"  Skipped (empty)      : {skipped_empty}")
    if errors:
        print(f"  Errors               : {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
