#!/usr/bin/env python3
"""Skill-first diagnosis helper for conversation-insights."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from local_loader import load_conversations
from incremental_dimensions import (
    DIMENSION_LAYER_MAP,
    is_supported_dimension,
    sort_reports,
)
from skill_runtime import (
    run_api,
    run_incremental_api,
)

_SKILL_ROOT = _SCRIPT_DIR.parent
_DATA_DIR = _SKILL_ROOT / "data" / "conversations"
_INSIGHTS_SESSION_DIR = _SKILL_ROOT / "data" / "insights" / "session"
_INSIGHTS_INCREMENTAL_DIR = _SKILL_ROOT / "data" / "insights" / "incremental"
_SKILL_JOBS_DIR = _SKILL_ROOT / "output" / "skill_jobs"
_SKILLS_DIR = _SKILL_ROOT / "skills"

_SESSION_SCHEMA = "session-mechanism.v1"
_INCREMENTAL_SCHEMA = "incremental-mechanism.v1"
_PLACEHOLDER_TOKENS = (
    "placeholder",
    "insufficient-evidence",
    "no validated",
    "need more session mechanism outputs",
    "collect-more-session-insights",
    "tbd",
    "trigger-missing",
    "action-missing",
    "root-cause-missing",
    "gain-missing",
    "window-missing",
)
_DISALLOWED_GENERATED_BY_ENGINES = {
    "manual",
    "mock",
    "template",
}
_DISALLOWED_GENERATED_BY_PROVIDERS = {
    "skill-manual",
    "manual",
    "mock",
    "api-mock",
    "template",
}
_DISALLOWED_RUN_ID_TOKENS = (
    "replace-mock-sidecars",
    "mock-sidecar",
    "mock-backfill",
)
_MAX_DETAIL_LINES_PER_REPORT = 80
_EVIDENCE_DUMP_PATTERN = re.compile(r"(#t\d+|session[_-]?id|主证据[:：]|辅助证据[:：])", re.IGNORECASE)
_INCREMENTAL_HYPOTHESIS_CHARS = 28
_INCREMENTAL_ACTION_CHARS = 14

def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    """Ensure required directories exist."""
    for path in (
        _INSIGHTS_SESSION_DIR,
        _INSIGHTS_INCREMENTAL_DIR,
        _SKILL_JOBS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON payload with deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _read_json(path: Path) -> Dict[str, Any]:
    """Read JSON payload from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(value: str) -> datetime:
    """Parse YYYY-MM-DD date in UTC."""
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _to_dt(value: str) -> datetime:
    """Parse ISO-8601 timestamp with optional Z suffix."""
    text = (value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _week_from_timestamp(value: str) -> str:
    """Convert timestamp to YYYY-Www."""
    dt = _to_dt(value)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _today_week() -> str:
    """Return current ISO week as YYYY-Www."""
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _contains_placeholder(text: str) -> bool:
    """Return True when text contains low-quality placeholder markers."""
    content = str(text or "").strip().lower()
    if not content:
        return True
    return any(token in content for token in _PLACEHOLDER_TOKENS)


def _generated_by_block_reason(generated_by: Any) -> Optional[str]:
    """Return reason when generated_by metadata indicates simulated output."""
    if not isinstance(generated_by, dict):
        return None

    engine = str(generated_by.get("engine") or "").strip().lower()
    provider = str(generated_by.get("provider") or "").strip().lower()
    run_id = str(generated_by.get("run_id") or "").strip().lower()

    if engine in _DISALLOWED_GENERATED_BY_ENGINES:
        return f"generated_by.engine={engine} is not allowed"
    if provider in _DISALLOWED_GENERATED_BY_PROVIDERS:
        return f"generated_by.provider={provider} is not allowed"
    if any(token in run_id for token in _DISALLOWED_RUN_ID_TOKENS):
        return f"generated_by.run_id contains blocked token: {run_id}"
    return None


def _normalize_evidence_text(text: Any, limit: int = 240) -> str:
    """Normalize evidence snippet for dedupe and display."""
    content = " ".join(str(text or "").strip().split())
    return content[:limit]


def _evidence_identity(item: Dict[str, Any]) -> Optional[Tuple[str, int, str]]:
    """Build stable identity tuple for an evidence entry."""
    session_id = str(item.get("session_id") or "").strip()
    if not session_id:
        return None
    turn_id = item.get("turn_id")
    if not isinstance(turn_id, int) or turn_id <= 0:
        return None
    snippet = _normalize_evidence_text(item.get("snippet"))
    if not snippet:
        return None
    return (session_id, turn_id, snippet.lower())


def _dedupe_evidence(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate evidence by session/turn/snippet identity."""
    seen: set[Tuple[str, int, str]] = set()
    result: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = _evidence_identity(entry)
        if key is None or key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "session_id": key[0],
                "turn_id": key[1],
                "snippet": _normalize_evidence_text(entry.get("snippet")),
            }
        )
    return result


def _select_diverse_evidence(
    entries: Iterable[Dict[str, Any]],
    max_items: int = 6,
    primary_limit: int = 3,
) -> List[Dict[str, Any]]:
    """Select layered evidence with dedupe and cross-session prioritization."""
    if max_items <= 0:
        return []
    deduped = _dedupe_evidence(entries)
    if not deduped:
        return []

    selected: List[Dict[str, Any]] = []
    seen_sessions: set[str] = set()
    primary_cap = max(1, min(primary_limit, max_items))

    for entry in deduped:
        sid = str(entry.get("session_id") or "")
        if not sid or sid in seen_sessions:
            continue
        selected.append({**entry, "tier": "primary"})
        seen_sessions.add(sid)
        if len(selected) >= primary_cap:
            break

    for entry in deduped:
        if len(selected) >= max_items:
            break
        if any(
            str(existing.get("session_id")) == str(entry.get("session_id"))
            and int(existing.get("turn_id", 0)) == int(entry.get("turn_id", 0))
            and str(existing.get("snippet", "")) == str(entry.get("snippet", ""))
            for existing in selected
        ):
            continue
        selected.append({**entry, "tier": "supporting"})
        if len(selected) >= max_items:
            break

    return selected


def _parse_window_to_since(window: str) -> Optional[str]:
    """Parse window expression and return since-date string (YYYY-MM-DD)."""
    value = (window or "").strip().lower()
    if value in {"", "all", "all-time"}:
        return None

    match = re.fullmatch(r"(\d+)d", value)
    if not match:
        raise ValueError("window must be like '30d' or 'all-time'")

    days = int(match.group(1))
    if days <= 0:
        raise ValueError("window days must be positive")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    return since.date().isoformat()


def _turn_snippet(text: str, limit: int = 200) -> str:
    """Trim a text snippet to a bounded length."""
    cleaned = " ".join((text or "").split())
    return cleaned[:limit]


def _select_timeline_turns(turns: List[Dict[str, Any]], max_turns: int = 12) -> List[Dict[str, Any]]:
    """Select representative turns for digest while controlling prompt size."""
    if len(turns) <= max_turns:
        return turns

    head = max_turns // 2
    tail = max_turns - head
    selected = list(turns[:head]) + list(turns[-tail:])

    deduped: List[Dict[str, Any]] = []
    seen_turn_ids: set[int] = set()
    for turn in selected:
        turn_id = int(turn.get("turn_id") or 0)
        if turn_id > 0 and turn_id in seen_turn_ids:
            continue
        if turn_id > 0:
            seen_turn_ids.add(turn_id)
        deduped.append(turn)
    return deduped


def build_session_digest(conv: Dict[str, Any]) -> Dict[str, Any]:
    """Build SessionDigestV1 from unified conversation JSON."""
    metadata = conv.get("metadata", {})
    llm = metadata.get("llm_metadata") or {}
    created_at = str(conv.get("created_at", ""))
    turns = conv.get("turns", [])

    timeline: List[Dict[str, Any]] = []
    for idx, turn in enumerate(_select_timeline_turns(turns, max_turns=12), start=1):
        user_text = turn.get("user_message", {}).get("content", "")
        assistant_text = turn.get("assistant_response", {}).get("content", "")
        tool_uses = turn.get("assistant_response", {}).get("tool_uses", [])
        timeline.append(
            {
                "turn_id": int(turn.get("turn_id", idx) or idx),
                "user_snippet": _turn_snippet(str(user_text), 140),
                "assistant_snippet": _turn_snippet(str(assistant_text), 120),
                "correction_count": len(turn.get("corrections") or []),
                "tools": [str(t.get("tool_name", "")) for t in tool_uses if t.get("tool_name")],
            }
        )

    return {
        "schema_version": "session-digest.v1",
        "session_id": str(conv.get("session_id", "")),
        "source": str(conv.get("source", "unknown")),
        "model": str(conv.get("model") or "unknown"),
        "title": str(conv.get("title") or ""),
        "created_at": created_at,
        "week": _week_from_timestamp(created_at),
        "turn_count": int(metadata.get("total_turns", len(turns)) or 0),
        "tool_count": int(metadata.get("total_tool_uses", 0) or 0),
        "primary_language": str(metadata.get("primary_language", "unknown")),
        "detected_domains": list(metadata.get("detected_domains") or []),
        "llm_metadata": {
            "conversation_intent": llm.get("conversation_intent"),
            "task_type": llm.get("task_type"),
            "actual_domains": llm.get("actual_domains") or [],
            "difficulty": llm.get("difficulty"),
            "outcome": llm.get("outcome"),
            "key_topics": llm.get("key_topics") or [],
            "prompt_quality": llm.get("prompt_quality") or {},
            "cognitive_patterns": llm.get("cognitive_patterns") or [],
            "conversation_summary": llm.get("conversation_summary") or "",
        },
        "timeline": timeline,
    }


def _validate_evidence(evidence: Dict[str, Any], index: int) -> List[str]:
    """Validate evidence object used by mechanism contracts."""
    errors: List[str] = []
    session_id = evidence.get("session_id")
    turn_id = evidence.get("turn_id")
    snippet = evidence.get("snippet")

    if not isinstance(session_id, str) or not session_id.strip():
        errors.append(f"evidence[{index}].session_id must be non-empty string")
    if not isinstance(turn_id, int) or turn_id <= 0:
        errors.append(f"evidence[{index}].turn_id must be positive integer")
    if not isinstance(snippet, str) or not snippet.strip():
        errors.append(f"evidence[{index}].snippet must be non-empty string")
    tier = evidence.get("tier")
    if tier is not None and tier not in {"primary", "supporting"}:
        errors.append(f"evidence[{index}].tier must be 'primary' or 'supporting' when present")
    return errors


def validate_session_mechanism(payload: Dict[str, Any]) -> List[str]:
    """Validate SessionMechanismV1 payload."""
    errors: List[str] = []

    if payload.get("schema_version") != _SESSION_SCHEMA:
        errors.append(f"schema_version must be '{_SESSION_SCHEMA}'")

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        errors.append("session_id must be non-empty string")

    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        errors.append("created_at must be non-empty string")

    week = payload.get("week")
    period_id = payload.get("period_id")
    if week is not None and (not isinstance(week, str) or not week.strip()):
        errors.append("week must be non-empty string when present")
    if period_id is not None and (not isinstance(period_id, str) or not period_id.strip()):
        errors.append("period_id must be non-empty string when present")

    what_happened = payload.get("what_happened")
    if not isinstance(what_happened, list) or not what_happened:
        errors.append("what_happened must be non-empty list")

    why_items = payload.get("why")
    if not isinstance(why_items, list) or not why_items:
        errors.append("why must be non-empty list")
    else:
        for idx, item in enumerate(why_items):
            if not isinstance(item, dict):
                errors.append(f"why[{idx}] must be object")
                continue
            hypothesis = item.get("hypothesis")
            if not isinstance(hypothesis, str) or not hypothesis.strip():
                errors.append(f"why[{idx}].hypothesis must be non-empty string")
            confidence = item.get("confidence")
            if confidence is not None and not isinstance(confidence, (int, float)):
                errors.append(f"why[{idx}].confidence must be number when present")
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"why[{idx}].evidence must be non-empty list")
            else:
                for ev_idx, ev in enumerate(evidence):
                    if not isinstance(ev, dict):
                        errors.append(f"why[{idx}].evidence[{ev_idx}] must be object")
                        continue
                    errors.extend(_validate_evidence(ev, ev_idx))

    actions = payload.get("how_to_improve")
    if not isinstance(actions, list) or not actions:
        errors.append("how_to_improve must be non-empty list")
    else:
        for idx, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"how_to_improve[{idx}] must be object")
                continue
            for key in ("trigger", "action", "expected_gain", "validation_window"):
                if not isinstance(action.get(key), str) or not action.get(key, "").strip():
                    errors.append(f"how_to_improve[{idx}].{key} must be non-empty string")

    labels = payload.get("labels")
    if labels is not None and not isinstance(labels, list):
        errors.append("labels must be list when present")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("summary must be non-empty string")

    generated_by = payload.get("generated_by")
    if not isinstance(generated_by, dict):
        errors.append("generated_by must be object")
    else:
        for key in ("engine", "provider", "model", "run_id", "generated_at"):
            if not isinstance(generated_by.get(key), str) or not generated_by.get(key, "").strip():
                errors.append(f"generated_by.{key} must be non-empty string")
        block_reason = _generated_by_block_reason(generated_by)
        if block_reason:
            errors.append(f"generated_by is blocked: {block_reason}")

    return errors


def validate_incremental_mechanism(payload: Dict[str, Any]) -> List[str]:
    """Validate IncrementalMechanismV1 payload."""
    errors: List[str] = []

    schema_version = payload.get("schema_version")
    if schema_version != _INCREMENTAL_SCHEMA:
        errors.append(f"schema_version must be '{_INCREMENTAL_SCHEMA}'")

    period_id = payload.get("period_id")
    week = payload.get("week")
    if isinstance(period_id, str) and period_id.strip():
        pass
    elif isinstance(week, str) and week.strip():
        pass
    else:
        errors.append("period_id or week must be provided")

    period = payload.get("period")
    if period is not None:
        if not isinstance(period, dict):
            errors.append("period must be object when present")
        else:
            for key in ("since", "until"):
                if key in period and (
                    not isinstance(period.get(key), str) or not period.get(key, "").strip()
                ):
                    errors.append(f"period.{key} must be non-empty string when present")

    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        errors.append("reports must be non-empty list")
    else:
        seen_report_keys: set[Tuple[str, str]] = set()
        for idx, item in enumerate(reports):
            if not isinstance(item, dict):
                errors.append(f"reports[{idx}] must be object")
                continue
            for key in ("dimension", "layer", "title", "key_insights"):
                if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                    errors.append(f"reports[{idx}].{key} must be non-empty string")
            dimension = str(item.get("dimension") or "").strip()
            layer = str(item.get("layer") or "").strip()
            if dimension and not is_supported_dimension(dimension):
                supported = ", ".join(sorted(DIMENSION_LAYER_MAP.keys()))
                errors.append(
                    f"reports[{idx}].dimension must be one of [{supported}]"
                )
            expected_layer = DIMENSION_LAYER_MAP.get(dimension)
            if dimension and expected_layer and layer and layer != expected_layer:
                errors.append(
                    f"reports[{idx}].layer must be '{expected_layer}' for dimension '{dimension}'"
                )

            for key in ("period", "date"):
                value = item.get(key)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    errors.append(f"reports[{idx}].{key} must be non-empty string when present")
            period_key = str(item.get("period") or period_id or week or "").strip()
            if dimension and period_key:
                report_key = (dimension, period_key)
                if report_key in seen_report_keys:
                    errors.append(
                        f"duplicate report key detected for dimension+period: {dimension}+{period_key}"
                    )
                else:
                    seen_report_keys.add(report_key)

            conversations_analyzed = item.get("conversations_analyzed")
            if conversations_analyzed is not None and (
                not isinstance(conversations_analyzed, int) or conversations_analyzed < 0
            ):
                errors.append(f"reports[{idx}].conversations_analyzed must be non-negative integer when present")

            detail_lines = item.get("detail_lines")
            detail_text = item.get("detail_text")
            has_lines = isinstance(detail_lines, list) and any(
                isinstance(line, str) and line.strip() for line in detail_lines
            )
            has_text = isinstance(detail_text, str) and detail_text.strip()
            if not has_lines and not has_text:
                errors.append(f"reports[{idx}] requires detail_lines or detail_text")
            if isinstance(detail_lines, list):
                normalized_lines = [
                    str(line).strip()
                    for line in detail_lines
                    if isinstance(line, str) and str(line).strip()
                ]
                if len(normalized_lines) > _MAX_DETAIL_LINES_PER_REPORT:
                    errors.append(
                        f"reports[{idx}].detail_lines has {len(normalized_lines)} lines; "
                        f"expected aggregated insights <= {_MAX_DETAIL_LINES_PER_REPORT}"
                    )
                if len(normalized_lines) >= 20:
                    evidence_like = sum(
                        1 for line in normalized_lines if _EVIDENCE_DUMP_PATTERN.search(line)
                    )
                    if evidence_like / len(normalized_lines) >= 0.7:
                        errors.append(
                            f"reports[{idx}] looks like per-session evidence dump; "
                            "aggregate into mechanism-level insights"
                        )

    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be object")
    else:
        for key in ("sessions_total", "sessions_with_mechanism"):
            if not isinstance(coverage.get(key), int) or coverage.get(key, -1) < 0:
                errors.append(f"coverage.{key} must be non-negative integer")
        sessions_total = coverage.get("sessions_total")
        with_mechanism = coverage.get("sessions_with_mechanism")
        if (
            isinstance(sessions_total, int)
            and isinstance(with_mechanism, int)
            and with_mechanism > sessions_total
        ):
            errors.append("coverage.sessions_with_mechanism cannot exceed coverage.sessions_total")

    what_happened = payload.get("what_happened")
    if what_happened is not None and not isinstance(what_happened, list):
        errors.append("what_happened must be list when present")

    return errors


def _normalize_session_payload(raw: Any) -> List[Dict[str, Any]]:
    """Normalize session mechanism payload to a list."""
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    if isinstance(raw, dict):
        if isinstance(raw.get("sessions"), list):
            return [item for item in raw["sessions"] if isinstance(item, dict)]

        normalized: List[Dict[str, Any]] = []
        # Map style: {"session_id": {...}}
        for sid, value in raw.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            item.setdefault("session_id", str(sid))
            normalized.append(item)
        return normalized

    return []


def _load_session_sidecars() -> List[Dict[str, Any]]:
    """Load all session sidecar files."""
    sidecars: List[Dict[str, Any]] = []
    if not _INSIGHTS_SESSION_DIR.is_dir():
        return sidecars

    for path in sorted(_INSIGHTS_SESSION_DIR.glob("*.json")):
        try:
            payload = _read_json(path)
        except Exception:
            continue
        block_reason = _generated_by_block_reason(payload.get("generated_by"))
        if block_reason:
            continue
        sidecars.append(payload)
    return sidecars


def _filter_sessions_by_period(
    sessions: Iterable[Dict[str, Any]],
    *,
    since: Optional[str],
    until: Optional[str],
) -> List[Dict[str, Any]]:
    """Filter session mechanisms by created_at date range."""
    if since:
        since_dt = _parse_date(since)
    else:
        since_dt = None
    if until:
        until_dt = _parse_date(until)
    else:
        until_dt = None

    filtered: List[Dict[str, Any]] = []
    for item in sessions:
        created_at = item.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            continue
        created_dt = _to_dt(created_at)
        if since_dt and created_dt < since_dt:
            continue
        if until_dt and created_dt > (until_dt + timedelta(days=1)):
            continue
        filtered.append(item)
    return filtered


def _count_conversations_in_period(*, since: Optional[str], until: Optional[str]) -> int:
    """Count source conversations in date range for accurate coverage."""
    conversations = load_conversations(str(_DATA_DIR), since=since, until=until)
    return len(conversations)


def _has_valid_evidence_item(item: Dict[str, Any]) -> bool:
    """Check whether evidence item is concrete and non-placeholder."""
    session_id = str(item.get("session_id") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    turn_id = item.get("turn_id")
    if not session_id or session_id.lower() in {"n/a", "unknown"}:
        return False
    if not isinstance(turn_id, int) or turn_id <= 0:
        return False
    if not snippet or _contains_placeholder(snippet):
        return False
    return True


def _session_has_mechanism_signal(session: Dict[str, Any]) -> bool:
    """Check whether a session sidecar contains usable mechanism insights."""
    block_reason = _generated_by_block_reason(session.get("generated_by"))
    if block_reason:
        return False

    summary = str(session.get("summary") or "")
    if _contains_placeholder(summary):
        return False

    why_items = session.get("why") or []
    for why in why_items:
        if not isinstance(why, dict):
            continue
        hypothesis = str(why.get("hypothesis") or "").strip()
        if not hypothesis or _contains_placeholder(hypothesis):
            continue
        evidence = why.get("evidence") or []
        if not isinstance(evidence, list):
            continue
        if any(_has_valid_evidence_item(item) for item in evidence if isinstance(item, dict)):
            return True

    return False


def _build_period_id(
    *,
    since: Optional[str],
    until: Optional[str],
    window: Optional[str],
    explicit_period_id: Optional[str],
) -> str:
    """Build deterministic period identifier."""
    if explicit_period_id and explicit_period_id.strip():
        return explicit_period_id.strip()
    if since or until:
        return f"{since or 'open'}_to_{until or 'today'}"
    if window:
        return f"rolling_{window}"
    return "rolling_30d"


def _compact_session_for_incremental(session: Dict[str, Any]) -> Dict[str, Any]:
    """Build compact session payload for incremental Skill inference."""
    compact: Dict[str, Any] = {
        "session_id": str(session.get("session_id") or "").strip(),
        "created_at": str(session.get("created_at") or "").strip(),
    }

    labels = session.get("labels")
    if isinstance(labels, list):
        compact["labels"] = [
            str(label).strip()
            for label in labels
            if isinstance(label, str) and str(label).strip()
        ][:1]

    mechanism: Dict[str, Any] = {}
    for why in session.get("why") or []:
        if not isinstance(why, dict):
            continue
        hypothesis = str(why.get("hypothesis") or "").strip()
        if not hypothesis:
            continue
        mechanism["hypothesis"] = _turn_snippet(hypothesis, _INCREMENTAL_HYPOTHESIS_CHARS)
        confidence = why.get("confidence")
        if isinstance(confidence, (int, float)):
            mechanism["confidence"] = round(float(confidence), 3)
        evidence_raw = why.get("evidence") or []
        if isinstance(evidence_raw, list):
            filtered_evidence = [
                ev for ev in evidence_raw if isinstance(ev, dict) and _has_valid_evidence_item(ev)
            ]
            evidence = _select_diverse_evidence(filtered_evidence, max_items=1, primary_limit=1)
            evidence_refs: List[str] = []
            for evidence_item in evidence:
                sid = str(evidence_item.get("session_id") or "").strip()
                tid = int(evidence_item.get("turn_id") or 0)
                if sid and tid > 0:
                    evidence_refs.append(f"{sid}#T{tid}")
            if evidence_refs:
                mechanism["evidence_refs"] = evidence_refs
        if mechanism:
            break
    if mechanism:
        compact["mechanism"] = mechanism

    for action in session.get("how_to_improve") or []:
        if not isinstance(action, dict):
            continue
        do_action = str(action.get("action") or "").strip()
        if not do_action:
            continue
        compact["action_ref"] = _turn_snippet(do_action, _INCREMENTAL_ACTION_CHARS)
        break
    return compact


def _build_incremental_skill_input(
    *,
    period_id: str,
    run_id: str,
    window: Optional[str],
    since: Optional[str],
    until: Optional[str],
    sessions_total: int,
    sessions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build IncrementalInputV1 payload for Skill execution."""
    period: Dict[str, str] = {}
    if window:
        period["window"] = str(window)
    if since:
        period["since"] = since
    if until:
        period["until"] = until

    compact_sessions = [_compact_session_for_incremental(session) for session in sessions]
    return {
        "schema_version": "incremental-input.v1",
        "period_id": period_id,
        "generated_at": _now_iso(),
        "source_run_id": run_id,
        "period": period,
        "coverage": {
            "sessions_total": max(int(sessions_total), len(compact_sessions)),
            "sessions_with_mechanism": len(compact_sessions),
        },
        "sessions": compact_sessions,
    }


def _coerce_incremental_payload(raw: Any) -> Dict[str, Any]:
    """Normalize payload to incremental mechanism aggregate object."""
    if isinstance(raw, dict) and raw.get("schema_version") == _INCREMENTAL_SCHEMA:
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("incremental"), dict):
        return raw["incremental"]
    return {}


def _write_run_bundle(
    *,
    run_id: str,
    window: str,
    source: str,
    limit: Optional[int],
    digests: List[Dict[str, Any]],
) -> Path:
    """Write run bundle and instruction file."""
    run_dir = _SKILL_JOBS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "schema_version": "diagnose-run.v1",
        "run_id": run_id,
        "created_at": _now_iso(),
        "window": window,
        "source": source,
        "limit": limit,
        "session_count": len(digests),
        "sessions": digests,
    }

    bundle_path = run_dir / "session_digests.json"
    _write_json(bundle_path, bundle)

    hint_path = run_dir / "README.md"
    hint_path.write_text(
        "\n".join(
            [
                "# Diagnose Run (Internal Debug Bundle)",
                "",
                f"- run_id: `{run_id}`",
                f"- sessions: `{len(digests)}`",
                "",
                "此目录用于故障排查，不是日常运行入口。",
                "",
                "## Recommended",
                "",
                "请优先使用统一入口：",
                "- `python3 scripts/pipeline.py`",
                "- `python3 scripts/pipeline.py run --mode full`",
            ]
        ),
        encoding="utf-8",
    )
    return bundle_path


def _session_needs_backfill(session_id: str, *, force_refresh: bool) -> bool:
    """Return True if a session sidecar is missing, invalid, or low-quality."""
    if force_refresh:
        return True

    path = _INSIGHTS_SESSION_DIR / f"{session_id}.json"
    if not path.is_file():
        return True

    try:
        payload = _read_json(path)
    except Exception:
        return True

    if validate_session_mechanism(payload):
        return True
    if not _session_has_mechanism_signal(payload):
        return True
    return False


def _apply_session_results(
    *,
    run_id: str,
    result_path: Path,
    allow_partial: bool,
) -> int:
    """Validate and persist SessionMechanismV1 payloads."""
    _ensure_dirs()

    result_path = result_path.expanduser().resolve()
    if not result_path.is_file():
        print(f"ERROR: result file not found: {result_path}", file=sys.stderr)
        return 2

    try:
        raw_payload = _read_json(result_path)
    except Exception as exc:
        print(f"ERROR: failed to read result file: {exc}", file=sys.stderr)
        return 2

    items = _normalize_session_payload(raw_payload)
    if not items:
        print("ERROR: no session mechanism records found in result payload", file=sys.stderr)
        return 2

    invalid: List[str] = []
    invalid_records: List[Dict[str, Any]] = []
    valid_items: List[Dict[str, Any]] = []

    for index, item in enumerate(items):
        record = dict(item)
        record.setdefault("schema_version", _SESSION_SCHEMA)
        record.setdefault("generated_by", {})
        if isinstance(record.get("generated_by"), dict):
            generated_by = dict(record["generated_by"])
        else:
            generated_by = {}

        generated_by.setdefault("engine", "api")
        generated_by.setdefault("provider", "api")
        generated_by.setdefault("model", "skill")
        generated_by.setdefault("run_id", run_id)
        generated_by.setdefault("generated_at", _now_iso())
        record["generated_by"] = generated_by

        if not record.get("week") and isinstance(record.get("created_at"), str):
            record["week"] = _week_from_timestamp(str(record.get("created_at", "")))
        if not record.get("period_id") and record.get("week"):
            record["period_id"] = str(record.get("week"))

        errors = validate_session_mechanism(record)
        if errors:
            invalid.append(f"index {index} session_id={record.get('session_id')}: {'; '.join(errors)}")
            invalid_records.append(
                {
                    "index": index,
                    "session_id": str(record.get("session_id") or ""),
                    "errors": errors,
                }
            )
            continue
        valid_items.append(record)

    run_dir = _SKILL_JOBS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if invalid and not allow_partial:
        print("ERROR: session mechanism validation failed:", file=sys.stderr)
        for line in invalid:
            print(f"  - {line}", file=sys.stderr)
        return 1

    if invalid and allow_partial:
        invalid_path = run_dir / "invalid_session_mechanisms.json"
        _write_json(
            invalid_path,
            {
                "schema_version": "diagnose-invalid-session-mechanisms.v1",
                "run_id": run_id,
                "generated_at": _now_iso(),
                "invalid_count": len(invalid_records),
                "invalid_records": invalid_records,
            },
        )
        print(
            f"[diagnose-apply] warning: skipped invalid session mechanisms={len(invalid_records)}"
        )
        print(f"[diagnose-apply] invalid_details={invalid_path}")

    if not valid_items:
        print("ERROR: no valid session mechanisms after validation", file=sys.stderr)
        return 1

    created = 0
    updated = 0

    for record in valid_items:
        session_id = str(record["session_id"])
        out_path = _INSIGHTS_SESSION_DIR / f"{session_id}.json"
        rendered = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
        if out_path.is_file():
            existing = out_path.read_text(encoding="utf-8")
            if existing == rendered:
                continue
            updated += 1
        else:
            created += 1
        out_path.write_text(rendered, encoding="utf-8")

    summary = {
        "schema_version": "diagnose-apply-summary.v1",
        "run_id": run_id,
        "applied_at": _now_iso(),
        "result_file": str(result_path),
        "records_valid": len(valid_items),
        "records_invalid": len(invalid_records),
        "created": created,
        "updated": updated,
    }

    _write_json(run_dir / "apply_summary.json", summary)

    print(f"[diagnose-apply] run_id={run_id}")
    print(f"[diagnose-apply] valid={len(valid_items)} created={created} updated={updated}")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Backfill missing/invalid session sidecars, then optionally apply automatically."""
    _ensure_dirs()

    since_arg = args.since
    until_arg = args.until
    if not since_arg and not until_arg and args.window:
        try:
            parsed_since = _parse_window_to_since(args.window)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        since_arg = parsed_since
        if parsed_since is not None:
            until_arg = datetime.now(timezone.utc).date().isoformat()

    source = None if args.source in {None, "", "all"} else args.source
    conversations = load_conversations(str(_DATA_DIR), since=since_arg, until=until_arg, source=source)
    if args.limit is not None and args.limit > 0:
        conversations = conversations[: args.limit]

    target_conversations: List[Dict[str, Any]] = []
    for conv in conversations:
        session_id = str(conv.get("session_id") or "").strip()
        if not session_id:
            continue
        if _session_needs_backfill(session_id, force_refresh=args.force_refresh):
            target_conversations.append(conv)

    if not target_conversations:
        print(
            f"[diagnose-backfill] no target sessions (checked={len(conversations)} window={args.window})"
        )
        return 0

    run_id = args.run_id or f"backfill-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    digests = [build_session_digest(conv) for conv in target_conversations]
    _write_run_bundle(
        run_id=run_id,
        window=args.window,
        source=args.source,
        limit=args.limit,
        digests=digests,
    )

    print(
        f"[diagnose-backfill] prepared run_id={run_id} "
        f"targets={len(target_conversations)} checked={len(conversations)}"
    )

    run_rc = run_api(
        run_id,
        _SKILL_JOBS_DIR,
        args.provider,
        args.dry_run,
        skills_root=_SKILLS_DIR,
        model=args.model,
        timeout_sec=args.timeout_sec,
        allow_partial=args.allow_partial,
        max_workers=args.max_workers,
    )
    if run_rc != 0:
        return int(run_rc)
    if args.dry_run:
        return 0

    result_path = _SKILL_JOBS_DIR / run_id / f"api_{args.provider}_results.json"
    if not result_path.is_file():
        print(f"ERROR: backfill result file missing: {result_path}", file=sys.stderr)
        return 2

    return _apply_session_results(
        run_id=run_id,
        result_path=result_path,
        allow_partial=bool(args.allow_partial),
    )


def cmd_incremental(args: argparse.Namespace) -> int:
    """Apply incremental mechanism payload and optionally sync reports."""
    _ensure_dirs()

    since_arg = args.since
    until_arg = args.until
    if not since_arg and not until_arg and args.window:
        try:
            parsed_since = _parse_window_to_since(args.window)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        since_arg = parsed_since
        if parsed_since is not None:
            until_arg = datetime.now(timezone.utc).date().isoformat()

    if args.period_id:
        period_id = args.period_id
    else:
        period_id = _build_period_id(
            since=since_arg,
            until=until_arg,
            window=args.window,
            explicit_period_id=None,
        )

    run_id = args.run_id or f"incremental-{period_id}"
    source_conversations = load_conversations(str(_DATA_DIR), since=since_arg, until=until_arg)

    sidecars_all = _load_session_sidecars()
    valid_sidecars: List[Dict[str, Any]] = []
    for item in sidecars_all:
        if validate_session_mechanism(item):
            continue
        valid_sidecars.append(item)
    filtered = _filter_sessions_by_period(valid_sidecars, since=since_arg, until=until_arg)

    payload: Dict[str, Any]
    if args.result_file:
        result_path = Path(args.result_file).expanduser().resolve()
        if not result_path.is_file():
            print(f"ERROR: result file not found: {result_path}", file=sys.stderr)
            return 2

        raw = _read_json(result_path)
        payload = _coerce_incremental_payload(raw)
        if not payload:
            print("ERROR: incremental result payload is empty or malformed", file=sys.stderr)
            return 2
        payload_period = payload.get("period_id") or payload.get("week")
        if args.period_id and payload_period != args.period_id:
            print(
                f"ERROR: payload period={payload_period} does not match --period-id {args.period_id}",
                file=sys.stderr,
                )
            return 2
    else:
        input_payload = _build_incremental_skill_input(
            period_id=period_id,
            run_id=run_id,
            window=args.window,
            since=since_arg,
            until=until_arg,
            sessions_total=_count_conversations_in_period(since=since_arg, until=until_arg),
            sessions=filtered,
        )
        runtime_rc, generated_path = run_incremental_api(
            run_id=run_id,
            jobs_root=_SKILL_JOBS_DIR,
            provider=args.provider,
            dry_run=args.dry_run,
            incremental_input=input_payload,
            skills_root=_SKILLS_DIR,
            model=args.model,
            timeout_sec=args.timeout_sec,
        )

        if runtime_rc != 0:
            return int(runtime_rc)
        if args.dry_run and generated_path is None:
            print(f"[diagnose-incremental] period={period_id} dry-run (skill runtime preview only)")
            return 0
        if generated_path is None or not generated_path.is_file():
            print("ERROR: incremental skill result file missing", file=sys.stderr)
            return 2
        raw = _read_json(generated_path)
        payload = _coerce_incremental_payload(raw)
        if not payload:
            print("ERROR: incremental skill result payload is empty or malformed", file=sys.stderr)
            return 2

    payload.setdefault("schema_version", _INCREMENTAL_SCHEMA)
    payload.setdefault("period_id", period_id)
    payload.setdefault("week", str(payload.get("period_id") or period_id))
    payload.setdefault("source_run_id", run_id)
    payload.setdefault("generated_at", _now_iso())
    if not isinstance(payload.get("period"), dict):
        payload["period"] = {}
    if since_arg and not payload["period"].get("since"):
        payload["period"]["since"] = since_arg
    if until_arg and not payload["period"].get("until"):
        payload["period"]["until"] = until_arg
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        payload["coverage"] = {}
        coverage = payload["coverage"]
    coverage.setdefault("sessions_total", len(source_conversations))
    coverage.setdefault("sessions_with_mechanism", len(filtered))
    if isinstance(payload.get("reports"), list):
        payload["reports"] = sort_reports(
            [item for item in payload["reports"] if isinstance(item, dict)]
        )

    errors = validate_incremental_mechanism(payload)
    if errors:
        print("ERROR: incremental mechanism validation failed:", file=sys.stderr)
        for msg in errors:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    out_path = _INSIGHTS_INCREMENTAL_DIR / f"{period_id}.json"

    if args.dry_run:
        print(f"[diagnose-incremental] period={period_id} dry-run")
        print(
            f"[diagnose-incremental] reports={len(payload.get('reports', []))} "
            f"coverage={payload.get('coverage', {})}"
        )
    else:
        _write_json(out_path, payload)
        print(f"[diagnose-incremental] written: {out_path}")

    if args.sync_report:
        from _sync_analysis_reports_core import sync_reports_from_incremental

        return sync_reports_from_incremental(
            payload,
            dry_run=args.dry_run,
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for diagnose helper."""
    parser = argparse.ArgumentParser(description="Skill-first diagnose helper")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill", help="Auto backfill session sidecars and apply results")
    backfill.add_argument("--window", default="30d", help="Window like 30d or all-time")
    backfill.add_argument("--since", help="Start date YYYY-MM-DD (overrides --window)")
    backfill.add_argument("--until", help="End date YYYY-MM-DD")
    backfill.add_argument(
        "--source",
        default="all",
        choices=["all", "chatgpt", "claude_code", "codex", "gemini", "claude_web"],
        help="Source filter",
    )
    backfill.add_argument("--limit", type=int, help="Optional max candidate sessions")
    backfill.add_argument("--run-id", help="Optional run id")
    backfill.add_argument(
        "--provider",
        default="claude_cli",
        choices=["claude_cli", "codex_cli", "anthropic", "openai"],
        help="API provider",
    )
    backfill.add_argument("--model", help="Optional API model override")
    backfill.add_argument("--timeout-sec", type=int, default=180, help="API timeout seconds")
    backfill.add_argument("--max-workers", type=int, default=4, help="Concurrent workers for API provider")
    backfill.add_argument("--force-refresh", action="store_true", help="Refresh all selected sessions")
    backfill.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow partial API failures (default: fail if any session fails)",
    )
    backfill.add_argument("--dry-run", action="store_true", help="Preview only")
    backfill.set_defaults(handler=cmd_backfill)

    incremental = sub.add_parser("incremental", help="Build/apply incremental mechanism payload")
    incremental.add_argument("--period-id", help="Incremental period identifier")
    incremental.add_argument("--window", default="30d", help="Rolling window like 30d or all-time")
    incremental.add_argument("--since", help="Start date YYYY-MM-DD (overrides --window)")
    incremental.add_argument("--until", help="End date YYYY-MM-DD (defaults today when window is used)")
    incremental.add_argument("--result-file", help="Incremental mechanism JSON result file")
    incremental.add_argument("--run-id", help="Optional source run identifier")
    incremental.add_argument(
        "--provider",
        default="claude_cli",
        choices=["claude_cli", "codex_cli", "anthropic", "openai"],
        help="Incremental skill provider",
    )
    incremental.add_argument("--model", help="Optional provider model override")
    incremental.add_argument("--timeout-sec", type=int, default=180, help="Provider timeout seconds")
    incremental.add_argument("--sync-report", action="store_true", help="Sync incremental mechanism to Notion report DB")
    incremental.add_argument("--dry-run", action="store_true", help="Preview only")
    incremental.set_defaults(handler=cmd_incremental)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
