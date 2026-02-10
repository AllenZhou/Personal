#!/usr/bin/env python3
"""
可视化仪表盘生成器 — 静态 HTML Dashboard

读取本地 JSON 对话数据（主数据源）+ Notion 数据库（补充数据源），
生成一个自包含的 HTML 仪表盘文件，浏览器打开即可查看所有分析数据。

Usage::

    python scripts/dashboard.py                  # 生成仪表盘
    python scripts/dashboard.py --no-notion      # 仅使用本地数据
    python scripts/dashboard.py -o my_dash.html  # 指定输出路径

输出文件: output/dashboard.html（默认）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from local_loader import load_conversations  # noqa: E402
from incremental_dimensions import report_sort_key  # noqa: E402

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))
_DEFAULT_OUTPUT = os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "output", "dashboard.html")
)
_INSIGHTS_DIR = os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "data", "insights")
)
_OUTPUT_DIR_L3 = os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "output")
)


# ---------------------------------------------------------------------------
# Notion data fetching (optional)
# ---------------------------------------------------------------------------

def _load_notion_client():
    """Try to load the Notion client. Returns None on failure."""
    try:
        from notion_client import NotionClient
        if not os.path.isfile(_CONFIG_PATH):
            return None
        return NotionClient.load_config(_CONFIG_PATH)
    except Exception:
        return None


def _fetch_notion_tool_stats(client) -> List[Dict[str, Any]]:
    """Fetch Tool Stats from Notion."""
    try:
        db_id = client.databases.get("tool_stats")
        if not db_id:
            return []
        pages = client.query_database(db_id)
        results = []
        for page in pages:
            props = page.get("properties", {})
            name = _notion_title(props.get("Tool Name", {}))
            usage = _notion_number(props.get("Usage Count", {}))
            success = _notion_number(props.get("Success Rate", {}))
            results.append({
                "name": name,
                "usage": int(usage) if usage else 0,
                "success_rate": success or 0.0,
            })
        return sorted(results, key=lambda x: x["usage"], reverse=True)
    except Exception:
        return []


def _fetch_notion_domain_map(client) -> List[Dict[str, Any]]:
    """Fetch Domain Map from Notion."""
    try:
        db_id = client.databases.get("domain_map")
        if not db_id:
            return []
        pages = client.query_database(db_id)
        results = []
        for page in pages:
            props = page.get("properties", {})
            name = _notion_title(props.get("Domain", {}))
            count = _notion_number(props.get("Conversation Count", {}))
            depth = _notion_number(props.get("Depth Score", {}))
            trend = _notion_select(props.get("Trend", {}))
            results.append({
                "name": name,
                "count": int(count) if count else 0,
                "depth": depth or 0.0,
                "trend": trend or "stable",
            })
        return sorted(results, key=lambda x: x["count"], reverse=True)
    except Exception:
        return []


def _fetch_notion_reports(client, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent Analysis Reports from Notion."""
    try:
        db_id = client.databases.get("analysis_reports")
        if not db_id:
            return []
        effective_limit = int(limit) if isinstance(limit, int) else 20
        if effective_limit == 0:
            effective_limit = -1  # -1 means all
        if effective_limit < -1:
            effective_limit = 20
        page_size = 100 if effective_limit <= 0 else min(effective_limit, 100)
        pages = client.query_database(
            db_id,
            sorts=[{"property": "Date", "direction": "descending"}],
            page_size=page_size,
        )
        selected_pages = pages if effective_limit <= 0 else pages[:effective_limit]
        results = []
        for page in selected_pages:
            props = page.get("properties", {})
            title = _notion_title(props.get("Title", {}))
            date = _notion_date(props.get("Date", {}))
            dimension = _notion_select(props.get("Dimension", {}))
            layer = _notion_select(props.get("Layer", {}))
            insights = _notion_rich_text(props.get("Key Insights", {}))
            page_id = str(page.get("id") or "").strip()

            detail_lines: List[str] = []
            if page_id:
                try:
                    blocks = client.get_blocks(page_id)
                    expanded = _expand_toggle_blocks(client, blocks)
                    items = _extract_blocks_text(expanded)
                    detail_lines = _extract_report_detail_lines(items)
                except Exception:
                    detail_lines = []

            results.append({
                "title": title,
                "date": date,
                "dimension": dimension or "",
                "layer": layer or "",
                "insights": insights,
                "details": detail_lines,
            })
        results.sort(key=report_sort_key)
        if effective_limit > 0:
            return results[:effective_limit]
        return results
    except Exception:
        return []


def _extract_report_detail_lines(items: List[Dict[str, str]]) -> List[str]:
    """Extract detail lines from report page blocks.

    Prefer lines under the "详细洞察" section.
    """
    details: List[str] = []
    in_detail = False

    for item in items:
        btype = str(item.get("type") or "")
        text = str(item.get("text") or "").strip()
        if not text and btype != "divider":
            continue

        if btype.startswith("heading_"):
            if text == "详细洞察":
                in_detail = True
                continue
            if in_detail:
                break

        if not in_detail:
            continue
        if btype == "divider":
            continue
        if text.startswith("证据密度:"):
            break
        if text and text != "暂无可展开的详细洞察。":
            details.append(text)

    return details


# ---------------------------------------------------------------------------
# L3 content fetching from Notion pages
# ---------------------------------------------------------------------------

def _expand_toggle_blocks(client, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recursively expand toggle blocks by fetching their children.

    Toggle titles are converted to heading_3 blocks so they render
    inline in the dashboard.
    """
    expanded: List[Dict[str, Any]] = []
    for b in blocks:
        btype = b.get("type", "")
        if btype == "toggle":
            # Emit toggle title as a heading_3
            texts = b.get("toggle", {}).get("rich_text", [])
            title = "".join(t.get("plain_text", "") for t in texts)
            expanded.append({
                "type": "heading_3",
                "heading_3": {"rich_text": [{"plain_text": title}]},
            })
            # Fetch and expand children
            if b.get("has_children"):
                children = client.get_blocks(b["id"])
                expanded.extend(_expand_toggle_blocks(client, children))
        else:
            expanded.append(b)
    return expanded


def _extract_blocks_text(blocks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Extract structured text from Notion blocks.

    Returns a list of {type, text} dicts for rendering.
    """
    items: List[Dict[str, str]] = []
    for b in blocks:
        btype = b.get("type", "")
        if btype in ("paragraph", "heading_1", "heading_2", "heading_3",
                      "bulleted_list_item", "numbered_list_item",
                      "callout", "quote", "code"):
            texts = b.get(btype, {}).get("rich_text", [])
            content = "".join(t.get("plain_text", "") for t in texts)
            if content.strip():
                items.append({"type": btype, "text": content})
        elif btype == "divider":
            items.append({"type": "divider", "text": ""})
    return items


def _fetch_notion_user_profile(client) -> List[Dict[str, str]]:
    """Fetch User Profile page content from Notion."""
    try:
        page_id = client.pages.get("user_profile")
        if not page_id:
            return []
        blocks = client.get_blocks(page_id)
        return _extract_blocks_text(blocks)
    except Exception:
        return []


def _fetch_notion_coaching(client) -> List[Dict[str, str]]:
    """Fetch the most recent coaching report content."""
    try:
        db_id = client.databases.get("analysis_reports")
        if not db_id:
            return []
        pages = client.query_database(
            db_id,
            filter={"property": "Dimension", "select": {"equals": "coaching"}},
            sorts=[{"property": "Date", "direction": "descending"}],
            page_size=1,
        )
        if not pages:
            return []
        page_id = pages[0]["id"]
        blocks = client.get_blocks(page_id)
        return _extract_blocks_text(blocks)
    except Exception:
        return []


def _fetch_notion_l3_pages(client) -> List[Dict[str, Any]]:
    """Fetch L3 child pages (Templates, Learning Plan, Automation) from root.

    When duplicate pages exist for the same base title, prefer the one
    with more content blocks (newer generated pages are richer).
    """
    try:
        root_id = client.pages.get("root")
        if not root_id:
            return []
        blocks = client.get_blocks(root_id)
        # Collect all candidates per base_title, then pick the richest.
        candidates: Dict[str, List[Dict[str, Any]]] = {}
        target_titles = {"Prompt Templates", "Learning Plan",
                         "Automation Suggestions",
                         "提示词模板", "学习计划", "自动化建议"}
        for b in blocks:
            if b.get("type") == "child_page":
                title = b.get("child_page", {}).get("title", "")
                base_title = title.split(" - ")[0].strip()
                if base_title in target_titles:
                    page_blocks = client.get_blocks(b["id"])
                    page_blocks = _expand_toggle_blocks(client, page_blocks)
                    content = _extract_blocks_text(page_blocks)
                    entry = {
                        "title": title,
                        "base_title": base_title,
                        "content": content,
                    }
                    candidates.setdefault(base_title, []).append(entry)

        # For each title, pick the version with the most content blocks.
        results = []
        for base_title in target_titles:
            pages = candidates.get(base_title, [])
            if pages:
                best = max(pages, key=lambda p: len(p["content"]))
                results.append(best)
        return results
    except Exception:
        return []


# Notion property extraction helpers

def _notion_title(prop: dict) -> str:
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def _notion_rich_text(prop: dict) -> str:
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts)


def _notion_number(prop: dict) -> Optional[float]:
    return prop.get("number")


def _notion_select(prop: dict) -> Optional[str]:
    sel = prop.get("select")
    if sel and isinstance(sel, dict):
        return sel.get("name")
    return None


def _notion_date(prop: dict) -> str:
    d = prop.get("date")
    if d and isinstance(d, dict):
        return d.get("start", "")[:10]
    return ""


# ---------------------------------------------------------------------------
# Local insights loading (from Agent Skill Mode G)
# ---------------------------------------------------------------------------

def _load_local_insights() -> Dict[str, Any]:
    """Load Agent Skill insights from data/insights/latest.json."""
    latest_path = os.path.join(_INSIGHTS_DIR, "latest.json")
    if not os.path.isfile(latest_path):
        return {}
    try:
        with open(latest_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _normalize_local_report_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one local incremental report for dashboard rendering."""
    if not isinstance(item, dict):
        return None

    title = str(item.get("title") or "").strip()
    date = str(item.get("date") or "").strip()
    dimension = str(item.get("dimension") or "").strip()
    layer = str(item.get("layer") or "").strip()
    insights = str(item.get("key_insights") or "").strip()

    if not (title and dimension and layer and insights):
        return None

    details: List[str] = []
    detail_lines = item.get("detail_lines")
    if isinstance(detail_lines, list):
        details = [str(line).strip() for line in detail_lines if str(line or "").strip()]
    if not details:
        detail_text = str(item.get("detail_text") or "").strip()
        if detail_text:
            details = [line.strip() for line in detail_text.splitlines() if line.strip()]

    return {
        "title": title,
        "date": date,
        "dimension": dimension,
        "layer": layer,
        "insights": insights,
        "details": details,
    }


def _load_local_incremental_reports(limit: int = 20) -> List[Dict[str, Any]]:
    """Load reports from the latest local incremental mechanism sidecar."""
    incremental_dir = os.path.join(_INSIGHTS_DIR, "incremental")
    if not os.path.isdir(incremental_dir):
        return []

    files = [
        os.path.join(incremental_dir, name)
        for name in os.listdir(incremental_dir)
        if name.endswith(".json")
    ]
    if not files:
        return []

    latest_file = max(files, key=lambda path: (os.path.getmtime(path), path))
    try:
        with open(latest_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []

    reports = payload.get("reports")
    if not isinstance(reports, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in reports:
        normalized_item = _normalize_local_report_item(item)
        if normalized_item is not None:
            normalized.append(normalized_item)

    normalized.sort(key=report_sort_key)
    if limit > 0:
        return normalized[:limit]
    return normalized


def _load_l3_outputs() -> Dict[str, Any]:
    """Load L3 output files (user_profile.md, best_practices.md, improvement_plan.md)."""
    outputs: Dict[str, Any] = {}

    # User Profile
    profile_path = os.path.join(_OUTPUT_DIR_L3, "user_profile.md")
    if os.path.isfile(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as fh:
                outputs["user_profile_md"] = fh.read()
        except OSError:
            pass

    # User Profile Data (JSON)
    profile_data_path = os.path.join(_OUTPUT_DIR_L3, "user_profile_data.json")
    if os.path.isfile(profile_data_path):
        try:
            with open(profile_data_path, "r", encoding="utf-8") as fh:
                outputs["user_profile_data"] = json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass

    # Best Practices
    practices_path = os.path.join(_OUTPUT_DIR_L3, "best_practices.md")
    if os.path.isfile(practices_path):
        try:
            with open(practices_path, "r", encoding="utf-8") as fh:
                outputs["best_practices_md"] = fh.read()
        except OSError:
            pass

    # Improvement Plan
    plan_path = os.path.join(_OUTPUT_DIR_L3, "improvement_plan.md")
    if os.path.isfile(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as fh:
                outputs["improvement_plan_md"] = fh.read()
        except OSError:
            pass

    return outputs


def _md_to_blocks(md_content: str) -> List[Dict[str, str]]:
    """Convert markdown content to simplified block format for rendering."""
    blocks: List[Dict[str, str]] = []
    lines = md_content.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("# "):
            blocks.append({"type": "heading_1", "text": stripped[2:]})
        elif stripped.startswith("## "):
            blocks.append({"type": "heading_2", "text": stripped[3:]})
        elif stripped.startswith("### "):
            blocks.append({"type": "heading_3", "text": stripped[4:]})
        elif stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
            blocks.append({"type": "bulleted_list_item", "text": stripped[6:]})
        elif stripped.startswith("- **") or stripped.startswith("- "):
            text = stripped[2:] if stripped.startswith("- ") else stripped
            blocks.append({"type": "bulleted_list_item", "text": text})
        elif stripped.startswith("> "):
            blocks.append({"type": "callout", "text": stripped[2:]})
        elif stripped.startswith("---"):
            blocks.append({"type": "divider", "text": ""})
        elif stripped.startswith("```"):
            continue  # Skip code fence markers
        elif stripped.startswith("*") and stripped.endswith("*"):
            blocks.append({"type": "paragraph", "text": stripped.strip("*")})
        else:
            blocks.append({"type": "paragraph", "text": stripped})

    return blocks


# ---------------------------------------------------------------------------
# Data aggregation from local conversations
# ---------------------------------------------------------------------------

def aggregate_local_data(conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate statistics from local conversation JSON files.

    Returns a data dict ready for embedding in the HTML template.
    """
    total_turns = 0
    total_tool_uses = 0

    platform_counts: Counter = Counter()
    model_counts: Counter = Counter()
    language_counts: Counter = Counter()
    domain_counts: Counter = Counter()
    tool_name_counts: Counter = Counter()
    tool_success: Dict[str, List[bool]] = defaultdict(list)
    monthly_counts: Counter = Counter()
    depth_buckets = {"1": 0, "2-5": 0, "6-10": 0, "10+": 0}

    # LLM metadata counters
    task_type_counts: Counter = Counter()
    difficulty_counts: Counter = Counter()
    outcome_counts: Counter = Counter()
    cognitive_pattern_counts: Counter = Counter()
    prompt_quality_buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}

    for conv in conversations:
        source = conv.get("source", "unknown")
        platform_counts[source] += 1

        model = conv.get("model") or "unknown"
        model_counts[model] += 1

        meta = conv.get("metadata", {})
        lang = meta.get("primary_language", "unknown")
        language_counts[lang] += 1

        domains = meta.get("detected_domains", [])
        for d in domains:
            domain_counts[d] += 1

        turns = conv.get("turns", [])
        n_turns = len(turns)
        total_turns += n_turns

        # Depth bucket
        if n_turns == 1:
            depth_buckets["1"] += 1
        elif n_turns <= 5:
            depth_buckets["2-5"] += 1
        elif n_turns <= 10:
            depth_buckets["6-10"] += 1
        else:
            depth_buckets["10+"] += 1

        # Timeline (monthly)
        created = conv.get("created_at", "")[:7]  # "YYYY-MM"
        if created:
            monthly_counts[created] += 1

        # Tool usage
        for turn in turns:
            ar = turn.get("assistant_response", {})
            tool_uses = ar.get("tool_uses", [])
            total_tool_uses += len(tool_uses)
            for tu in tool_uses:
                name = tu.get("tool_name", "unknown")
                tool_name_counts[name] += 1
                success = tu.get("success")
                if success is not None:
                    tool_success[name].append(success)

        # LLM metadata enrichment data
        llm_meta = meta.get("llm_metadata")
        if llm_meta:
            task_type = llm_meta.get("task_type", "other")
            task_type_counts[task_type] += 1

            difficulty = llm_meta.get("difficulty", 1)
            difficulty_counts[str(difficulty)] += 1

            outcome = llm_meta.get("outcome", "unknown")
            outcome_counts[outcome] += 1

            pq = llm_meta.get("prompt_quality", {})
            score = pq.get("score", 0) if isinstance(pq, dict) else 0
            if score <= 20:
                prompt_quality_buckets["0-20"] += 1
            elif score <= 40:
                prompt_quality_buckets["21-40"] += 1
            elif score <= 60:
                prompt_quality_buckets["41-60"] += 1
            elif score <= 80:
                prompt_quality_buckets["61-80"] += 1
            else:
                prompt_quality_buckets["81-100"] += 1

            patterns = llm_meta.get("cognitive_patterns", [])
            for p in patterns:
                if isinstance(p, str):
                    cognitive_pattern_counts[p] += 1
                elif isinstance(p, dict):
                    cognitive_pattern_counts[p.get("pattern", "unknown")] += 1

    # Build tool stats from local data
    local_tool_stats = []
    for name, count in tool_name_counts.most_common():
        successes = tool_success.get(name, [])
        rate = (sum(successes) / len(successes) * 100) if successes else 0.0
        local_tool_stats.append({
            "name": name,
            "usage": count,
            "success_rate": round(rate, 1),
        })

    # Build domain map from local data
    local_domain_map = []
    for name, count in domain_counts.most_common():
        local_domain_map.append({
            "name": name,
            "count": count,
            "depth": 0.0,
            "trend": "stable",
        })

    # Timeline sorted
    timeline = [
        {"month": m, "count": c}
        for m, c in sorted(monthly_counts.items())
    ]

    return {
        "summary": {
            "total_conversations": len(conversations),
            "total_turns": total_turns,
            "total_tool_uses": total_tool_uses,
            "platform_count": len(platform_counts),
            "domain_count": len(domain_counts),
            "report_count": 0,  # Will be updated from Notion
        },
        "platform_distribution": dict(platform_counts.most_common()),
        "timeline": timeline,
        "tool_stats": local_tool_stats,
        "domain_map": local_domain_map,
        "depth_distribution": depth_buckets,
        "language_distribution": dict(language_counts.most_common()),
        "model_distribution": dict(model_counts.most_common()),
        "task_type_distribution": dict(task_type_counts.most_common()),
        "difficulty_distribution": {str(k): difficulty_counts.get(str(k), 0) for k in range(1, 11)},
        "outcome_distribution": dict(outcome_counts.most_common()),
        "prompt_quality_distribution": prompt_quality_buckets,
        "cognitive_pattern_distribution": dict(cognitive_pattern_counts.most_common(15)),
        "recent_reports": [],  # Will be updated from Notion
        "user_profile": [],   # L3: User Profile blocks
        "coaching": [],  # L3: Coaching blocks
        "l3_pages": [],       # L3: Templates, Learning Plan, Automation
        "local_insights": {},  # Agent Skill insights (from data/insights/)
        "l3_outputs": {},     # New L3 outputs (user_profile.md, best_practices.md, etc.)
    }


# ---------------------------------------------------------------------------
# Merge Notion data into aggregated data
# ---------------------------------------------------------------------------

def merge_notion_data(
    data: Dict[str, Any],
    tool_stats: List[Dict[str, Any]],
    domain_map: List[Dict[str, Any]],
    reports: List[Dict[str, Any]],
    *,
    user_profile: Optional[List[Dict[str, str]]] = None,
    coaching: Optional[List[Dict[str, str]]] = None,
    l3_pages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Merge Notion data into the aggregated data dict.

    For Tool Stats and Domain Map, prefer whichever source (local or Notion)
    has more entries -- local data is freshly computed from all JSON files
    while Notion may lag behind.
    """
    if tool_stats and len(tool_stats) >= len(data.get("tool_stats", [])):
        data["tool_stats"] = tool_stats

    if domain_map and len(domain_map) >= len(data.get("domain_map", [])):
        data["domain_map"] = domain_map

    if reports:
        data["recent_reports"] = reports
        data["summary"]["report_count"] = len(reports)

    if user_profile:
        data["user_profile"] = user_profile

    if coaching:
        data["coaching"] = coaching

    if l3_pages:
        data["l3_pages"] = l3_pages

    return data


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>对话洞察仪表盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {
    --bg-primary: #0f1117;
    --bg-card: #1a1d2e;
    --bg-card-hover: #222640;
    --text-primary: #e8eaed;
    --text-secondary: #9aa0a6;
    --text-muted: #5f6368;
    --accent-blue: #4e8cff;
    --accent-green: #34d399;
    --accent-purple: #a78bfa;
    --accent-orange: #fb923c;
    --accent-pink: #f472b6;
    --accent-cyan: #22d3ee;
    --border-color: #2a2d3e;
    --radius: 12px;
    --shadow: 0 4px 24px rgba(0,0,0,0.3);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
                 'Microsoft YaHei', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    min-height: 100vh;
}

.header {
    padding: 32px 40px 20px;
    border-bottom: 1px solid var(--border-color);
    background: linear-gradient(135deg, #0f1117 0%, #1a1d2e 100%);
}

.header h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
}

.header .subtitle {
    color: var(--text-secondary);
    font-size: 14px;
    margin-top: 4px;
}

.container {
    max-width: 1440px;
    margin: 0 auto;
    padding: 24px 40px 60px;
}

/* Stat cards row */
.stat-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
}

.stat-card {
    background: var(--bg-card);
    border-radius: var(--radius);
    padding: 20px 24px;
    border: 1px solid var(--border-color);
    transition: background 0.2s, transform 0.2s;
}

.stat-card:hover {
    background: var(--bg-card-hover);
    transform: translateY(-2px);
}

.stat-card .label {
    font-size: 12px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
}

.stat-card .value {
    font-size: 32px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.stat-card:nth-child(1) .value { color: var(--accent-blue); }
.stat-card:nth-child(2) .value { color: var(--accent-green); }
.stat-card:nth-child(3) .value { color: var(--accent-purple); }
.stat-card:nth-child(4) .value { color: var(--accent-orange); }
.stat-card:nth-child(5) .value { color: var(--accent-pink); }
.stat-card:nth-child(6) .value { color: var(--accent-cyan); }

/* Chart grid */
.chart-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
    margin-bottom: 28px;
}

@media (max-width: 1024px) {
    .chart-grid { grid-template-columns: 1fr; }
    .container { padding: 16px 20px 40px; }
    .header { padding: 24px 20px 16px; }
}

.chart-card {
    background: var(--bg-card);
    border-radius: var(--radius);
    padding: 24px;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow);
    min-width: 0;
    overflow: hidden;
}

.chart-card h3 {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 16px;
    color: var(--text-primary);
}

.chart-wrapper {
    position: relative;
    width: 100%;
    height: 300px;
}

.chart-card.wide {
    grid-column: span 2;
}

@media (max-width: 1024px) {
    .chart-card.wide { grid-column: span 1; }
}

/* Reports table */
.reports-section {
    background: var(--bg-card);
    border-radius: var(--radius);
    padding: 24px;
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow);
}

.reports-section h3 {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 16px;
}

.reports-table {
    width: 100%;
    border-collapse: collapse;
}

.reports-table th {
    text-align: left;
    font-size: 11px;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
}

.reports-table td {
    padding: 10px 12px;
    font-size: 13px;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-primary);
}

.reports-table tr:hover td {
    background: var(--bg-card-hover);
}

.report-summary {
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.6;
}

.report-details {
    margin-top: 8px;
}

.report-details > summary {
    cursor: pointer;
    color: var(--accent-cyan);
    font-size: 12px;
    user-select: none;
}

.report-details ul {
    margin: 8px 0 0 18px;
    padding: 0;
}

.report-details li {
    margin: 4px 0;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;
}

.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

.badge-l1 { background: rgba(78,140,255,0.2); color: var(--accent-blue); }
.badge-l2 { background: rgba(167,139,250,0.2); color: var(--accent-purple); }
.badge-l3 { background: rgba(52,211,153,0.2); color: var(--accent-green); }

.empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
    font-size: 14px;
}

/* L3 Prescriptive Section */
.l3-section {
    margin-top: 28px;
}

.l3-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--accent-green);
    display: inline-block;
}

.l3-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
    margin-bottom: 20px;
}

@media (max-width: 1024px) {
    .l3-grid { grid-template-columns: 1fr; }
}

.l3-card {
    background: var(--bg-card);
    border-radius: var(--radius);
    padding: 24px;
    border: 1px solid var(--border-color);
    border-left: 3px solid var(--accent-green);
    box-shadow: var(--shadow);
    min-width: 0;
    overflow: hidden;
    /* no height limit – show full content */
}

.l3-card h3 {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 16px;
    color: var(--accent-green);
}

.l3-card .block-h1 {
    font-size: 16px;
    font-weight: 700;
    margin: 16px 0 8px;
    color: var(--text-primary);
}

.l3-card .block-h2 {
    font-size: 14px;
    font-weight: 600;
    margin: 14px 0 6px;
    color: var(--accent-purple);
}

.l3-card .block-p {
    font-size: 13px;
    color: var(--text-secondary);
    margin: 4px 0;
    line-height: 1.6;
}

.l3-card .block-li {
    font-size: 13px;
    color: var(--text-secondary);
    margin: 3px 0;
    padding-left: 16px;
    position: relative;
    line-height: 1.6;
}

.l3-card .block-li::before {
    content: '';
    position: absolute;
    left: 4px;
    top: 8px;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--accent-green);
}

.l3-card .block-li.numbered {
    padding-left: 24px;
    counter-increment: li-counter;
}

.l3-card .block-li.numbered::before {
    content: counter(li-counter) '.';
    background: none;
    font-size: 12px;
    font-weight: 600;
    color: var(--accent-green);
    top: 0;
    left: 0;
    width: auto;
    height: auto;
    border-radius: 0;
}

.l3-card .block-callout {
    font-size: 12px;
    color: var(--text-muted);
    background: rgba(52, 211, 153, 0.08);
    padding: 8px 12px;
    border-radius: 6px;
    margin: 6px 0;
    border-left: 3px solid var(--accent-green);
}

.l3-card .block-divider {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 12px 0;
}

.l3-card .block-quote {
    font-size: 13px;
    color: var(--text-secondary);
    border-left: 3px solid var(--accent-purple);
    padding-left: 12px;
    margin: 8px 0;
    font-style: italic;
}

.footer {
    text-align: center;
    padding: 24px;
    color: var(--text-muted);
    font-size: 12px;
}
</style>
</head>
<body>

<div class="header">
    <h1>对话洞察仪表盘</h1>
    <div class="subtitle">
        数据来源：本地 JSON %%NOTION_STATUS%% &nbsp;|&nbsp;
        生成时间：%%GENERATED_AT%%
    </div>
</div>

<div class="container">
    <!-- Stat Cards -->
    <div class="stat-cards">
        <div class="stat-card">
            <div class="label">对话总数</div>
            <div class="value" id="stat-conversations">-</div>
        </div>
        <div class="stat-card">
            <div class="label">总轮次</div>
            <div class="value" id="stat-turns">-</div>
        </div>
        <div class="stat-card">
            <div class="label">工具调用</div>
            <div class="value" id="stat-tools">-</div>
        </div>
        <div class="stat-card">
            <div class="label">平台数</div>
            <div class="value" id="stat-platforms">-</div>
        </div>
        <div class="stat-card">
            <div class="label">领域数</div>
            <div class="value" id="stat-domains">-</div>
        </div>
        <div class="stat-card">
            <div class="label">分析报告</div>
            <div class="value" id="stat-reports">-</div>
        </div>
    </div>

    <!-- Charts Grid -->
    <div class="chart-grid">
        <!-- 1. Platform Distribution (Pie) -->
        <div class="chart-card">
            <h3>平台分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-platform"></canvas>
            </div>
        </div>

        <!-- 2. Language Distribution (Doughnut) -->
        <div class="chart-card">
            <h3>语言分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-language"></canvas>
            </div>
        </div>

        <!-- 3. Timeline (Line) — wide -->
        <div class="chart-card wide">
            <h3>对话时间线（按月）</h3>
            <div class="chart-wrapper">
                <canvas id="chart-timeline"></canvas>
            </div>
        </div>

        <!-- 4. Tool Usage (Horizontal Bar) -->
        <div class="chart-card">
            <h3>工具使用排行</h3>
            <div class="chart-wrapper">
                <canvas id="chart-tools"></canvas>
            </div>
        </div>

        <!-- 5. Domain Map (Radar) -->
        <div class="chart-card">
            <h3>知识领域分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-domains"></canvas>
            </div>
        </div>

        <!-- 6. Depth Distribution (Bar) -->
        <div class="chart-card">
            <h3>对话深度分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-depth"></canvas>
            </div>
        </div>

        <!-- 7. Model Distribution (Bar) -->
        <div class="chart-card">
            <h3>模型使用分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-models"></canvas>
            </div>
        </div>

        <!-- 8. Task Type Distribution (Horizontal Bar) -->
        <div class="chart-card">
            <h3>任务类型分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-task-type"></canvas>
            </div>
        </div>

        <!-- 9. Difficulty Distribution (Bar) -->
        <div class="chart-card">
            <h3>对话难度分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-difficulty"></canvas>
            </div>
        </div>

        <!-- 10. Prompt Quality Distribution (Bar) -->
        <div class="chart-card">
            <h3>提示词质量评分分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-prompt-quality"></canvas>
            </div>
        </div>

        <!-- 11. Outcome Distribution (Pie) -->
        <div class="chart-card">
            <h3>对话结果分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-outcome"></canvas>
            </div>
        </div>

        <!-- 12. Cognitive Patterns (Horizontal Bar) — wide -->
        <div class="chart-card wide">
            <h3>认知模式分布</h3>
            <div class="chart-wrapper">
                <canvas id="chart-cognitive"></canvas>
            </div>
        </div>
    </div>

    <!-- 8. Recent Reports Table -->
    <div class="reports-section">
        <h3>分析报告</h3>
        <div id="reports-content"></div>
    </div>

    <!-- L3 Prescriptive Section -->
    <div class="l3-section">
        <h2 class="l3-title">L3 处方层 — 改进建议与行动方向</h2>

        <!-- Improvement Directions (from Agent Skill insights) -->
        <div class="l3-grid" id="l3-insights-grid"></div>

        <div class="l3-grid">
            <!-- User Profile -->
            <div class="l3-card">
                <h3>用户画像</h3>
                <div id="l3-profile"></div>
            </div>

            <!-- Coaching -->
            <div class="l3-card">
                <h3>辅导建议</h3>
                <div id="l3-coaching"></div>
            </div>
        </div>

        <!-- L3 sub-pages (Templates, Learning Plan, Automation) -->
        <div class="l3-grid" id="l3-pages-grid"></div>
    </div>
</div>

<div class="footer">
    Conversation Insights Dashboard &mdash; 自动生成
</div>

<script>
// Embedded data
const DATA = %%DATA_JSON%%;

// ---- Helpers ----
function formatNumber(n) {
    if (n >= 10000) return (n / 1000).toFixed(1) + 'k';
    return n.toLocaleString('zh-CN');
}

const COLORS = {
    blue:   '#4e8cff',
    green:  '#34d399',
    purple: '#a78bfa',
    orange: '#fb923c',
    pink:   '#f472b6',
    cyan:   '#22d3ee',
    yellow: '#fbbf24',
    red:    '#f87171',
    indigo: '#818cf8',
    teal:   '#2dd4bf',
    lime:   '#a3e635',
    rose:   '#fb7185',
};

const PALETTE = Object.values(COLORS);
const PALETTE_ALPHA = PALETTE.map(c => c + '33');

const chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            labels: { color: '#9aa0a6', font: { size: 12 } }
        }
    }
};

Chart.defaults.color = '#9aa0a6';
Chart.defaults.borderColor = '#2a2d3e';

// ---- Stat Cards ----
document.getElementById('stat-conversations').textContent = formatNumber(DATA.summary.total_conversations);
document.getElementById('stat-turns').textContent = formatNumber(DATA.summary.total_turns);
document.getElementById('stat-tools').textContent = formatNumber(DATA.summary.total_tool_uses);
document.getElementById('stat-platforms').textContent = DATA.summary.platform_count;
document.getElementById('stat-domains').textContent = DATA.summary.domain_count;
document.getElementById('stat-reports').textContent = DATA.summary.report_count;

// ---- 1. Platform Distribution (Pie) ----
(() => {
    const labels = Object.keys(DATA.platform_distribution);
    const values = Object.values(DATA.platform_distribution);
    new Chart(document.getElementById('chart-platform'), {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: PALETTE.slice(0, labels.length),
                borderWidth: 0,
            }]
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                legend: { position: 'right', labels: { color: '#9aa0a6', padding: 12, font: { size: 12 } } },
            }
        }
    });
})();

// ---- 2. Language Distribution (Doughnut) ----
(() => {
    const labels = Object.keys(DATA.language_distribution);
    const values = Object.values(DATA.language_distribution);
    new Chart(document.getElementById('chart-language'), {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: [COLORS.blue, COLORS.orange, COLORS.purple, ...PALETTE.slice(3)],
                borderWidth: 0,
                cutout: '55%',
            }]
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                legend: { position: 'right', labels: { color: '#9aa0a6', padding: 12, font: { size: 12 } } },
            }
        }
    });
})();

// ---- 3. Timeline (Line) ----
(() => {
    const labels = DATA.timeline.map(d => d.month);
    const values = DATA.timeline.map(d => d.count);
    new Chart(document.getElementById('chart-timeline'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '对话数',
                data: values,
                borderColor: COLORS.blue,
                backgroundColor: COLORS.blue + '20',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: COLORS.blue,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6', maxRotation: 45 } },
                y: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true }
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: false }
            }
        }
    });
})();

// ---- 4. Tool Usage (Horizontal Bar) ----
(() => {
    const top = DATA.tool_stats.slice(0, 15);
    const labels = top.map(d => d.name);
    const values = top.map(d => d.usage);
    new Chart(document.getElementById('chart-tools'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '调用次数',
                data: values,
                backgroundColor: COLORS.purple + 'aa',
                borderColor: COLORS.purple,
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            indexAxis: 'y',
            scales: {
                x: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true },
                y: { grid: { display: false }, ticks: { color: '#9aa0a6', font: { size: 11 } } }
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: false }
            }
        }
    });
})();

// ---- 5. Domain Map (Radar) ----
(() => {
    const top = DATA.domain_map.slice(0, 10);
    const labels = top.map(d => d.name);
    const values = top.map(d => d.count);
    new Chart(document.getElementById('chart-domains'), {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                label: '对话数',
                data: values,
                borderColor: COLORS.cyan,
                backgroundColor: COLORS.cyan + '30',
                pointBackgroundColor: COLORS.cyan,
                pointBorderColor: COLORS.cyan,
                pointRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                r: {
                    grid: { color: '#2a2d3e' },
                    angleLines: { color: '#2a2d3e' },
                    pointLabels: { color: '#9aa0a6', font: { size: 11 } },
                    ticks: { display: false },
                    beginAtZero: true,
                }
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: false }
            }
        }
    });
})();

// ---- 6. Depth Distribution (Bar) ----
(() => {
    const labels = Object.keys(DATA.depth_distribution);
    const values = Object.values(DATA.depth_distribution);
    new Chart(document.getElementById('chart-depth'), {
        type: 'bar',
        data: {
            labels: labels.map(l => l + ' 轮'),
            datasets: [{
                label: '对话数',
                data: values,
                backgroundColor: [COLORS.green + 'cc', COLORS.blue + 'cc', COLORS.orange + 'cc', COLORS.pink + 'cc'],
                borderWidth: 0,
                borderRadius: 6,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: { grid: { display: false }, ticks: { color: '#9aa0a6' } },
                y: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true }
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: false }
            }
        }
    });
})();

// ---- 7. Model Distribution (Bar) ----
(() => {
    // Sort by count, take top 12
    const entries = Object.entries(DATA.model_distribution)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12);
    const labels = entries.map(e => e[0]);
    const values = entries.map(e => e[1]);
    new Chart(document.getElementById('chart-models'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '对话数',
                data: values,
                backgroundColor: PALETTE.slice(0, labels.length).map(c => c + 'cc'),
                borderWidth: 0,
                borderRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: { grid: { display: false }, ticks: { color: '#9aa0a6', maxRotation: 45, font: { size: 10 } } },
                y: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true }
            },
            plugins: {
                ...chartDefaults.plugins,
                legend: { display: false }
            }
        }
    });
})();

// ---- 8. Task Type Distribution (Horizontal Bar) ----
(() => {
    const entries = Object.entries(DATA.task_type_distribution || {})
        .sort((a, b) => b[1] - a[1]);
    const labels = entries.map(e => e[0]);
    const values = entries.map(e => e[1]);
    new Chart(document.getElementById('chart-task-type'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '对话数',
                data: values,
                backgroundColor: COLORS.orange + 'aa',
                borderColor: COLORS.orange,
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            indexAxis: 'y',
            scales: {
                x: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true },
                y: { grid: { display: false }, ticks: { color: '#9aa0a6', font: { size: 11 } } }
            },
            plugins: { ...chartDefaults.plugins, legend: { display: false } }
        }
    });
})();

// ---- 9. Difficulty Distribution (Bar) ----
(() => {
    const labels = Object.keys(DATA.difficulty_distribution || {});
    const values = Object.values(DATA.difficulty_distribution || {});
    const bgColors = labels.map(l => {
        const v = parseInt(l);
        if (v <= 2) return COLORS.green + 'cc';
        if (v <= 4) return COLORS.blue + 'cc';
        if (v <= 6) return COLORS.orange + 'cc';
        if (v <= 8) return COLORS.pink + 'cc';
        return COLORS.red + 'cc';
    });
    new Chart(document.getElementById('chart-difficulty'), {
        type: 'bar',
        data: {
            labels: labels.map(l => '难度 ' + l),
            datasets: [{
                label: '对话数',
                data: values,
                backgroundColor: bgColors,
                borderWidth: 0,
                borderRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: { grid: { display: false }, ticks: { color: '#9aa0a6' } },
                y: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true }
            },
            plugins: { ...chartDefaults.plugins, legend: { display: false } }
        }
    });
})();

// ---- 10. Prompt Quality Distribution (Bar) ----
(() => {
    const labels = Object.keys(DATA.prompt_quality_distribution || {});
    const values = Object.values(DATA.prompt_quality_distribution || {});
    const bgColors = [COLORS.red + 'cc', COLORS.orange + 'cc', COLORS.yellow + 'cc', COLORS.blue + 'cc', COLORS.green + 'cc'];
    new Chart(document.getElementById('chart-prompt-quality'), {
        type: 'bar',
        data: {
            labels: labels.map(l => l + ' 分'),
            datasets: [{
                label: '对话数',
                data: values,
                backgroundColor: bgColors,
                borderWidth: 0,
                borderRadius: 6,
            }]
        },
        options: {
            ...chartDefaults,
            scales: {
                x: { grid: { display: false }, ticks: { color: '#9aa0a6' } },
                y: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true }
            },
            plugins: { ...chartDefaults.plugins, legend: { display: false } }
        }
    });
})();

// ---- 11. Outcome Distribution (Pie) ----
(() => {
    const labels = Object.keys(DATA.outcome_distribution || {});
    const values = Object.values(DATA.outcome_distribution || {});
    const colorMap = { resolved: COLORS.green, partial: COLORS.orange, abandoned: COLORS.red, exploratory: COLORS.purple };
    const bgColors = labels.map(l => colorMap[l] || COLORS.blue);
    new Chart(document.getElementById('chart-outcome'), {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: bgColors,
                borderWidth: 0,
            }]
        },
        options: {
            ...chartDefaults,
            plugins: {
                ...chartDefaults.plugins,
                legend: { position: 'right', labels: { color: '#9aa0a6', padding: 12, font: { size: 12 } } },
            }
        }
    });
})();

// ---- 12. Cognitive Patterns (Horizontal Bar) ----
(() => {
    const entries = Object.entries(DATA.cognitive_pattern_distribution || {})
        .sort((a, b) => b[1] - a[1]);
    const labels = entries.map(e => e[0]);
    const values = entries.map(e => e[1]);
    new Chart(document.getElementById('chart-cognitive'), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '出现次数',
                data: values,
                backgroundColor: COLORS.cyan + 'aa',
                borderColor: COLORS.cyan,
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            ...chartDefaults,
            indexAxis: 'y',
            scales: {
                x: { grid: { color: '#1f2234' }, ticks: { color: '#9aa0a6' }, beginAtZero: true },
                y: { grid: { display: false }, ticks: { color: '#9aa0a6', font: { size: 11 } } }
            },
            plugins: { ...chartDefaults.plugins, legend: { display: false } }
        }
    });
})();

// ---- Reports Table ----
(() => {
    const container = document.getElementById('reports-content');
    const reports = DATA.recent_reports;

    if (!reports || reports.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无分析报告数据（请先运行 pipeline）</div>';
        return;
    }

    let html = '<table class="reports-table"><thead><tr>';
    html += '<th>标题</th><th>日期</th><th>维度</th><th>关键洞察</th>';
    html += '</tr></thead><tbody>';

    reports.forEach(r => {
        const dim = r.dimension || '';
        const layer = (r.layer || '').toUpperCase();
        let badgeClass = 'badge-l1';
        if (layer === 'L2') badgeClass = 'badge-l2';
        else if (layer === 'L3') badgeClass = 'badge-l3';
        const badgeLabel = layer ? (layer + ' / ' + dim) : dim;

        const insights = r.insights || '';
        const details = Array.isArray(r.details) ? r.details : [];
        const detailsHtml = details.length > 0
            ? `<details class="report-details"><summary>查看详细洞察（${details.length} 条）</summary><ul>${details.map(d => `<li>${escapeHtml(d)}</li>`).join('')}</ul></details>`
            : '';

        html += '<tr>';
        html += `<td>${escapeHtml(r.title)}</td>`;
        html += `<td style="white-space:nowrap">${escapeHtml(r.date)}</td>`;
        html += `<td><span class="badge ${badgeClass}">${escapeHtml(badgeLabel)}</span></td>`;
        html += `<td><div class="report-summary">${escapeHtml(insights)}</div>${detailsHtml}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;
})();

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- L3 Block Renderer ----
function renderBlocks(blocks, containerId) {
    const container = document.getElementById(containerId);
    if (!blocks || blocks.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无数据（需连接 Notion 并运行 L3 生成器）</div>';
        return;
    }

    let html = '';
    let numberedCounter = 0;
    blocks.forEach(b => {
        const text = escapeHtml(b.text || '');
        switch (b.type) {
            case 'heading_1':
                html += `<div class="block-h1">${text}</div>`;
                numberedCounter = 0;
                break;
            case 'heading_2':
            case 'heading_3':
                html += `<div class="block-h2">${text}</div>`;
                numberedCounter = 0;
                break;
            case 'paragraph':
                html += `<div class="block-p">${text}</div>`;
                break;
            case 'bulleted_list_item':
                html += `<div class="block-li">${text}</div>`;
                break;
            case 'numbered_list_item':
                numberedCounter++;
                html += `<div class="block-li numbered" style="counter-reset:li-counter ${numberedCounter - 1}">${text}</div>`;
                break;
            case 'callout':
                html += `<div class="block-callout">${text}</div>`;
                break;
            case 'quote':
                html += `<div class="block-quote">${text}</div>`;
                break;
            case 'divider':
                html += '<hr class="block-divider">';
                numberedCounter = 0;
                break;
            default:
                if (text) html += `<div class="block-p">${text}</div>`;
        }
    });
    container.innerHTML = html;
}

// ---- Render L3 Panels ----
renderBlocks(DATA.user_profile, 'l3-profile');
renderBlocks(DATA.coaching, 'l3-coaching');

// Render L3 sub-pages (Templates, Learning Plan, Automation)
(() => {
    const grid = document.getElementById('l3-pages-grid');
    const pages = DATA.l3_pages || [];

    if (pages.length === 0) return;

    const titleMap = {
        'Prompt Templates': '提示词反模式诊断',
        '提示词模板': '提示词反模式诊断',
        'Learning Plan': '学习计划',
        '学习计划': '学习计划',
        'Automation Suggestions': '自动化建议',
        '自动化建议': '自动化建议',
    };

    pages.forEach((p, i) => {
        const card = document.createElement('div');
        card.className = 'l3-card';
        const zhTitle = titleMap[p.base_title] || p.title;
        card.innerHTML = `<h3>${escapeHtml(zhTitle)}</h3><div id="l3-page-${i}"></div>`;
        grid.appendChild(card);
        // Render after appending to DOM
        renderBlocks(p.content, `l3-page-${i}`);
    });
})();

// ---- Render Local Insights (from Agent Skill Mode G) ----
(() => {
    const grid = document.getElementById('l3-insights-grid');
    const insights = DATA.local_insights || {};
    if (!insights.prompt_antipatterns && !insights.unresolved_concepts && !insights.improvement_directions) return;

    // Improvement Directions card
    const directions = insights.improvement_directions || [];
    if (directions.length > 0) {
        const card = document.createElement('div');
        card.className = 'l3-card';
        let html = '<h3>改进方向</h3>';
        directions.forEach(d => {
            const area = escapeHtml(d.area || '');
            const current = escapeHtml(d.current_pattern || '');
            const target = escapeHtml(d.target_pattern || '');
            const impact = escapeHtml(d.impact || '');
            html += `<div class="block-h2">${area}</div>`;
            if (current) html += `<div class="block-p">当前模式：${current}</div>`;
            if (target) html += `<div class="block-p">目标模式：${target}</div>`;
            if (impact) html += `<div class="block-callout">预期效果：${impact}</div>`;
        });
        card.innerHTML = html;
        grid.appendChild(card);
    }

    // Unresolved Concepts card
    const concepts = insights.unresolved_concepts || [];
    if (concepts.length > 0) {
        const card = document.createElement('div');
        card.className = 'l3-card';
        let html = '<h3>未掌握概念</h3>';
        concepts.forEach(c => {
            const name = escapeHtml(c.concept || '');
            const analysis = escapeHtml(c.analysis || '');
            const recommendation = escapeHtml(c.recommendation || '');
            html += `<div class="block-li">「${name}」`;
            if (analysis) html += ` — ${analysis}`;
            html += '</div>';
            if (recommendation) html += `<div class="block-callout">建议：${recommendation}</div>`;
        });
        card.innerHTML = html;
        grid.appendChild(card);
    }

    // Prompt Anti-patterns card
    const antipatterns = insights.prompt_antipatterns || [];
    if (antipatterns.length > 0) {
        const card = document.createElement('div');
        card.className = 'l3-card';
        card.style.gridColumn = 'span 2';
        let html = '<h3>提示词反模式分析</h3>';
        const total = antipatterns.reduce((s, a) => s + (a.frequency || 0), 0);
        html += `<div class="block-p">共检测到 ${antipatterns.length} 种反模式（${total} 个实例）</div>`;
        antipatterns.forEach(ap => {
            const name = escapeHtml(ap.pattern_name || '');
            const freq = ap.frequency || 0;
            const desc = escapeHtml(ap.description || '');
            html += `<div class="block-h2">${name}（${freq} 次）</div>`;
            if (desc) html += `<div class="block-p">${desc}</div>`;
        });
        card.innerHTML = html;
        grid.appendChild(card);
    }
})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Generate HTML
# ---------------------------------------------------------------------------

def generate_html(data: Dict[str, Any], notion_connected: bool) -> str:
    """Generate the complete HTML dashboard from aggregated data."""
    data_json = json.dumps(data, ensure_ascii=False, indent=None)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    notion_status = "+ Notion" if notion_connected else "（离线模式）"

    html = _HTML_TEMPLATE
    html = html.replace("%%DATA_JSON%%", data_json)
    html = html.replace("%%GENERATED_AT%%", now)
    html = html.replace("%%NOTION_STATUS%%", notion_status)

    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成对话洞察可视化仪表盘（静态 HTML）"
    )
    parser.add_argument(
        "-o", "--output",
        default=_DEFAULT_OUTPUT,
        help=f"输出文件路径（默认：{_DEFAULT_OUTPUT}）",
    )
    parser.add_argument(
        "--no-notion",
        action="store_true",
        help="跳过 Notion 数据获取，仅使用本地 JSON",
    )
    parser.add_argument(
        "--report-limit",
        type=int,
        default=50,
        help="报告条目上限（默认 50，0 表示不限）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    print("=" * 60)
    print("  对话洞察可视化仪表盘生成器")
    print("=" * 60)
    print()

    # Step 1: Load local conversations
    print("  [1/4] 加载本地对话数据...")
    conversations = load_conversations()
    print(f"         已加载 {len(conversations)} 个对话")

    if not conversations:
        print("\n  错误：未找到本地对话数据。", file=sys.stderr)
        print("  请先运行导入脚本将对话导入到 data/conversations/ 目录。")
        return 1

    # Step 2: Aggregate local data
    print("  [2/4] 聚合统计数据...")
    data = aggregate_local_data(conversations)
    print(f"         平台 {data['summary']['platform_count']} 个 | "
          f"领域 {data['summary']['domain_count']} 个 | "
          f"工具 {len(data['tool_stats'])} 种")

    # Load local Agent Skill insights
    local_insights = _load_local_insights()
    if local_insights:
        data["local_insights"] = local_insights
        meta = local_insights.get("_meta", {})
        print(f"         Agent Skill 分析：已加载（{meta.get('generated_at', '日期未知')[:10]}）")
    else:
        print("         Agent Skill 分析：未找到（可选，运行 Mode G 后可用）")

    # Load local incremental reports (latest sidecar)
    local_reports = _load_local_incremental_reports(limit=args.report_limit)
    if local_reports:
        data["recent_reports"] = local_reports
        data["summary"]["report_count"] = len(local_reports)
        print(f"         本地机制报告：已加载 {len(local_reports)} 条（latest incremental）")
    else:
        print("         本地机制报告：未找到（可先运行 pipeline 生成 incremental）")

    # Load new L3 outputs (from output/ directory)
    l3_outputs = _load_l3_outputs()
    if l3_outputs:
        data["l3_outputs"] = l3_outputs
        loaded_files = []
        if "user_profile_md" in l3_outputs:
            loaded_files.append("用户画像")
            # Convert to blocks for rendering
            data["user_profile"] = _md_to_blocks(l3_outputs["user_profile_md"])
        if "best_practices_md" in l3_outputs:
            loaded_files.append("最佳实践")
        if "improvement_plan_md" in l3_outputs:
            loaded_files.append("改进计划")
        if loaded_files:
            print(f"         L3 输出文件：{', '.join(loaded_files)}")
    else:
        print("         L3 输出文件：未找到（可选，由独立 L3 产出流程生成）")

    # Step 3: Fetch Notion data (optional)
    notion_connected = False
    if not args.no_notion:
        print("  [3/4] 获取 Notion 补充数据...")
        client = _load_notion_client()
        if client:
            tool_stats = _fetch_notion_tool_stats(client)
            domain_map = _fetch_notion_domain_map(client)
            reports = _fetch_notion_reports(client, limit=args.report_limit)

            # L3 content
            print("         获取 L3 处方层内容...")
            user_profile = _fetch_notion_user_profile(client)
            coaching = _fetch_notion_coaching(client)
            l3_pages = _fetch_notion_l3_pages(client)

            if tool_stats or domain_map or reports:
                notion_connected = True
            data = merge_notion_data(
                data, tool_stats, domain_map, reports,
                user_profile=user_profile,
                coaching=coaching,
                l3_pages=l3_pages,
            )
            print(f"         Tool Stats: {len(tool_stats)} 条 | "
                  f"Domain Map: {len(domain_map)} 条 | "
                  f"Reports: {len(reports)} 条")
            print(f"         User Profile: {len(user_profile)} 块 | "
                  f"Coaching: {len(coaching)} 块 | "
                  f"L3 Pages: {len(l3_pages)} 个")
            if tool_stats or domain_map or reports or user_profile:
                notion_connected = True
        else:
            print("         无法连接 Notion，使用本地数据")
    else:
        print("  [3/4] 跳过 Notion（--no-notion）")

    # Step 4: Generate HTML
    print("  [4/4] 生成 HTML 仪表盘...")
    html = generate_html(data, notion_connected)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"         输出：{args.output} ({size_kb:.1f} KB)")

    print()
    print("=" * 60)
    print("  仪表盘已生成！")
    print(f"  用浏览器打开查看：open {args.output}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
