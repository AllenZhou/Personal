from __future__ import annotations

import argparse
import re
import sys
import types
from unittest.mock import patch

from pipeline import _run_core_chain, main


def test_pipeline_doctor_json_runs() -> None:
    rc = main(["doctor", "--json"])
    assert rc in {0, 1}


def test_pipeline_default_entry_delegates_to_run() -> None:
    with patch("pipeline._run_core_chain", return_value=0) as mocked:
        rc = main([])
    assert rc == 0
    mocked.assert_called_once()


def test_pipeline_run_full_dry_run_delegates_to_core() -> None:
    with patch("pipeline._run_core_chain", return_value=0) as mocked:
        rc = main(["run", "--mode", "full", "--dry-run"])
    assert rc == 0
    mocked.assert_called_once()


def test_pipeline_run_accepts_codex_cli_provider() -> None:
    with patch("pipeline._run_core_chain", return_value=0) as mocked:
        rc = main(["run", "--skill-provider", "codex_cli", "--dry-run"])
    assert rc == 0
    mocked.assert_called_once()


def test_pipeline_test_segmented_runs() -> None:
    with patch("pipeline._run_python_module", return_value=0) as mocked:
        rc = main(["test", "--mode", "segmented"])
    assert rc == 0
    assert mocked.call_count == 2


def test_pipeline_test_full_runs() -> None:
    with patch("pipeline._run_python_module", return_value=0) as mocked:
        rc = main(["test", "--mode", "full"])
    assert rc == 0
    assert mocked.call_count == 2


def test_core_chain_passes_backfill_and_diagnose_args(monkeypatch) -> None:
    run_step_calls = []
    stats_calls = []
    dashboard_calls = []

    def fake_run_step(label: str, script_name: str, script_args: list[str]) -> int:
        run_step_calls.append((label, script_name, list(script_args)))
        return 0

    def fake_stats_main(argv: list[str]) -> int:
        stats_calls.append(list(argv))
        return 0

    def fake_dashboard_main(argv: list[str]) -> int:
        dashboard_calls.append(list(argv))
        return 0

    monkeypatch.setattr("pipeline._run_step", fake_run_step)
    monkeypatch.setitem(
        sys.modules,
        "_sync_notion_stats_core",
        types.SimpleNamespace(main=fake_stats_main),
    )
    monkeypatch.setitem(
        sys.modules,
        "_dashboard_core",
        types.SimpleNamespace(main=fake_dashboard_main),
    )

    args = argparse.Namespace(
        mode="incremental",
        window="30d",
        since=None,
        run_id="run-x",
        dry_run=True,
        no_notion=False,
        output=None,
        report_limit=50,
        skip_ingest=False,
        skip_enrich=False,
        enrich_limit=None,
        skip_backfill=False,
        skill_provider="claude_cli",
        skill_model=None,
        skill_timeout_sec=90,
        skill_max_workers=1,
        backfill_limit=None,
        backfill_force_refresh=False,
        allow_partial_backfill=False,
    )
    rc = _run_core_chain(args)

    assert rc == 0
    assert run_step_calls[0][0] == "ingest_claude_code"
    assert run_step_calls[1][0] == "ingest_codex"
    assert run_step_calls[2][0] == "enrich_heuristic"
    backfill_call = run_step_calls[3]
    assert backfill_call[0] == "diagnose_backfill"
    assert backfill_call[1] == "diagnose_helper.py"
    assert backfill_call[2] == [
        "backfill",
        "--window",
        "30d",
        "--provider",
        "claude_cli",
        "--timeout-sec",
        "90",
        "--max-workers",
        "1",
        "--run-id",
        "run-x",
        "--dry-run",
    ]

    diagnose_call = run_step_calls[4]
    assert diagnose_call[0] == "diagnose_incremental"
    assert diagnose_call[1] == "diagnose_helper.py"
    assert diagnose_call[2] == [
        "incremental",
        "--window",
        "30d",
        "--provider",
        "claude_cli",
        "--timeout-sec",
        "90",
        "--sync-report",
        "--run-id",
        "run-x",
        "--dry-run",
    ]
    assert len(stats_calls) == 1
    assert stats_calls[0][0:2] == ["--append", "--period"]
    assert stats_calls[0][-1] == "--dry-run"
    assert stats_calls[0][2] != "all-time"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2}", stats_calls[0][2])
    assert dashboard_calls == [["--report-limit", "50", "--no-notion"]]
