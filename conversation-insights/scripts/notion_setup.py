#!/usr/bin/env python3
"""
Notion Setup for Conversation Insights

Initializes the complete Notion database structure:
  - Root page ("Conversation Insights")
  - 5 databases (Conversations, Analysis Reports, Tool Stats, Domain Map, Analysis Log)
  - User Profile page with template content

Usage:
    python scripts/notion_setup.py --api-key ntn_xxxx --parent-page xxxx

All created resource IDs are written to config.yaml in the skill root directory.
"""

import sys
import os
import argparse
import traceback

# ---------------------------------------------------------------------------
# Path setup: allow importing notion_client.py from the same scripts/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notion_client import NotionClient

# Skill root is two levels up from this script (scripts/ -> conversation-insights/)
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_ROOT, "config.yaml")


# ---------------------------------------------------------------------------
# Database schema definitions
# ---------------------------------------------------------------------------

def _select_options(names: list[str]) -> list[dict]:
    """Build a list of Notion select option objects."""
    return [{"name": n} for n in names]


DATABASES: list[dict] = [
    {
        "key": "conversations",
        "title": "Conversations",
        "icon": "1f4ac",  # speech bubble
        "properties": {
            "Title": {"title": {}},
            "Session ID": {"rich_text": {}},
            "Source": {
                "select": {
                    "options": _select_options([
                        "chatgpt", "claude_code", "codex", "gemini", "claude_web",
                    ]),
                },
            },
            "Model": {"rich_text": {}},
            "Project Path": {"rich_text": {}},
            "Created At": {"date": {}},
            "Total Turns": {"number": {"format": "number"}},
            "Total Tool Uses": {"number": {"format": "number"}},
            "Domains": {"multi_select": {"options": []}},
            "Language": {
                "select": {
                    "options": _select_options(["en", "zh", "mixed"]),
                },
            },
            "Git Branch": {"rich_text": {}},
            "Processed": {"checkbox": {}},
        },
    },
    {
        "key": "analysis_reports",
        "title": "Analysis Reports",
        "icon": "1f4ca",  # bar chart
        "properties": {
            "Title": {"title": {}},
            "Dimension": {
                "select": {
                    "options": _select_options([
                        "thinking-patterns",
                        "tool-usage",
                        "knowledge-domains",
                        "collaboration-efficiency",
                        "preferences",
                        "cross-platform",
                        "temporal",
                        "tasks",
                        "prompts",
                        "cognitive",
                        "growth",
                        "code-output",
                    ]),
                },
            },
            "Layer": {
                "select": {
                    "options": _select_options(["L1", "L2", "L3"]),
                },
            },
            "Period": {
                "select": {
                    "options": _select_options(["daily", "weekly", "monthly"]),
                },
            },
            "Date": {"date": {}},
            "Conversations Analyzed": {"number": {"format": "number"}},
            "Key Insights": {"rich_text": {}},
        },
    },
    {
        "key": "tool_stats",
        "title": "Tool Stats",
        "icon": "1f527",  # wrench
        "properties": {
            "Tool Name": {"title": {}},
            "Period": {"rich_text": {}},
            "Usage Count": {"number": {"format": "number"}},
            "Success Rate": {"number": {"format": "number"}},
            "Common Sequences": {"rich_text": {}},
            "Last Updated": {"date": {}},
        },
    },
    {
        "key": "domain_map",
        "title": "Domain Map",
        "icon": "1f5fa",  # world map
        "properties": {
            "Domain": {"title": {}},
            "Category": {
                "select": {
                    "options": _select_options([
                        "frontend", "backend", "devops", "database",
                        "data-science", "mobile", "security", "testing",
                        "documentation", "architecture", "legal", "finance",
                        "design", "ai-ml", "other",
                    ]),
                },
            },
            "Conversation Count": {"number": {"format": "number"}},
            "Depth Score": {"number": {"format": "number"}},
            "Trend": {
                "select": {
                    "options": _select_options([
                        "growing", "stable", "declining", "new",
                    ]),
                },
            },
            "Last Seen": {"date": {}},
            "Gap Indicator": {"checkbox": {}},
        },
    },
    {
        "key": "analysis_log",
        "title": "Analysis Log",
        "icon": "1f4dd",  # memo
        "properties": {
            "Title": {"title": {}},
            "Run Type": {
                "select": {
                    "options": _select_options([
                        "full", "incremental", "daily", "weekly", "monthly",
                    ]),
                },
            },
            "Started At": {"date": {}},
            "Status": {
                "select": {
                    "options": _select_options([
                        "running", "completed", "failed",
                    ]),
                },
            },
            "Sessions Processed": {"number": {"format": "number"}},
        },
    },
]


# ---------------------------------------------------------------------------
# User Profile page content blocks
# ---------------------------------------------------------------------------

USER_PROFILE_BLOCKS: list[dict] = [
    {
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "User Profile"}}],
        },
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "Last Updated: (not yet analyzed)"},
                },
            ],
            "icon": {"type": "emoji", "emoji": "\u2139\ufe0f"},
        },
    },
    # --- Section: 思维画像 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u601d\u7ef4\u753b\u50cf"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
    # --- Section: 工具画像 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u5de5\u5177\u753b\u50cf"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
    # --- Section: 知识画像 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u77e5\u8bc6\u753b\u50cf"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
    # --- Section: 效率画像 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u6548\u7387\u753b\u50cf"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
    # --- Section: 偏好画像 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u504f\u597d\u753b\u50cf"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
    # --- Section: 演变历史 ---
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "\u6f14\u53d8\u5386\u53f2"}}],
        },
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "\u5f85\u5206\u6790\u540e\u586b\u5145\u2026\u2026"},
                },
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Config file writer (plain file I/O, no YAML library)
# ---------------------------------------------------------------------------

def write_config(
    api_key: str,
    parent_page_id: str,
    root_page_id: str,
    database_ids: dict[str, str],
    user_profile_id: str,
) -> str:
    """Write config.yaml using simple string formatting. Returns the file path."""
    lines = [
        "notion:",
        f'  api_key: "{api_key}"',
        f'  parent_page_id: "{parent_page_id}"',
        "  databases:",
    ]
    for key in ["conversations", "analysis_reports", "tool_stats", "domain_map", "analysis_log"]:
        db_id = database_ids.get(key, "")
        lines.append(f'    {key}: "{db_id}"')
    lines.append("  pages:")
    lines.append(f'    root: "{root_page_id}"')
    lines.append(f'    user_profile: "{user_profile_id}"')
    lines.append("")  # trailing newline

    content = "\n".join(lines)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    return CONFIG_PATH


# ---------------------------------------------------------------------------
# Main setup logic
# ---------------------------------------------------------------------------

def create_root_page(client: NotionClient, parent_page_id: str) -> str:
    """Create the 'Conversation Insights' root page under the parent page.

    Returns:
        The ID of the newly created page.
    """
    print("[1/7] Creating root page 'Conversation Insights'...")
    response = client.create_page(
        parent_id=parent_page_id,
        properties={
            "title": [
                {
                    "type": "text",
                    "text": {"content": "Conversation Insights"},
                },
            ],
        },
        is_database=False,
        icon={"type": "emoji", "emoji": "\U0001f9e0"},
    )
    page_id = response["id"]
    print(f"  -> Root page created: {page_id}")
    return page_id


def create_database(
    client: NotionClient,
    parent_page_id: str,
    db_spec: dict,
    step_label: str,
) -> str | None:
    """Create a single database under the root page.

    Returns:
        The database ID on success, or None on failure.
    """
    title = db_spec["title"]
    print(f"[{step_label}] Creating database '{title}'...")

    try:
        emoji_codepoint = int(db_spec["icon"], 16)
        emoji_char = chr(emoji_codepoint)
    except (ValueError, OverflowError):
        emoji_char = "\U0001f4c1"  # fallback: file folder

    try:
        response = client.create_database(
            parent_page_id=parent_page_id,
            title=title,
            properties_schema=db_spec["properties"],
            icon={"type": "emoji", "emoji": emoji_char},
        )
        db_id = response["id"]
        print(f"  -> Database '{title}' created: {db_id}")
        return db_id
    except Exception as exc:
        print(f"  !! Failed to create database '{title}': {exc}")
        traceback.print_exc()
        return None


def create_user_profile_page(
    client: NotionClient,
    parent_page_id: str,
) -> str:
    """Create the User Profile child page with template content blocks.

    Returns:
        The page ID.
    """
    print("[7/7] Creating 'User Profile' page...")
    response = client.create_page(
        parent_id=parent_page_id,
        properties={
            "title": [
                {
                    "type": "text",
                    "text": {"content": "User Profile"},
                },
            ],
        },
        is_database=False,
        icon={"type": "emoji", "emoji": "\U0001f464"},
        children=USER_PROFILE_BLOCKS,
    )
    page_id = response["id"]
    print(f"  -> User Profile page created: {page_id}")
    return page_id


def print_summary(
    root_page_id: str,
    database_ids: dict[str, str],
    user_profile_id: str,
    errors: list[str],
) -> None:
    """Print a human-readable summary of all created resources."""
    print()
    print("=" * 60)
    print("  Conversation Insights - Setup Summary")
    print("=" * 60)
    print()
    print(f"  Root Page:       {root_page_id}")
    print()
    print("  Databases:")
    for key, db_id in database_ids.items():
        status = db_id if db_id else "(FAILED)"
        label = key.replace("_", " ").title()
        print(f"    {label:.<30} {status}")
    print()
    print(f"  User Profile:    {user_profile_id}")
    print()
    print(f"  Config written:  {CONFIG_PATH}")
    print()

    if errors:
        print("  WARNINGS:")
        for err in errors:
            print(f"    - {err}")
        print()

    success_count = sum(1 for v in database_ids.values() if v)
    total_count = len(database_ids)
    print(f"  Result: {success_count}/{total_count} databases created successfully.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Initialize Notion databases for Conversation Insights.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python scripts/notion_setup.py --api-key ntn_xxxx --parent-page abc123\n"
        ),
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="Notion Internal Integration Secret (starts with ntn_).",
    )
    parser.add_argument(
        "--parent-page",
        required=True,
        help="ID of the Notion page under which to create the workspace.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the full Notion setup flow.

    Returns:
        Exit code (0 on success, 1 on fatal error).
    """
    args = parse_args(argv)

    api_key: str = args.api_key
    parent_page_id: str = args.parent_page

    # Basic validation
    if not api_key.startswith("ntn_"):
        print("WARNING: API key does not start with 'ntn_'. Proceeding anyway.")

    client = NotionClient(api_key=api_key)

    errors: list[str] = []
    database_ids: dict[str, str] = {}
    user_profile_id = ""
    root_page_id = ""

    # Step 1: Create root page
    try:
        root_page_id = create_root_page(client, parent_page_id)
    except Exception as exc:
        print(f"FATAL: Could not create root page: {exc}")
        traceback.print_exc()
        return 1

    # Steps 2-6: Create databases
    for idx, db_spec in enumerate(DATABASES, start=2):
        step_label = f"{idx}/7"
        db_id = create_database(client, root_page_id, db_spec, step_label)
        if db_id:
            database_ids[db_spec["key"]] = db_id
        else:
            database_ids[db_spec["key"]] = ""
            errors.append(f"Database '{db_spec['title']}' creation failed.")

    # Step 7: Create User Profile page
    try:
        user_profile_id = create_user_profile_page(client, root_page_id)
    except Exception as exc:
        print(f"ERROR: Could not create User Profile page: {exc}")
        traceback.print_exc()
        user_profile_id = ""
        errors.append("User Profile page creation failed.")

    # Write config.yaml
    try:
        config_path = write_config(
            api_key=api_key,
            parent_page_id=parent_page_id,
            root_page_id=root_page_id,
            database_ids=database_ids,
            user_profile_id=user_profile_id,
        )
        print(f"\nConfig written to {config_path}")
    except Exception as exc:
        print(f"ERROR: Could not write config.yaml: {exc}")
        traceback.print_exc()
        errors.append("config.yaml write failed.")

    # Print summary
    print_summary(root_page_id, database_ids, user_profile_id, errors)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
