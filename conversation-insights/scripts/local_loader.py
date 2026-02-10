"""Shared utility for loading conversations from local JSON files.

All conversation data lives in ``data/conversations/{session_id}.json``.
This module provides helpers to load, filter and look up conversations
without touching the Notion API, enabling fast offline access.

Usage::

    from local_loader import load_conversations, get_conversation

    # Load all conversations
    conversations = load_conversations()

    # Load conversations in a date range
    conversations = load_conversations(since="2026-01-25", until="2026-02-01")

    # Look up a single conversation by session ID
    conv = get_conversation("abc-123")
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_SCRIPT_DIR, os.pardir, "data", "conversations")


def load_conversations(
    data_dir: Optional[str] = None,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load conversations from local JSON files with optional filters.

    Parameters
    ----------
    data_dir : str, optional
        Override the default ``data/conversations/`` directory.
    since : str, optional
        ISO date string. Only include conversations created on or after.
    until : str, optional
        ISO date string. Only include conversations created on or before.
    source : str, optional
        Filter by platform (e.g. ``"claude_code"``, ``"chatgpt"``).

    Returns
    -------
    list[dict]
        Loaded conversation dicts sorted by ``created_at`` descending.
    """
    directory = data_dir or _DATA_DIR
    if not os.path.isdir(directory):
        return []

    conversations: List[Dict[str, Any]] = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                conv = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        # Source filter.
        if source and conv.get("source") != source:
            continue

        # Date filters (compare ISO date prefix).
        created = (conv.get("created_at") or "")[:10]
        if since and created < since:
            continue
        if until and created > until:
            continue

        conversations.append(conv)

    # Sort by created_at descending.
    conversations.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return conversations


def get_conversation(
    session_id: str,
    data_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load a single conversation by session ID.

    Parameters
    ----------
    session_id : str
        The session ID (filename stem).
    data_dir : str, optional
        Override the default data directory.

    Returns
    -------
    dict or None
        The conversation dict, or None if not found.
    """
    directory = data_dir or _DATA_DIR
    filepath = os.path.join(directory, f"{session_id}.json")
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
