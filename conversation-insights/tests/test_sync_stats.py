from __future__ import annotations

from conftest import make_conversation
from _sync_notion_stats_core import (
    aggregate_domain_stats,
    aggregate_tool_stats,
    build_domain_map_index,
    build_tool_stats_index,
    sync_domain_map,
    sync_tool_stats,
)


class FakeClient:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.updated = []
        self.created = []

    def query_database(self, _db_id):
        return self.pages

    def update_page(self, page_id, props):
        self.updated.append((page_id, props))

    def create_page(self, parent_id, properties, is_database):
        page_id = f"new-{len(self.created)+1}"
        self.created.append((parent_id, properties, is_database))
        return {"id": page_id}


def test_aggregate_tool_stats() -> None:
    conv = make_conversation()
    conv["turns"][0]["assistant_response"]["tool_uses"].append({"tool_name": "Edit", "success": False, "input": None})
    stats = aggregate_tool_stats([conv])

    names = {item["name"] for item in stats}
    assert "Read" in names
    assert "Edit" in names


def test_aggregate_domain_stats_prefers_llm_domains() -> None:
    conv = make_conversation()
    conv["metadata"]["llm_metadata"]["actual_domains"] = ["backend.api", "legal.compliance"]
    stats = aggregate_domain_stats([conv])

    names = {item["name"] for item in stats}
    assert "backend.api" in names
    assert "legal.compliance" in names


def test_append_index_and_upsert_behavior() -> None:
    existing_pages = [
        {
            "id": "tool-1",
            "properties": {
                "Tool Name": {"title": [{"plain_text": "Read"}]},
                "Period": {"rich_text": [{"plain_text": "all-time"}]},
            },
        },
        {
            "id": "domain-1",
            "properties": {
                "Domain": {"title": [{"plain_text": "backend.api"}]},
            },
        },
    ]
    client = FakeClient(existing_pages)

    tool_index = build_tool_stats_index(client, "tool-db")
    domain_index = build_domain_map_index(client, "domain-db")

    assert tool_index[("Read", "all-time")] == "tool-1"
    assert domain_index["backend.api"] == "domain-1"

    tool_written = sync_tool_stats(
        client,
        "tool-db",
        [{"name": "Read", "usage": 10, "success_rate": 90.0}],
        "all-time",
        append=True,
        existing_index=tool_index,
        dry_run=False,
    )
    domain_written = sync_domain_map(
        client,
        "domain-db",
        [{
            "name": "backend.api",
            "count": 4,
            "depth": 4.0,
            "trend": "stable",
            "category": "backend",
            "last_seen": "2026-02",
            "gap_indicator": False,
        }],
        append=True,
        existing_index=domain_index,
        dry_run=False,
    )

    assert tool_written == 1
    assert domain_written == 1
    assert len(client.updated) == 2
    assert len(client.created) == 0
