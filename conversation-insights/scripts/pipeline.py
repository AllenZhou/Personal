#!/usr/bin/env python3
"""Unified serial orchestrator for conversation-insights."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_DATA_DIR = _SKILL_ROOT / "data" / "conversations"
_CONFIG_PATH = _SKILL_ROOT / "config.yaml"
_INSIGHTS_SESSION_DIR = _SKILL_ROOT / "data" / "insights" / "session"
_INSIGHTS_INCREMENTAL_DIR = _SKILL_ROOT / "data" / "insights" / "incremental"
_TESTS_DIR = _SKILL_ROOT / "tests"


def _run_script(script_name: str, script_args: List[str]) -> int:
    """Execute a Python script with the current interpreter."""
    script_path = _SCRIPT_DIR / script_name
    cmd = [sys.executable, str(script_path), *script_args]
    print("[pipeline] exec:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(_SKILL_ROOT))
    return int(result.returncode)


def _run_python_module(module: str, args: List[str]) -> int:
    """Execute python -m <module> with args."""
    cmd = [sys.executable, "-m", module, *args]
    print("[pipeline] exec:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(_SKILL_ROOT))
    return int(result.returncode)


def _run_step(label: str, script_name: str, script_args: List[str]) -> int:
    """Run a script step and stop on first failure."""
    print(f"[pipeline] step={label} start")
    rc = _run_script(script_name, script_args)
    if rc != 0:
        print(f"[pipeline] step={label} failed rc={rc}", file=sys.stderr)
        return rc
    print(f"[pipeline] step={label} done")
    return 0


def _derive_stats_period_label(*, since: Optional[str], window: str) -> str:
    """Derive stats period label using the same logic as incremental diagnosis."""
    from diagnose_helper import _build_period_id, _parse_window_to_since

    since_arg = since
    until_arg: Optional[str] = None

    if not since_arg and window:
        parsed_since = _parse_window_to_since(window)
        since_arg = parsed_since
        if parsed_since is not None:
            until_arg = datetime.now().date().isoformat()

    return _build_period_id(
        since=since_arg,
        until=until_arg,
        window=window,
        explicit_period_id=None,
    )


def _run_core_chain(args: argparse.Namespace) -> int:
    """Run serial chain from ingestion to Notion sync and dashboard."""
    mode = args.mode
    since = args.since
    window = "all-time" if mode == "full" else args.window

    # 1) Ingest
    if not args.skip_ingest:
        rc = _run_step(
            "ingest_claude_code",
            "ingest_claude_code.py",
            ["--since", since] if since else [],
        )
        if rc != 0:
            return rc

        rc = _run_step(
            "ingest_codex",
            "ingest_codex.py",
            ["--since", since] if since else [],
        )
        if rc != 0:
            return rc

    # 2) Enrich
    if not args.skip_enrich:
        enrich_args: List[str] = []
        if args.enrich_limit is not None:
            enrich_args.extend(["--limit", str(args.enrich_limit)])
        rc = _run_step("enrich_heuristic", "auto_enricher.py", enrich_args)
        if rc != 0:
            return rc

    # 3) Session sidecar backfill (auto, serial)
    if not args.skip_backfill:
        backfill_args: List[str] = [
            "backfill",
            "--window",
            window,
            "--provider",
            args.skill_provider,
            "--timeout-sec",
            str(args.skill_timeout_sec),
            "--max-workers",
            str(args.skill_max_workers),
        ]
        if args.run_id:
            backfill_args.extend(["--run-id", args.run_id])
        if args.skill_model:
            backfill_args.extend(["--model", args.skill_model])
        if args.backfill_limit is not None:
            backfill_args.extend(["--limit", str(args.backfill_limit)])
        if args.backfill_force_refresh:
            backfill_args.append("--force-refresh")
        if args.allow_partial_backfill:
            backfill_args.append("--allow-partial")
        if args.dry_run:
            backfill_args.append("--dry-run")

        rc = _run_step("diagnose_backfill", "diagnose_helper.py", backfill_args)
        if rc != 0:
            return rc

    # 4) Build incremental mechanism + sync reports
    diagnose_args: List[str] = [
        "incremental",
        "--window",
        window,
        "--provider",
        args.skill_provider,
        "--timeout-sec",
        str(args.skill_timeout_sec),
        "--sync-report",
    ]
    if args.run_id:
        diagnose_args.extend(["--run-id", args.run_id])
    if args.skill_model:
        diagnose_args.extend(["--model", args.skill_model])
    if args.dry_run:
        diagnose_args.append("--dry-run")

    rc = _run_step("diagnose_incremental", "diagnose_helper.py", diagnose_args)
    if rc != 0:
        return rc

    # 5) Sync tool/domain stats
    from _sync_notion_stats_core import main as stats_main

    try:
        stats_period = _derive_stats_period_label(since=since, window=window)
    except Exception as exc:
        print(f"[pipeline] step=sync_stats failed to derive period label: {exc}", file=sys.stderr)
        return 2

    stats_args: List[str] = ["--append", "--period", stats_period]
    if args.dry_run:
        stats_args.append("--dry-run")

    print("[pipeline] step=sync_stats start")
    rc = stats_main(stats_args)
    if rc != 0:
        print(f"[pipeline] step=sync_stats failed rc={rc}", file=sys.stderr)
        return int(rc)
    print("[pipeline] step=sync_stats done")

    # 6) Render dashboard
    from _dashboard_core import main as dashboard_main

    dashboard_args: List[str] = []
    if args.output:
        dashboard_args.extend(["--output", args.output])
    if args.report_limit is not None:
        dashboard_args.extend(["--report-limit", str(args.report_limit)])
    if args.no_notion or args.dry_run:
        dashboard_args.append("--no-notion")

    print("[pipeline] step=dashboard start")
    rc = dashboard_main(dashboard_args)
    if rc != 0:
        print(f"[pipeline] step=dashboard failed rc={rc}", file=sys.stderr)
        return int(rc)
    print("[pipeline] step=dashboard done")

    return 0


def run_pipeline(args: argparse.Namespace) -> int:
    """Public serial pipeline entrypoint."""
    started_at = datetime.now().isoformat()
    rc = _run_core_chain(args)
    finished_at = datetime.now().isoformat()
    print(
        json.dumps(
            {
                "schema_version": "pipeline-run-summary.v1",
                "mode": args.mode,
                "dry_run": bool(args.dry_run),
                "started_at": started_at,
                "finished_at": finished_at,
                "ok": rc == 0,
                "rc": rc,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(rc)


def _session_contract_health() -> dict[str, Any]:
    """Validate session mechanism sidecars."""
    result = {
        "total": 0,
        "malformed": 0,
        "invalid": 0,
    }

    if not _INSIGHTS_SESSION_DIR.is_dir():
        return result

    from diagnose_helper import validate_session_mechanism

    for path in _INSIGHTS_SESSION_DIR.glob("*.json"):
        result["total"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            result["malformed"] += 1
            continue
        errors = validate_session_mechanism(payload)
        if errors:
            result["invalid"] += 1

    return result


def _incremental_contract_health() -> dict[str, Any]:
    """Validate incremental mechanism sidecars."""
    result = {
        "total": 0,
        "malformed": 0,
        "invalid": 0,
    }

    if not _INSIGHTS_INCREMENTAL_DIR.is_dir():
        return result

    from diagnose_helper import validate_incremental_mechanism

    for path in _INSIGHTS_INCREMENTAL_DIR.glob("*.json"):
        result["total"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            result["malformed"] += 1
            continue
        errors = validate_incremental_mechanism(payload)
        if errors:
            result["invalid"] += 1

    return result


def run_doctor(args: argparse.Namespace) -> int:
    """Run basic health checks without mutating project state."""
    checks: List[dict[str, Any]] = []

    checks.append({"name": "config_exists", "ok": _CONFIG_PATH.is_file(), "detail": str(_CONFIG_PATH)})
    checks.append({"name": "data_dir_exists", "ok": _DATA_DIR.is_dir(), "detail": str(_DATA_DIR)})
    checks.append(
        {
            "name": "insights_session_dir_exists",
            "ok": _INSIGHTS_SESSION_DIR.is_dir(),
            "detail": str(_INSIGHTS_SESSION_DIR),
        }
    )
    checks.append(
        {
            "name": "insights_incremental_dir_exists",
            "ok": _INSIGHTS_INCREMENTAL_DIR.is_dir(),
            "detail": str(_INSIGHTS_INCREMENTAL_DIR),
        }
    )

    files = 0
    schema_v12 = 0
    llm_meta = 0
    malformed = 0

    if _DATA_DIR.is_dir():
        for path in _DATA_DIR.glob("*.json"):
            files += 1
            try:
                conv = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                malformed += 1
                continue

            if conv.get("schema_version") == "1.2":
                schema_v12 += 1
            if conv.get("metadata", {}).get("llm_metadata"):
                llm_meta += 1

    valid_conversation_files = max(files - malformed, 0)
    checks.append({"name": "conversation_files", "ok": files > 0, "detail": files})
    checks.append(
        {
            "name": "schema_v12_coverage",
            "ok": files == 0 or schema_v12 == valid_conversation_files,
            "detail": {"v12": schema_v12, "valid": valid_conversation_files},
        }
    )
    checks.append(
        {
            "name": "llm_metadata_coverage",
            "ok": files == 0 or llm_meta == valid_conversation_files,
            "detail": {"with_llm_metadata": llm_meta, "valid": valid_conversation_files},
        }
    )
    checks.append({"name": "malformed_json", "ok": malformed == 0, "detail": malformed})

    session_health = _session_contract_health()
    incremental_health = _incremental_contract_health()

    checks.append(
        {
            "name": "session_mechanism_contract",
            "ok": session_health["malformed"] == 0 and session_health["invalid"] == 0,
            "detail": session_health,
        }
    )
    checks.append(
        {
            "name": "incremental_mechanism_contract",
            "ok": incremental_health["malformed"] == 0 and incremental_health["invalid"] == 0,
            "detail": incremental_health,
        }
    )

    overall_ok = all(c["ok"] for c in checks)
    report = {
        "timestamp": datetime.now().isoformat(),
        "overall_ok": overall_ok,
        "checks": checks,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Pipeline Doctor")
        print("=" * 60)
        for item in checks:
            status = "OK" if item["ok"] else "FAIL"
            print(f"[{status}] {item['name']}: {item['detail']}")

    return 0 if overall_ok else 1


def run_tests(args: argparse.Namespace) -> int:
    """Run segmented/full test suites."""
    scripts = sorted(str(path) for path in _SCRIPT_DIR.glob("*.py"))
    rc = _run_python_module("py_compile", scripts)
    if rc != 0:
        return rc

    if args.mode == "segmented":
        test_targets = [
            str(_TESTS_DIR / "test_diagnose_contract.py"),
            str(_TESTS_DIR / "test_diagnose_helper.py"),
            str(_TESTS_DIR / "test_sync_reports.py"),
            str(_TESTS_DIR / "test_pipeline_cli.py"),
        ]
    else:
        test_targets = [str(_TESTS_DIR)]

    pytest_args = ["-q", *test_targets]
    return _run_python_module("pytest", pytest_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conversation Insights serial pipeline entrypoint")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run end-to-end serial pipeline")
    run.add_argument("--mode", default="incremental", choices=["incremental", "full"])  # full => all-time
    run.add_argument("--window", default="30d", help="Rolling window for incremental mode")
    run.add_argument("--since", help="Optional since date YYYY-MM-DD for ingest")
    run.add_argument("--run-id", help="Optional run id used in diagnose stage")
    run.add_argument("--dry-run", action="store_true", help="Do not write Notion")
    run.add_argument("--no-notion", action="store_true", help="Skip Notion reads when rendering dashboard")
    run.add_argument("--output", help="Dashboard output path")
    run.add_argument("--report-limit", type=int, default=50, help="Dashboard report limit (0 for all)")
    run.add_argument("--skip-ingest", action="store_true", help="Skip ingestion stage")
    run.add_argument("--skip-enrich", action="store_true", help="Skip heuristic enrich stage")
    run.add_argument("--enrich-limit", type=int, help="Optional limit for heuristic enrich")
    run.add_argument("--skip-backfill", action="store_true", help="Skip session sidecar backfill stage")
    run.add_argument(
        "--skill-provider",
        default="claude_cli",
        choices=["claude_cli", "codex_cli", "openai", "anthropic"],
        help="Skill API provider",
    )
    run.add_argument("--skill-model", help="Optional provider model override")
    run.add_argument("--skill-timeout-sec", type=int, default=180, help="Skill API timeout seconds")
    run.add_argument("--skill-max-workers", type=int, default=4, help="Concurrent workers for skill backfill")
    run.add_argument("--backfill-limit", type=int, help="Optional session limit for backfill stage")
    run.add_argument("--backfill-force-refresh", action="store_true", help="Force refresh even when sidecar exists")
    run.add_argument(
        "--allow-partial-backfill",
        action="store_true",
        help="Allow partial API failures in backfill stage",
    )
    run.set_defaults(handler=run_pipeline)

    doctor = sub.add_parser("doctor", help="Run pipeline health checks")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    doctor.set_defaults(handler=run_doctor)

    test = sub.add_parser("test", help="Run tests")
    test.add_argument("--mode", default="segmented", choices=["segmented", "full"])
    test.set_defaults(handler=run_tests)

    return parser


def _default_run_args() -> argparse.Namespace:
    return argparse.Namespace(
        mode="incremental",
        window="30d",
        since=None,
        run_id=None,
        dry_run=False,
        no_notion=False,
        output=None,
        report_limit=50,
        skip_ingest=False,
        skip_enrich=False,
        enrich_limit=None,
        skip_backfill=False,
        skill_provider="claude_cli",
        skill_model=None,
        skill_timeout_sec=180,
        skill_max_workers=4,
        backfill_limit=None,
        backfill_force_refresh=False,
        allow_partial_backfill=False,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list:
        return run_pipeline(_default_run_args())

    parser = build_parser()
    args = parser.parse_args(args_list)
    if not hasattr(args, "handler"):
        return run_pipeline(_default_run_args())
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
