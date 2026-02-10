#!/usr/bin/env python3
"""
Sync local conversation statistics to Notion Tool Stats and Domain Map databases.

Reads aggregated data from local JSON conversations and writes/updates
corresponding entries in Notion databases.

Usage:
    python scripts/sync_notion_stats.py              # Full sync (clear and rewrite)
    python scripts/sync_notion_stats.py --dry-run    # Preview without writing
    python scripts/sync_notion_stats.py --append     # Append/update without clearing

This script bridges the gap between local-first analysis and Notion visualization.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from local_loader import load_conversations
from notion_client import NotionClient

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))


# ---------------------------------------------------------------------------
# Statistics aggregation (mirrors dashboard.py logic)
# ---------------------------------------------------------------------------

def aggregate_tool_stats(conversations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate tool usage statistics from conversations.

    Returns:
        List of tool stat dicts with keys: name, usage, success_rate
    """
    tool_name_counts: Counter = Counter()
    tool_success: Dict[str, List[bool]] = defaultdict(list)

    for conv in conversations:
        turns = conv.get("turns", [])
        for turn in turns:
            ar = turn.get("assistant_response", {})
            tool_uses = ar.get("tool_uses", [])
            for tu in tool_uses:
                name = tu.get("tool_name", "unknown")
                tool_name_counts[name] += 1
                success = tu.get("success")
                if success is not None:
                    tool_success[name].append(success)

    results = []
    for name, count in tool_name_counts.most_common():
        successes = tool_success.get(name, [])
        rate = (sum(successes) / len(successes) * 100) if successes else 0.0
        results.append({
            "name": name,
            "usage": count,
            "success_rate": round(rate, 1),
        })

    return results


def aggregate_domain_stats(conversations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate domain/knowledge area statistics from conversations.

    Returns:
        List of domain stat dicts with keys: name, count, depth, trend, category
    """
    domain_counts: Counter = Counter()
    domain_last_seen: Dict[str, str] = {}

    # For trend detection, track monthly counts
    domain_monthly: Dict[str, Counter] = defaultdict(Counter)

    for conv in conversations:
        meta = conv.get("metadata", {})
        created = conv.get("created_at", "")[:7]  # YYYY-MM

        # Try llm_metadata.actual_domains first, fallback to detected_domains
        llm_meta = meta.get("llm_metadata", {})
        domains = llm_meta.get("actual_domains", []) if llm_meta else []
        if not domains:
            domains = meta.get("detected_domains", [])

        for d in domains:
            domain_counts[d] += 1
            if created:
                domain_monthly[d][created] += 1
                # Track most recent appearance
                if d not in domain_last_seen or created > domain_last_seen[d]:
                    domain_last_seen[d] = created

    # Calculate depth score: log2(count + 1) * 2, capped at 10
    import math

    def depth_score(count: int) -> float:
        return min(10.0, round(math.log2(count + 1) * 2, 1))

    # Determine trend based on recent vs older activity
    def calc_trend(monthly: Counter) -> str:
        if not monthly:
            return "stable"
        months = sorted(monthly.keys())
        if len(months) == 1:
            return "new"
        # Compare last 2 months vs earlier
        recent = sum(monthly[m] for m in months[-2:])
        older = sum(monthly[m] for m in months[:-2]) if len(months) > 2 else 0
        if older == 0:
            return "new" if recent > 0 else "stable"
        ratio = recent / max(older, 1)
        if ratio > 1.5:
            return "growing"
        elif ratio < 0.5:
            return "declining"
        return "stable"

    # Categorize domains
    def categorize(domain: str) -> str:
        domain_lower = domain.lower()
        if any(k in domain_lower for k in ["react", "vue", "angular", "css", "html", "frontend", "ui"]):
            return "frontend"
        if any(k in domain_lower for k in ["api", "backend", "server", "database", "sql", "mongo"]):
            return "backend"
        if any(k in domain_lower for k in ["docker", "k8s", "kubernetes", "ci", "cd", "deploy", "infra"]):
            return "devops"
        if any(k in domain_lower for k in ["test", "jest", "pytest", "spec"]):
            return "testing"
        if any(k in domain_lower for k in ["ml", "ai", "model", "llm", "nlp", "data"]):
            return "ai-ml"
        if any(k in domain_lower for k in ["security", "auth", "crypto", "ssl"]):
            return "security"
        if any(k in domain_lower for k in ["doc", "readme", "markdown"]):
            return "documentation"
        if any(k in domain_lower for k in ["legal", "compliance", "tax", "uae"]):
            return "legal"
        return "other"

    results = []
    for name, count in domain_counts.most_common():
        trend = calc_trend(domain_monthly.get(name, Counter()))
        results.append({
            "name": name,
            "count": count,
            "depth": depth_score(count),
            "trend": trend,
            "category": categorize(name),
            "last_seen": domain_last_seen.get(name, ""),
            "gap_indicator": depth_score(count) < 3.0,
        })

    return results


# ---------------------------------------------------------------------------
# Notion sync functions
# ---------------------------------------------------------------------------

def clear_database(client: NotionClient, db_id: str, db_name: str) -> int:
    """Delete all pages in a database. Returns count of deleted pages."""
    print(f"  Clearing {db_name}...")
    pages = client.query_database(db_id)
    for page in pages:
        client._request("DELETE", f"/blocks/{page['id']}")
    return len(pages)


def _title_text(prop: Dict[str, Any]) -> str:
    title = prop.get("title", [])
    if not title:
        return ""
    first = title[0]
    return first.get("plain_text") or first.get("text", {}).get("content", "")


def _rich_text(prop: Dict[str, Any]) -> str:
    rich_text = prop.get("rich_text", [])
    if not rich_text:
        return ""
    first = rich_text[0]
    return first.get("plain_text") or first.get("text", {}).get("content", "")


def build_tool_stats_index(client: NotionClient, db_id: str) -> Dict[tuple, str]:
    """Build natural-key index for Tool Stats: (Tool Name, Period) -> page_id."""
    index: Dict[tuple, str] = {}
    for page in client.query_database(db_id):
        props = page.get("properties", {})
        key = (
            _title_text(props.get("Tool Name", {})),
            _rich_text(props.get("Period", {})),
        )
        if key[0]:
            index[key] = page["id"]
    return index


def build_domain_map_index(client: NotionClient, db_id: str) -> Dict[str, str]:
    """Build natural-key index for Domain Map: Domain -> page_id."""
    index: Dict[str, str] = {}
    for page in client.query_database(db_id):
        props = page.get("properties", {})
        domain = _title_text(props.get("Domain", {}))
        if domain:
            index[domain] = page["id"]
    return index


def sync_tool_stats(
    client: NotionClient,
    db_id: str,
    stats: List[Dict[str, Any]],
    period: str,
    append: bool = False,
    existing_index: Optional[Dict[tuple, str]] = None,
    dry_run: bool = False,
) -> int:
    """Sync tool stats to Notion database.

    Schema (from notion_setup.py):
        Tool Name (title), Period (rich_text), Usage Count (number),
        Success Rate (number), Common Sequences (rich_text), Last Updated (date)

    Returns:
        Number of entries written.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    written = 0

    index = existing_index or {}
    for stat in stats:
        props = {
            "Tool Name": {"title": [{"text": {"content": stat["name"]}}]},
            "Period": {"rich_text": [{"text": {"content": period}}]},
            "Usage Count": {"number": stat["usage"]},
            "Success Rate": {"number": stat["success_rate"]},
            "Last Updated": {"date": {"start": today}},
        }

        if dry_run:
            action = "update" if append and (stat["name"], period) in index else "create"
            print(
                f"    [DRY-RUN] Would {action}: {stat['name']} "
                f"({stat['usage']} uses)"
            )
        else:
            page_id = index.get((stat["name"], period)) if append else None
            if page_id:
                client.update_page(page_id, props)
            else:
                created = client.create_page(
                    parent_id=db_id,
                    properties=props,
                    is_database=True,
                )
                if append:
                    index[(stat["name"], period)] = created["id"]
        written += 1

    return written


def sync_domain_map(
    client: NotionClient,
    db_id: str,
    stats: List[Dict[str, Any]],
    append: bool = False,
    existing_index: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> int:
    """Sync domain map to Notion database.

    Schema (from notion_setup.py):
        Domain (title), Category (select), Conversation Count (number),
        Depth Score (number), Trend (select), Last Seen (date), Gap Indicator (checkbox)

    Returns:
        Number of entries written.
    """
    written = 0

    index = existing_index or {}
    for stat in stats:
        # Build date property - handle empty string
        last_seen_prop = {}
        if stat.get("last_seen"):
            # Convert YYYY-MM to YYYY-MM-01 for Notion date
            last_seen_prop = {"date": {"start": f"{stat['last_seen']}-01"}}
        else:
            last_seen_prop = {"date": None}

        props = {
            "Domain": {"title": [{"text": {"content": stat["name"]}}]},
            "Category": {"select": {"name": stat.get("category", "other")}},
            "Conversation Count": {"number": stat["count"]},
            "Depth Score": {"number": stat["depth"]},
            "Trend": {"select": {"name": stat.get("trend", "stable")}},
            "Last Seen": last_seen_prop,
            "Gap Indicator": {"checkbox": stat.get("gap_indicator", False)},
        }

        if dry_run:
            action = "update" if append and stat["name"] in index else "create"
            print(
                f"    [DRY-RUN] Would {action}: {stat['name']} "
                f"({stat['count']} convs, depth={stat['depth']})"
            )
        else:
            page_id = index.get(stat["name"]) if append else None
            if page_id:
                client.update_page(page_id, props)
            else:
                created = client.create_page(
                    parent_id=db_id,
                    properties=props,
                    is_database=True,
                )
                if append:
                    index[stat["name"]] = created["id"]
        written += 1

    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync local statistics to Notion Tool Stats and Domain Map databases"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to Notion",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append/update by natural key without clearing existing data",
    )
    parser.add_argument(
        "--period",
        default="all-time",
        help="Period label for Tool Stats entries (default: all-time)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    print("=" * 60)
    print("  Notion Stats Sync")
    print("=" * 60)
    print()

    # Step 1: Load config and create client
    print("[1/5] Loading Notion config...")
    if not os.path.isfile(_CONFIG_PATH):
        print(f"  ERROR: Config file not found: {_CONFIG_PATH}")
        print("  Run notion_setup.py first to initialize Notion databases.")
        return 1

    client = NotionClient.load_config(_CONFIG_PATH)
    tool_stats_db = client.databases.get("tool_stats")
    domain_map_db = client.databases.get("domain_map")

    if not tool_stats_db or not domain_map_db:
        print("  ERROR: Database IDs not found in config.")
        return 1

    print(f"  Tool Stats DB: {tool_stats_db}")
    print(f"  Domain Map DB: {domain_map_db}")

    # Step 2: Load local conversations
    print("\n[2/5] Loading local conversations...")
    conversations = load_conversations()
    print(f"  Loaded {len(conversations)} conversations")

    if not conversations:
        print("  ERROR: No conversations found. Run ingest scripts first.")
        return 1

    # Step 3: Aggregate statistics
    print("\n[3/5] Aggregating statistics...")
    tool_stats = aggregate_tool_stats(conversations)
    domain_stats = aggregate_domain_stats(conversations)
    print(f"  Tool Stats: {len(tool_stats)} tools")
    print(f"  Domain Map: {len(domain_stats)} domains")

    # Step 4: Clear existing data (unless --append)
    if not args.append and not args.dry_run:
        print("\n[4/5] Clearing existing Notion data...")
        tool_deleted = clear_database(client, tool_stats_db, "Tool Stats")
        domain_deleted = clear_database(client, domain_map_db, "Domain Map")
        print(f"  Deleted: {tool_deleted} tool entries, {domain_deleted} domain entries")
    else:
        print("\n[4/5] Skipping clear (--append or --dry-run)")

    # Step 5: Write new data
    print("\n[5/5] Writing to Notion...")

    print("  Syncing Tool Stats...")
    tool_index = None
    domain_index = None
    if args.append:
        print("  Building append indexes...")
        tool_index = build_tool_stats_index(client, tool_stats_db)
        domain_index = build_domain_map_index(client, domain_map_db)
        print(
            f"  Existing entries: {len(tool_index)} tool stats, "
            f"{len(domain_index)} domains"
        )

    tool_written = sync_tool_stats(
        client,
        tool_stats_db,
        tool_stats,
        args.period,
        append=args.append,
        existing_index=tool_index,
        dry_run=args.dry_run,
    )

    print("  Syncing Domain Map...")
    domain_written = sync_domain_map(
        client,
        domain_map_db,
        domain_stats,
        append=args.append,
        existing_index=domain_index,
        dry_run=args.dry_run,
    )

    # Summary
    print()
    print("=" * 60)
    if args.dry_run:
        print("  DRY RUN COMPLETE")
        print(f"  Would write: {tool_written} tool stats, {domain_written} domains")
    else:
        print("  SYNC COMPLETE")
        print(f"  Written: {tool_written} tool stats, {domain_written} domains")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
