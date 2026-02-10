from __future__ import annotations

from unittest.mock import patch

import dashboard
import snapshot
import sync_analysis_reports
import sync_notion_stats


def test_sync_analysis_reports_wrapper_delegates() -> None:
    with patch("sync_analysis_reports.sync_main", return_value=0) as mocked:
        rc = sync_analysis_reports.main(["--dry-run", "--mode", "incremental"])
    assert rc == 0
    mocked.assert_called_once_with(["--dry-run"])


def test_sync_notion_stats_wrapper_delegates() -> None:
    with patch("sync_notion_stats.sync_main", return_value=0) as mocked:
        rc = sync_notion_stats.main(["--dry-run", "--mode", "full"])
    assert rc == 0
    mocked.assert_called_once_with(["--append", "--period", "all-time", "--dry-run"])


def test_dashboard_wrapper_delegates() -> None:
    with patch("dashboard.dashboard_main", return_value=0) as mocked:
        rc = dashboard.main(["--mode", "incremental"])
    assert rc == 0
    mocked.assert_called_once_with([])


def test_snapshot_wrapper_delegates() -> None:
    with patch("snapshot.snapshot_main", return_value=0) as mocked:
        rc = snapshot.main(["--report"])
    assert rc == 0
    mocked.assert_called_once_with(["--report"])
