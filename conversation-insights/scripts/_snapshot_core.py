#!/usr/bin/env python3
"""
Weekly Snapshot Generator for Conversation Insights.

Saves key metrics to enable trend tracking over time.

Usage:
    python scripts/snapshot.py              # Generate snapshot for current week
    python scripts/snapshot.py --compare    # Compare with previous week
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Path setup
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from local_loader import load_conversations  # noqa: E402


def calculate_metrics(conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate key metrics from conversations."""
    total = len(conversations)
    if total == 0:
        return {"error": "No conversations found"}

    # Basic counts
    sources = {}
    outcomes = {"resolved": 0, "partial": 0, "abandoned": 0, "exploratory": 0}
    domains = {}
    task_types = {}

    # Quality metrics
    prompt_scores = []
    difficulties = []
    turn_counts = []

    # Cognitive patterns
    cognitive_counts = {
        "scope_creep": 0,
        "perfectionism": 0,
        "anchoring": 0,
        "decision_fatigue": 0,
        "sunk_cost": 0,
        "confirmation_bias": 0,
    }

    # Correction analysis
    total_corrections = 0
    total_turns = 0

    for conv in conversations:
        # Source
        source = conv.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1

        # Metadata (llm_metadata is nested under metadata)
        meta = conv.get("metadata", {}).get("llm_metadata", {})
        if not isinstance(meta, dict):
            continue

        # Outcome
        outcome = meta.get("outcome", "unknown")
        if outcome in outcomes:
            outcomes[outcome] += 1

        # Domains
        for domain in meta.get("actual_domains", []):
            top_domain = domain.split(".")[0] if "." in domain else domain
            domains[top_domain] = domains.get(top_domain, 0) + 1

        # Task type
        task_type = meta.get("task_type", "other")
        task_types[task_type] = task_types.get(task_type, 0) + 1

        # Prompt quality
        pq = meta.get("prompt_quality", {})
        if isinstance(pq, dict) and "score" in pq:
            prompt_scores.append(pq["score"])

        # Difficulty
        diff = meta.get("difficulty")
        if isinstance(diff, (int, float)):
            difficulties.append(diff)

        # Turn count (from metadata or len of turns array)
        turns_count = conv.get("metadata", {}).get("total_turns", 0)
        if turns_count == 0:
            turns_count = len(conv.get("turns", []))
        if turns_count > 0:
            turn_counts.append(turns_count)
            total_turns += turns_count

        # Corrections
        corrections = meta.get("correction_analysis", [])
        if isinstance(corrections, list):
            total_corrections += len(corrections)

        # Cognitive patterns
        patterns = meta.get("cognitive_patterns", [])
        if isinstance(patterns, list):
            for p in patterns:
                if isinstance(p, dict):
                    pattern_name = p.get("pattern", "")
                    if pattern_name in cognitive_counts:
                        cognitive_counts[pattern_name] += 1

    # Calculate averages
    avg_prompt_score = sum(prompt_scores) / len(prompt_scores) if prompt_scores else 0
    avg_difficulty = sum(difficulties) / len(difficulties) if difficulties else 0
    avg_turns = sum(turn_counts) / len(turn_counts) if turn_counts else 0
    correction_density = (total_corrections / total_turns * 100) if total_turns > 0 else 0

    # Resolution rate
    resolution_rate = (outcomes["resolved"] / total * 100) if total > 0 else 0

    return {
        "snapshot_date": datetime.now().isoformat(),
        "week": datetime.now().strftime("%Y-W%W"),
        "totals": {
            "conversations": total,
            "turns": total_turns,
            "corrections": total_corrections,
        },
        "sources": sources,
        "outcomes": outcomes,
        "metrics": {
            "avg_prompt_score": round(avg_prompt_score, 1),
            "avg_difficulty": round(avg_difficulty, 1),
            "avg_turns": round(avg_turns, 1),
            "correction_density_pct": round(correction_density, 2),
            "resolution_rate_pct": round(resolution_rate, 1),
        },
        "cognitive_patterns": cognitive_counts,
        "top_domains": dict(sorted(domains.items(), key=lambda x: x[1], reverse=True)[:10]),
        "top_task_types": dict(sorted(task_types.items(), key=lambda x: x[1], reverse=True)[:10]),
    }


def save_snapshot(metrics: Dict[str, Any], output_dir: Path) -> str:
    """Save snapshot to file."""
    week = metrics.get("week", datetime.now().strftime("%Y-W%W"))
    filename = f"{week}.json"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    return str(filepath)


def load_snapshot(week: str, output_dir: Path) -> Optional[Dict[str, Any]]:
    """Load a snapshot by week identifier."""
    filepath = output_dir / f"{week}.json"
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def get_previous_week(week: str) -> str:
    """Get the previous week identifier."""
    year, week_num = week.split("-W")
    week_num = int(week_num)
    if week_num > 1:
        return f"{year}-W{week_num - 1:02d}"
    else:
        return f"{int(year) - 1}-W52"


def compare_snapshots(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two snapshots and calculate deltas."""
    deltas = {}

    # Compare metrics
    for key in ["avg_prompt_score", "correction_density_pct", "resolution_rate_pct", "avg_turns"]:
        curr_val = current.get("metrics", {}).get(key, 0)
        prev_val = previous.get("metrics", {}).get(key, 0)
        delta = curr_val - prev_val
        pct_change = (delta / prev_val * 100) if prev_val != 0 else 0
        deltas[key] = {
            "current": curr_val,
            "previous": prev_val,
            "delta": round(delta, 2),
            "pct_change": round(pct_change, 1),
        }

    # Compare cognitive patterns
    pattern_deltas = {}
    for pattern in current.get("cognitive_patterns", {}):
        curr_count = current.get("cognitive_patterns", {}).get(pattern, 0)
        prev_count = previous.get("cognitive_patterns", {}).get(pattern, 0)
        pattern_deltas[pattern] = {
            "current": curr_count,
            "previous": prev_count,
            "delta": curr_count - prev_count,
        }
    deltas["cognitive_patterns"] = pattern_deltas

    return deltas


def generate_trend_report(current: Dict[str, Any], previous: Optional[Dict[str, Any]], output_dir: Path) -> str:
    """Generate a markdown trend report."""
    week = current.get("week", "unknown")

    lines = [
        "# 周趋势报告",
        "",
        f"**报告周期**: {week}",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 本周概览",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 对话总数 | {current.get('totals', {}).get('conversations', 0)} |",
        f"| 总轮次 | {current.get('totals', {}).get('turns', 0)} |",
        f"| Prompt 质量 | {current.get('metrics', {}).get('avg_prompt_score', 0)}/100 |",
        f"| 完成率 | {current.get('metrics', {}).get('resolution_rate_pct', 0)}% |",
        f"| 纠正密度 | {current.get('metrics', {}).get('correction_density_pct', 0)}% |",
        "",
    ]

    if previous:
        deltas = compare_snapshots(current, previous)
        prev_week = previous.get("week", "unknown")

        lines.extend([
            "---",
            "",
            f"## 与上周 ({prev_week}) 对比",
            "",
            "| 指标 | 上周 | 本周 | 变化 | 趋势 |",
            "|------|------|------|------|------|",
        ])

        for key, label in [
            ("avg_prompt_score", "Prompt 质量"),
            ("resolution_rate_pct", "完成率"),
            ("correction_density_pct", "纠正密度"),
        ]:
            d = deltas.get(key, {})
            delta = d.get("delta", 0)
            trend = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            # For correction density, lower is better
            if key == "correction_density_pct":
                trend = "↑" if delta < 0 else ("↓" if delta > 0 else "→")
            lines.append(
                f"| {label} | {d.get('previous', 0)} | {d.get('current', 0)} | {delta:+.1f} | {trend} |"
            )

        lines.extend([
            "",
            "### 认知模式变化",
            "",
            "| 模式 | 上周 | 本周 | 变化 |",
            "|------|------|------|------|",
        ])

        for pattern, d in deltas.get("cognitive_patterns", {}).items():
            if d.get("current", 0) > 0 or d.get("previous", 0) > 0:
                lines.append(
                    f"| {pattern} | {d.get('previous', 0)} | {d.get('current', 0)} | {d.get('delta', 0):+d} |"
                )

    lines.extend([
        "",
        "---",
        "",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ])

    report_path = output_dir.parent / "trend_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return str(report_path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate weekly snapshots for trend tracking")
    parser.add_argument("--compare", action="store_true", help="Compare with previous week")
    parser.add_argument("--report", action="store_true", help="Generate trend report")
    args = parser.parse_args(argv)

    # Setup paths
    project_dir = Path(_SCRIPT_DIR).parent
    data_dir = project_dir / "data" / "conversations"
    output_dir = project_dir / "output" / "snapshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("正在加载对话数据...")
    conversations = load_conversations(str(data_dir))
    print(f"已加载 {len(conversations)} 条对话")

    print("正在计算指标...")
    metrics = calculate_metrics(conversations)

    print("正在保存快照...")
    filepath = save_snapshot(metrics, output_dir)
    print(f"快照已保存: {filepath}")

    # Load previous week for comparison
    previous = None
    if args.compare or args.report:
        prev_week = get_previous_week(metrics["week"])
        previous = load_snapshot(prev_week, output_dir)
        if previous:
            print(f"已加载上周快照: {prev_week}")
        else:
            print(f"未找到上周快照: {prev_week}")

    # Compare
    if args.compare and previous:
        deltas = compare_snapshots(metrics, previous)
        print("\n=== 周对比 ===")
        for key, d in deltas.items():
            if key != "cognitive_patterns":
                print(f"  {key}: {d['previous']} → {d['current']} ({d['delta']:+.2f})")

    # Generate report
    if args.report:
        report_path = generate_trend_report(metrics, previous, output_dir)
        print(f"趋势报告已生成: {report_path}")

    print("\n=== 本周快照摘要 ===")
    print(f"  对话数: {metrics['totals']['conversations']}")
    print(f"  Prompt 质量: {metrics['metrics']['avg_prompt_score']}/100")
    print(f"  完成率: {metrics['metrics']['resolution_rate_pct']}%")
    print(f"  纠正密度: {metrics['metrics']['correction_density_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
