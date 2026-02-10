#!/usr/bin/env python3
"""Sync Skill-authored incremental reports to Notion Analysis Reports database."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from diagnose_helper import validate_incremental_mechanism
from incremental_dimensions import report_sort_key
from notion_client import NotionClient

_CONFIG_PATH = _SCRIPT_DIR.parent / "config.yaml"
_INCREMENTAL_DIR = _SCRIPT_DIR.parent / "data" / "insights" / "incremental"
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
_MECHANISM_TOKENS = (
    "机制",
    "根因",
    "导致",
    "因为",
    "动作",
    "验证",
    "改善",
    "干预",
    "hypothesis",
    "root cause",
    "trigger",
    "action",
    "validation",
)


def _read_json(path: Path) -> Dict[str, Any]:
    """Read JSON file payload."""
    return json.loads(path.read_text(encoding="utf-8"))


def _available_periods(directory: Path) -> List[str]:
    """List available mechanism period IDs in a directory."""
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def _title_text(prop: Dict[str, Any]) -> str:
    """Read Notion title property as plain text."""
    values = prop.get("title", [])
    if not values:
        return ""
    first = values[0]
    return str(first.get("plain_text") or first.get("text", {}).get("content") or "").strip()


def _select_name(prop: Dict[str, Any]) -> str:
    """Read Notion select property name."""
    select = prop.get("select") or {}
    return str(select.get("name") or "").strip()


def _rich_text_text(prop: Dict[str, Any]) -> str:
    """Read Notion rich_text property as concatenated plain text."""
    values = prop.get("rich_text", [])
    if not isinstance(values, list):
        return ""
    parts: List[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        text = str(item.get("plain_text") or item.get("text", {}).get("content") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _contains_cjk(text: str) -> bool:
    """Return True when text contains CJK characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _contains_placeholder(text: str) -> bool:
    """Return True when text looks like mock or placeholder content."""
    content = str(text or "").strip().lower()
    if not content:
        return True
    return any(token in content for token in _PLACEHOLDER_TOKENS)


def _looks_mechanistic(text: str) -> bool:
    """Return True when text contains mechanism-level explanation/action markers."""
    content = str(text or "").strip().lower()
    if not content:
        return False
    return any(token in content for token in _MECHANISM_TOKENS)


def _page_sort_key(page: Dict[str, Any]) -> str:
    """Sort key for keeping the most recently edited page."""
    return str(page.get("last_edited_time") or page.get("created_time") or "")


def _report_key(report: Dict[str, Any]) -> tuple[str, str]:
    """Natural key for a report record."""
    return (
        str(report.get("dimension") or "").strip(),
        str(report.get("period") or "").strip(),
    )


def _build_report_index_and_duplicates(
    client: NotionClient,
    db_id: str,
) -> tuple[Dict[tuple[str, str], str], List[Dict[str, str]]]:
    """Build index and duplicate actions using key (dimension, period)."""
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for page in client.query_database(db_id):
        props = page.get("properties", {})
        key = (
            _select_name(props.get("Dimension", {})),
            _select_name(props.get("Period", {})),
        )
        if not all(key):
            continue
        title = _title_text(props.get("Title", {}))
        insights = _rich_text_text(props.get("Key Insights", {}))
        item = {
            "id": str(page.get("id") or "").strip(),
            "title": title,
            "key_insights": insights,
            "sort_key": _page_sort_key(page),
            "is_zh": _contains_cjk(title) or _contains_cjk(insights),
        }
        if not item["id"]:
            continue
        grouped.setdefault(key, []).append(item)

    index: Dict[tuple[str, str], str] = {}
    duplicates: List[Dict[str, str]] = []
    for key, items in grouped.items():
        zh_items = [item for item in items if bool(item.get("is_zh"))]
        pool = zh_items if zh_items else items
        keeper = sorted(pool, key=lambda x: str(x.get("sort_key") or ""), reverse=True)[0]
        index[key] = str(keeper["id"])

        for item in items:
            page_id = str(item.get("id") or "")
            if page_id and page_id != keeper["id"]:
                duplicates.append(
                    {
                        "page_id": page_id,
                        "key": f"{key[0]}|{key[1]}",
                        "title": str(item.get("title") or ""),
                        "reason": "duplicate_key",
                    }
                )
    return index, duplicates


def load_incremental_mechanism(period_id: Optional[str] = None, latest: bool = False) -> Optional[Dict[str, Any]]:
    """Load incremental mechanism payload by period ID or latest available file."""
    target: Optional[Path] = None
    if period_id:
        candidate = _INCREMENTAL_DIR / f"{period_id}.json"
        if candidate.is_file():
            target = candidate
    elif latest:
        periods = _available_periods(_INCREMENTAL_DIR)
        if periods:
            target = _INCREMENTAL_DIR / f"{periods[-1]}.json"

    if target is None:
        return None

    try:
        payload = _read_json(target)
    except Exception:
        return None

    if validate_incremental_mechanism(payload):
        return None
    return payload


def _normalize_lines(value: Any, *, max_items: int = 400) -> List[str]:
    """Normalize report detail lines from list-like input."""
    lines: List[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                lines.append(text)
    elif isinstance(value, str):
        for raw in value.splitlines():
            text = str(raw or "").strip()
            if text:
                lines.append(text)

    if len(lines) > max_items:
        return lines[:max_items]
    return lines


def _dedupe_lines(lines: List[str], *, max_items: int) -> List[str]:
    """Deduplicate detail lines while preserving first-seen order."""
    deduped: List[str] = []
    seen: set[str] = set()
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= max_items:
            break
    return deduped


def _normalize_report_item(
    item: Dict[str, Any],
    *,
    default_period: str,
    default_date: str,
    default_conversations: int,
) -> Optional[Dict[str, Any]]:
    """Normalize one Skill-authored report item into Notion write contract."""
    if not isinstance(item, dict):
        return None

    dimension = str(item.get("dimension") or "").strip()
    layer = str(item.get("layer") or "").strip()
    title = str(item.get("title") or "").strip()
    key_insights = str(item.get("key_insights") or "").strip()
    if not (dimension and layer and title and key_insights):
        return None

    period = str(item.get("period") or default_period).strip()
    date = str(item.get("date") or default_date).strip()
    if not period:
        period = default_period
    if not date:
        date = default_date

    conv = item.get("conversations_analyzed")
    if not isinstance(conv, int) or conv < 0:
        conv = default_conversations

    max_detail_lines = max(12, min(80, int(default_conversations**0.5 * 2)))
    detail_lines = _normalize_lines(item.get("detail_lines"), max_items=max_detail_lines * 3)
    if not detail_lines:
        detail_lines = _normalize_lines(item.get("detail_text"), max_items=max_detail_lines * 3)
    detail_lines = _dedupe_lines(detail_lines, max_items=max_detail_lines)
    if not detail_lines:
        return None

    detail_text = str(item.get("detail_text") or "").strip()
    if not detail_text:
        detail_text = "\n".join(detail_lines)

    return {
        "dimension": dimension,
        "layer": layer,
        "title": title,
        "period": period,
        "date": date,
        "conversations_analyzed": int(conv),
        "key_insights": key_insights,
        "detail_text": detail_text,
        "detail_lines": detail_lines,
    }


def build_reports_from_incremental(incremental: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build Notion report payloads from Skill-authored `reports` field only."""
    reports_raw = incremental.get("reports")
    if not isinstance(reports_raw, list):
        return []

    default_period = str(incremental.get("period_id") or incremental.get("week") or "unknown-period")
    default_date = datetime.now().strftime("%Y-%m-%d")
    coverage = incremental.get("coverage") if isinstance(incremental.get("coverage"), dict) else {}
    default_conversations = int(coverage.get("sessions_with_mechanism", 0) or 0)

    reports: List[Dict[str, Any]] = []
    for item in reports_raw:
        normalized = _normalize_report_item(
            item,
            default_period=default_period,
            default_date=default_date,
            default_conversations=default_conversations,
        )
        if normalized is None:
            continue
        reports.append(normalized)
    return sorted(reports, key=report_sort_key)


def evaluate_payload_quality(incremental: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Evaluate report payload quality from Skill-authored reports."""
    reasons: List[str] = []
    reports = build_reports_from_incremental(incremental)
    if not reports:
        reasons.append("no valid skill-authored reports found")
        return False, reasons

    for idx, report in enumerate(reports):
        title = str(report.get("title") or "")
        insight = str(report.get("key_insights") or "")
        lines = report.get("detail_lines") or []

        if _contains_placeholder(title):
            reasons.append(f"reports[{idx}] title looks placeholder")
        if _contains_placeholder(insight):
            reasons.append(f"reports[{idx}] key_insights looks placeholder")

        non_placeholder_lines = [line for line in lines if not _contains_placeholder(str(line))]
        if not non_placeholder_lines:
            reasons.append(f"reports[{idx}] detail lines are empty or placeholder-only")
            continue

        mechanism_probe = " ".join([insight, *non_placeholder_lines[:8]])
        if not _looks_mechanistic(mechanism_probe):
            reasons.append(
                f"reports[{idx}] lacks mechanism/action language; avoid statistics-only summary"
            )

    return (len(reasons) == 0), reasons


def _build_report_children(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build Notion body blocks for one report."""
    blocks: List[Dict[str, Any]] = []

    summary = str(report.get("key_insights") or "").strip()
    if summary:
        blocks.append(NotionClient.heading("摘要", level=3))
        blocks.append(NotionClient.paragraph(summary))

    blocks.append(NotionClient.divider())
    blocks.append(NotionClient.heading("详细洞察", level=3))

    detail_lines = report.get("detail_lines")
    if isinstance(detail_lines, list) and detail_lines:
        for line in detail_lines:
            text = str(line or "").strip()
            if text:
                blocks.append(NotionClient.bulleted_list(text))
    else:
        detail_text = str(report.get("detail_text") or "").strip()
        if detail_text:
            blocks.append(NotionClient.paragraph(detail_text))
        else:
            blocks.append(NotionClient.paragraph("暂无可展开的详细洞察。"))

    return blocks


def _write_report(
    client: NotionClient,
    db_id: str,
    report: Dict[str, Any],
    dry_run: bool,
    existing_index: Optional[Dict[tuple[str, str], str]] = None,
) -> bool:
    """Write a single report page to Notion with upsert semantics."""
    props = {
        "Title": {"title": [{"text": {"content": report["title"]}}]},
        "Dimension": {"select": {"name": report["dimension"]}},
        "Layer": {"select": {"name": report["layer"]}},
        "Period": {"select": {"name": report["period"]}},
        "Date": {"date": {"start": report["date"]}},
        "Conversations Analyzed": {"number": int(report["conversations_analyzed"])},
        "Key Insights": {"rich_text": [{"text": {"content": str(report["key_insights"])}}]},
    }
    children = _build_report_children(report)
    key = _report_key(report)
    existing_page_id = existing_index.get(key) if isinstance(existing_index, dict) else None

    if dry_run:
        action = "update" if existing_page_id else "create"
        print(f"[DRY-RUN] Would {action}: {report['title']}")
        return True

    try:
        if existing_page_id:
            client.update_page(existing_page_id, props)
            client.clear_page(existing_page_id)
            if children:
                client.append_blocks(existing_page_id, children)
        else:
            created = client.create_page(
                parent_id=db_id,
                properties=props,
                children=children,
                is_database=True,
            )
            if isinstance(existing_index, dict):
                page_id = str(created.get("id") or "").strip()
                if page_id:
                    existing_index[key] = page_id
        return True
    except Exception as exc:
        print(f"ERROR writing report '{report['title']}': {exc}", file=sys.stderr)
        return False


def _archive_duplicate_pages(
    client: NotionClient,
    duplicates: List[Dict[str, str]],
) -> tuple[int, int]:
    """Archive duplicate report pages before upsert."""
    archived = 0
    failed = 0
    for item in duplicates:
        page_id = str(item.get("page_id") or "").strip()
        if not page_id:
            continue
        try:
            client.archive_page(page_id)
            archived += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR archiving duplicate page {page_id}: {exc}", file=sys.stderr)
    return archived, failed


def sync_reports_from_incremental(
    incremental: Dict[str, Any],
    dry_run: bool = False,
) -> int:
    """Sync reports from a validated IncrementalMechanismV1 object."""
    errors = validate_incremental_mechanism(incremental)
    if errors:
        print("ERROR: mechanism validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    quality_ok, quality_reasons = evaluate_payload_quality(incremental)
    if not quality_ok:
        print("ERROR: incremental mechanism quality gate failed:", file=sys.stderr)
        for reason in quality_reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1

    reports = build_reports_from_incremental(incremental)

    if dry_run:
        print(f"[sync-reports] dry-run with {len(reports)} reports")
        for report in reports:
            preview = str(report.get("key_insights") or "")[:80]
            print(f"  - {report['title']}: {preview}")
        return 0

    if not _CONFIG_PATH.is_file():
        print(f"ERROR: config file not found: {_CONFIG_PATH}", file=sys.stderr)
        return 1

    try:
        client = NotionClient.load_config(str(_CONFIG_PATH))
    except Exception as exc:
        print(f"ERROR: failed to load config: {exc}", file=sys.stderr)
        return 1

    db_id = client.databases.get("analysis_reports")
    if not db_id:
        print("ERROR: analysis_reports database ID missing in config", file=sys.stderr)
        return 1

    existing_index, duplicates = _build_report_index_and_duplicates(client, db_id)
    if duplicates:
        archived, failed = _archive_duplicate_pages(client, duplicates)
        print(
            f"[sync-reports] dedupe archived={archived} failed={failed} "
            f"(keep_key=Dimension+Period, prefer=中文)"
        )
        if failed > 0:
            return 1

    written = 0
    for report in reports:
        if _write_report(client, db_id, report, dry_run=False, existing_index=existing_index):
            written += 1

    print(f"[sync-reports] written {written}/{len(reports)} reports")
    return 0 if written == len(reports) else 1


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI args for incremental mechanism report sync."""
    parser = argparse.ArgumentParser(description="Sync incremental mechanism reports to Notion")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Notion")
    parser.add_argument("--period-id", help="Incremental period ID")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    period_id = args.period_id

    incremental = load_incremental_mechanism(period_id=period_id, latest=not period_id)
    if not incremental:
        print("WARN: no valid incremental mechanism file found")
        return 0 if args.dry_run else 1

    return sync_reports_from_incremental(
        incremental,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
