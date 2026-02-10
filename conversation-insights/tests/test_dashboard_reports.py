from __future__ import annotations

import json
import os
from pathlib import Path

import _dashboard_core as dashboard


def test_load_local_incremental_reports_reads_latest_file(tmp_path: Path, monkeypatch) -> None:
    insights_dir = tmp_path / "insights"
    incremental_dir = insights_dir / "incremental"
    incremental_dir.mkdir(parents=True, exist_ok=True)

    older = {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "reports": [
            {
                "dimension": "incremental-root-causes",
                "layer": "L3",
                "title": "旧报告",
                "key_insights": "旧数据",
                "detail_lines": ["旧明细"],
                "date": "2026-02-08",
            }
        ],
    }
    newer = {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_all-time",
        "reports": [
            {
                "dimension": "incremental-trigger-chains",
                "layer": "L2",
                "title": "新报告",
                "key_insights": "新数据",
                "detail_lines": ["主证据", "辅助证据"],
                "date": "2026-02-10",
            }
        ],
    }

    old_path = incremental_dir / "rolling_30d.json"
    new_path = incremental_dir / "rolling_all-time.json"
    old_path.write_text(json.dumps(older, ensure_ascii=False, indent=2), encoding="utf-8")
    new_path.write_text(json.dumps(newer, ensure_ascii=False, indent=2), encoding="utf-8")

    old_stat = old_path.stat()
    new_stat = new_path.stat()
    old_path.touch()
    new_path.touch()
    os.utime(old_path, (old_stat.st_atime, old_stat.st_mtime - 60))
    os.utime(new_path, (new_stat.st_atime, new_stat.st_mtime + 60))

    monkeypatch.setattr(dashboard, "_INSIGHTS_DIR", str(insights_dir))
    reports = dashboard._load_local_incremental_reports(limit=20)  # type: ignore[attr-defined]

    assert len(reports) == 1
    assert reports[0]["title"] == "新报告"
    assert reports[0]["details"] == ["主证据", "辅助证据"]


def test_load_local_incremental_reports_splits_detail_text(tmp_path: Path, monkeypatch) -> None:
    insights_dir = tmp_path / "insights"
    incremental_dir = insights_dir / "incremental"
    incremental_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "reports": [
            {
                "dimension": "incremental-interventions",
                "layer": "L3",
                "title": "干预实验",
                "key_insights": "需要分行展示",
                "detail_text": "第一行\n第二行\n\n第三行",
                "date": "2026-02-10",
            }
        ],
    }
    (incremental_dir / "rolling_30d.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(dashboard, "_INSIGHTS_DIR", str(insights_dir))
    reports = dashboard._load_local_incremental_reports(limit=20)  # type: ignore[attr-defined]

    assert len(reports) == 1
    assert reports[0]["insights"] == "需要分行展示"
    assert reports[0]["details"] == ["第一行", "第二行", "第三行"]
