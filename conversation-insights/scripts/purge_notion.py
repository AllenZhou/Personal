"""Purge data from the Conversation Insights Notion workspace.

Supports two modes:
  --analysis-only   Purge derived analysis data only (keep Conversations),
                    reset Processed flags, clear User Profile.
  (no flag)         Purge everything (all 5 databases + User Profile).

Usage:
    python scripts/purge_notion.py                 # purge all
    python scripts/purge_notion.py --analysis-only  # purge analysis data only
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Ensure sibling modules are importable when running as a script.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from notion_client import NotionClient  # noqa: E402


def _archive_page(client: NotionClient, page_id: str) -> None:
    """Archive (soft-delete) a single Notion page."""
    client._request("PATCH", f"/pages/{page_id}", {"archived": True})


def purge_database(client: NotionClient, db_id: str, label: str) -> int:
    """Archive all pages in a database. Returns the count of archived pages."""
    pages = client.query_database(db_id)
    count = len(pages)
    for i, page in enumerate(pages, 1):
        _archive_page(client, page["id"])
        if i % 20 == 0 or i == count:
            print(f"  [{label}] {i}/{count} archived")
    return count


def reset_processed(client: NotionClient, db_id: str) -> int:
    """Reset Processed checkbox to false for all pages in Conversations DB."""
    pages = client.query_database(
        db_id,
        filter={"property": "Processed", "checkbox": {"equals": True}},
    )
    count = len(pages)
    for i, page in enumerate(pages, 1):
        client.update_page(
            page["id"],
            {"Processed": NotionClient.prop_checkbox(False)},
        )
        if i % 20 == 0 or i == count:
            print(f"  [Conversations] {i}/{count} reset Processed=false")
    return count


def purge_analysis_only(client: NotionClient) -> None:
    """Purge derived analysis data, keep raw Conversations."""
    analysis_dbs = [
        ("analysis_reports", "Analysis Reports"),
        ("tool_stats", "Tool Stats"),
        ("domain_map", "Domain Map"),
        ("analysis_log", "Analysis Log"),
    ]

    total = 0
    for key, label in analysis_dbs:
        db_id = client.databases.get(key)
        if not db_id:
            print(f"  [{label}] skipped (no database ID in config)")
            continue
        n = purge_database(client, db_id, label)
        print(f"  [{label}] done — {n} page(s) archived")
        total += n

    # Reset Processed flags on Conversations
    conv_db_id = client.databases.get("conversations")
    if conv_db_id:
        n = reset_processed(client, conv_db_id)
        print(f"  [Conversations] done — {n} page(s) reset to Processed=false")
    else:
        print("  [Conversations] skipped (no database ID in config)")

    # Clear User Profile page body
    profile_id = client.pages.get("user_profile")
    if profile_id:
        print("  [User Profile] clearing page content...")
        client.clear_page(profile_id)
        print("  [User Profile] done")
    else:
        print("  [User Profile] skipped (no page ID in config)")

    print(f"\nAnalysis purge complete. {total} page(s) archived (Conversations preserved).")


def purge_all(client: NotionClient) -> None:
    """Purge everything including Conversations."""
    db_names = [
        ("conversations", "Conversations"),
        ("analysis_reports", "Analysis Reports"),
        ("tool_stats", "Tool Stats"),
        ("domain_map", "Domain Map"),
        ("analysis_log", "Analysis Log"),
    ]

    total = 0
    for key, label in db_names:
        db_id = client.databases.get(key)
        if not db_id:
            print(f"  [{label}] skipped (no database ID in config)")
            continue
        n = purge_database(client, db_id, label)
        print(f"  [{label}] done — {n} page(s) archived")
        total += n

    # Clear User Profile page body
    profile_id = client.pages.get("user_profile")
    if profile_id:
        print("  [User Profile] clearing page content...")
        client.clear_page(profile_id)
        print("  [User Profile] done")
    else:
        print("  [User Profile] skipped (no page ID in config)")

    print(f"\nPurge complete. {total} page(s) archived across {len(db_names)} databases.")


def main() -> None:
    config_path = os.path.join(_SCRIPT_DIR, os.pardir, "config.yaml")
    client = NotionClient.load_config(config_path)

    analysis_only = "--analysis-only" in sys.argv

    if analysis_only:
        print("Mode: analysis-only (preserving Conversations DB)\n")
        purge_analysis_only(client)
    else:
        print("Mode: full purge (all databases)\n")
        purge_all(client)


if __name__ == "__main__":
    main()
