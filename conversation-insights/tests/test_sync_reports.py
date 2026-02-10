from __future__ import annotations

import json
from pathlib import Path

import _sync_analysis_reports_core as sync_reports


def _incremental_payload() -> dict:
    return {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "week": "rolling_30d",
        "generated_at": "2026-02-06T10:00:00+00:00",
        "source_run_id": "run-1",
        "coverage": {"sessions_total": 2, "sessions_with_mechanism": 2},
        "reports": [
            {
                "dimension": "incremental-root-causes",
                "layer": "L3",
                "title": "增量根因假设 - rolling_30d",
                "key_insights": "开场上下文不足导致澄清循环。",
                "detail_lines": [
                    "证据: s-1#T1 snippet",
                    "动作: 使用四行开场契约",
                ],
                "conversations_analyzed": 2,
                "period": "rolling_30d",
                "date": "2026-02-06",
            }
        ],
        "guardrails": ["evidence-first"],
    }


def test_load_incremental_mechanism_latest(tmp_path: Path, monkeypatch) -> None:
    incremental_dir = tmp_path / "incremental"
    incremental_dir.mkdir(parents=True, exist_ok=True)

    payload = _incremental_payload()
    (incremental_dir / "rolling_30d.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(sync_reports, "_INCREMENTAL_DIR", incremental_dir)
    loaded = sync_reports.load_incremental_mechanism(latest=True)

    assert loaded is not None
    assert loaded["period_id"] == "rolling_30d"


def test_main_dry_run_without_incremental_file_returns_zero(tmp_path: Path, monkeypatch) -> None:
    incremental_dir = tmp_path / "incremental"
    incremental_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sync_reports, "_INCREMENTAL_DIR", incremental_dir)

    rc = sync_reports.main(["--dry-run"])
    assert rc == 0


def test_sync_reports_quality_gate_blocks_placeholder_payload() -> None:
    payload = _incremental_payload()
    payload["reports"][0]["key_insights"] = "insufficient-evidence"

    rc = sync_reports.sync_reports_from_incremental(payload, dry_run=True)
    assert rc == 1


def test_build_reports_from_skill_reports_preserves_detail_lines() -> None:
    payload = _incremental_payload()
    reports = sync_reports.build_reports_from_incremental(payload)

    assert len(reports) == 1
    assert reports[0]["dimension"] == "incremental-root-causes"
    assert reports[0]["detail_lines"][0].startswith("证据")


def test_write_report_includes_children_blocks() -> None:
    payload = _incremental_payload()
    report = sync_reports.build_reports_from_incremental(payload)[0]

    class DummyClient:
        def __init__(self) -> None:
            self.calls = []

        def create_page(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": "page-1"}

    client = DummyClient()
    ok = sync_reports._write_report(client, "db-1", report, dry_run=False)  # type: ignore[attr-defined]

    assert ok is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["parent_id"] == "db-1"
    assert call["is_database"] is True
    assert isinstance(call.get("children"), list)
    assert len(call["children"]) >= 3


def test_write_report_updates_existing_page_when_key_exists() -> None:
    payload = _incremental_payload()
    report = sync_reports.build_reports_from_incremental(payload)[0]

    class DummyClient:
        def __init__(self) -> None:
            self.updated = []
            self.cleared = []
            self.appended = []
            self.created = []

        def update_page(self, page_id, properties):
            self.updated.append((page_id, properties))
            return {"id": page_id}

        def clear_page(self, page_id):
            self.cleared.append(page_id)

        def append_blocks(self, page_id, blocks):
            self.appended.append((page_id, blocks))

        def create_page(self, **kwargs):
            self.created.append(kwargs)
            return {"id": "created-1"}

    key = (report["dimension"], report["period"])
    index = {key: "page-existing-1"}
    client = DummyClient()

    ok = sync_reports._write_report(  # type: ignore[attr-defined]
        client,
        "db-1",
        report,
        dry_run=False,
        existing_index=index,
    )

    assert ok is True
    assert client.updated and client.updated[0][0] == "page-existing-1"
    assert client.cleared == ["page-existing-1"]
    assert len(client.appended) == 1
    assert client.created == []


def test_build_report_index_and_duplicates_prefers_chinese() -> None:
    class DummyClient:
        def query_database(self, _db_id):
            return [
                {
                    "id": "page-en",
                    "last_edited_time": "2026-02-09T01:00:00.000Z",
                    "properties": {
                        "Dimension": {"select": {"name": "incremental-root-causes"}},
                        "Period": {"select": {"name": "rolling_all-time"}},
                        "Title": {"title": [{"plain_text": "Incremental Root Causes - rolling_all-time"}]},
                        "Key Insights": {"rich_text": [{"plain_text": "english only"}]},
                    },
                },
                {
                    "id": "page-zh",
                    "last_edited_time": "2026-02-08T01:00:00.000Z",
                    "properties": {
                        "Dimension": {"select": {"name": "incremental-root-causes"}},
                        "Period": {"select": {"name": "rolling_all-time"}},
                        "Title": {"title": [{"plain_text": "增量根因假设 - rolling_all-time"}]},
                        "Key Insights": {"rich_text": [{"plain_text": "中文"}]},
                    },
                },
            ]

    index, duplicates = sync_reports._build_report_index_and_duplicates(  # type: ignore[attr-defined]
        DummyClient(),
        "db-1",
    )

    assert index[("incremental-root-causes", "rolling_all-time")] == "page-zh"
    assert len(duplicates) == 1
    assert duplicates[0]["page_id"] == "page-en"


def test_archive_duplicate_pages() -> None:
    class DummyClient:
        def __init__(self):
            self.archived = []

        def archive_page(self, page_id):
            self.archived.append(page_id)
            return {"id": page_id}

    client = DummyClient()
    archived, failed = sync_reports._archive_duplicate_pages(  # type: ignore[attr-defined]
        client,
        [
            {"page_id": "p1"},
            {"page_id": "p2"},
        ],
    )
    assert archived == 2
    assert failed == 0
    assert client.archived == ["p1", "p2"]
