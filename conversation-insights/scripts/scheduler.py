#!/usr/bin/env python3
"""Cron manager for serial conversation-insights pipeline."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CRON_MARKER = "# conversation-insights-managed"


def _python() -> str:
    return sys.executable


def _pipeline() -> str:
    return os.path.join(_SCRIPT_DIR, "pipeline.py")


def _log_dir() -> str:
    path = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "logs"))
    os.makedirs(path, exist_ok=True)
    return path


def _get_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(content: str) -> bool:
    result = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
    return result.returncode == 0


def _strip_managed(content: str) -> str:
    lines = [line for line in content.splitlines() if _CRON_MARKER not in line]
    text = "\n".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _build_entries() -> List[str]:
    py = _python()
    pipeline = _pipeline()
    logs = _log_dir()

    daily = (
        f"0 0 * * * {py} {pipeline} "
        f">> {logs}/daily.log 2>&1 {_CRON_MARKER}-daily"
    )
    full_refresh = (
        f"0 2 * * 0 {py} {pipeline} run --mode full "
        f">> {logs}/full.log 2>&1 {_CRON_MARKER}-full-refresh"
    )
    return [daily, full_refresh]


def setup_cron() -> None:
    current = _get_crontab()
    cleaned = _strip_managed(current)
    entries = _build_entries()
    combined = cleaned + ("" if cleaned.endswith("\n") or not cleaned else "\n") + "\n".join(entries) + "\n"
    if not _write_crontab(combined):
        print("错误：写入 crontab 失败", file=sys.stderr)
        raise SystemExit(1)
    print("已安装定时任务：daily incremental + periodic full")


def show_status() -> None:
    print("对话洞察 -- 定时任务状态")
    print("=" * 60)
    current = _get_crontab()
    lines = [line for line in current.splitlines() if _CRON_MARKER in line]
    if not lines:
        print("未找到托管任务")
        return
    for line in lines:
        print(line)


def remove_cron() -> None:
    current = _get_crontab()
    cleaned = _strip_managed(current)
    if not _write_crontab(cleaned):
        print("错误：移除 crontab 失败", file=sys.stderr)
        raise SystemExit(1)
    print("已移除托管定时任务")


def _run(cmd: List[str]) -> int:
    print("exec:", " ".join(cmd))
    return int(subprocess.run(cmd, cwd=os.path.normpath(os.path.join(_SCRIPT_DIR, ".."))).returncode)


def run_daily() -> None:
    rc = _run([_python(), _pipeline()])
    raise SystemExit(rc)


def run_full() -> None:
    rc = _run([_python(), _pipeline(), "run", "--mode", "full"])
    raise SystemExit(rc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage serial pipeline cron jobs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup-cron", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--remove-cron", action="store_true")
    group.add_argument("--run-daily", action="store_true")
    group.add_argument("--run-full", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.setup_cron:
        setup_cron()
    elif args.status:
        show_status()
    elif args.remove_cron:
        remove_cron()
    elif args.run_daily:
        run_daily()
    elif args.run_full:
        run_full()


if __name__ == "__main__":
    main()
