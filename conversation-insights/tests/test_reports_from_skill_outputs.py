from __future__ import annotations

from _sync_analysis_reports_core import (
    build_reports_from_incremental,
    sync_reports_from_incremental,
)


def _incremental_payload() -> dict:
    return {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "week": "rolling_30d",
        "generated_at": "2026-02-06T10:00:00+00:00",
        "source_run_id": "run-1",
        "coverage": {"sessions_total": 3, "sessions_with_mechanism": 3},
        "reports": [
            {
                "dimension": "incremental-trigger-chains",
                "layer": "L2",
                "title": "增量触发链路诊断 - rolling_30d",
                "key_insights": "开场约束缺失导致澄清循环。",
                "detail_lines": [
                    "现象：首轮需求边界不清，触发多轮澄清。",
                    "建议：开场写目标、边界、完成标准。",
                ],
                "conversations_analyzed": 3,
                "period": "rolling_30d",
                "date": "2026-02-06",
            },
            {
                "dimension": "incremental-root-causes",
                "layer": "L3",
                "title": "增量根因假设 - rolling_30d",
                "key_insights": "任务开场上下文不足是主要根因。",
                "detail_lines": [
                    "证据：s-1#T1 Need quick fix",
                    "动作：复用四行开场契约模板。",
                ],
                "conversations_analyzed": 3,
                "period": "rolling_30d",
                "date": "2026-02-06",
            },
        ],
    }


def test_build_reports_from_incremental_contract_shape() -> None:
    reports = build_reports_from_incremental(_incremental_payload())
    assert len(reports) == 2
    assert all("dimension" in report for report in reports)
    assert all("key_insights" in report for report in reports)
    layers = {report["layer"] for report in reports}
    assert "L2" in layers
    assert "L3" in layers


def test_sync_reports_from_incremental_dry_run() -> None:
    rc = sync_reports_from_incremental(_incremental_payload(), dry_run=True)
    assert rc == 0
