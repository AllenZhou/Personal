from __future__ import annotations

import json
import subprocess
from pathlib import Path

from skill_runtime import run_api, run_incremental_api


def _write_bundle(jobs_root: Path, run_id: str) -> None:
    run_dir = jobs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "diagnose-run.v1",
        "run_id": run_id,
        "sessions": [
            {
                "session_id": "s-1",
                "created_at": "2026-02-06T10:00:00+00:00",
                "week": "2026-W06",
                "source": "codex",
                "turn_count": 2,
                "timeline": [
                    {
                        "turn_id": 1,
                        "user_snippet": "Please help",
                    }
                ],
            }
        ],
    }
    (run_dir / "session_digests.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_skills(skills_root: Path) -> None:
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / "diagnose-session.md").write_text(
        "输出 SessionMechanismV1 JSON。",
        encoding="utf-8",
    )
    (skills_root / "diagnose-incremental.md").write_text(
        "输出 IncrementalMechanismV1 JSON。",
        encoding="utf-8",
    )
    (skills_root / "analyze-behavior.md").write_text(
        "行为链机制诊断约束。",
        encoding="utf-8",
    )
    (skills_root / "analyze-attribution.md").write_text(
        "归因链机制诊断约束。",
        encoding="utf-8",
    )
    (skills_root / "analyze-mental.md").write_text(
        "心智模式机制诊断约束。",
        encoding="utf-8",
    )
    (skills_root / "extract-pattern.md").write_text(
        "模式提取与复用约束。",
        encoding="utf-8",
    )
    (skills_root / "coach.md").write_text(
        "教练扩展约束。",
        encoding="utf-8",
    )


def test_run_api_dry_run_writes_preview(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"
    run_id = "run-api-dry"
    _write_bundle(jobs_root, run_id)

    rc = run_api(run_id, jobs_root, provider="anthropic", dry_run=True)
    assert rc == 0
    assert (jobs_root / run_id / "api_anthropic_preview.json").is_file()


def test_run_api_rejects_unsupported_provider(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"
    run_id = "run-api"
    _write_bundle(jobs_root, run_id)

    rc = run_api(run_id, jobs_root, provider="unsupported", dry_run=False)
    assert rc == 2


def test_run_api_without_key_fails_fast(tmp_path: Path, monkeypatch) -> None:
    jobs_root = tmp_path / "jobs"
    skills_root = tmp_path / "skills"
    run_id = "run-api-openai"
    _write_bundle(jobs_root, run_id)
    _write_skills(skills_root)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    rc = run_api(
        run_id,
        jobs_root,
        provider="openai",
        dry_run=False,
        skills_root=skills_root,
    )
    assert rc == 2


def test_run_api_claude_cli_provider_works_with_stubbed_cli(tmp_path: Path, monkeypatch) -> None:
    jobs_root = tmp_path / "jobs"
    skills_root = tmp_path / "skills"
    run_id = "run-claude-cli"
    _write_bundle(jobs_root, run_id)
    _write_skills(skills_root)

    def fake_subprocess_run(*args, **kwargs):
        stdout = json.dumps(
            {
                "result": json.dumps(
                    {
                        "schema_version": "session-mechanism.v1",
                        "session_id": "s-1",
                        "summary": "测试输出",
                        "what_happened": ["发生了澄清循环"],
                        "why": [
                            {
                                "hypothesis": "开场上下文不足",
                                "confidence": "0.72",
                                "evidence": [
                                    {
                                        "session_id": "s-1",
                                        "turn_id": "1",
                                        "snippet": "Please help",
                                    }
                                ],
                            }
                        ],
                        "interventions": [
                            {
                                "when": "新任务启动",
                                "do": "补充目标、边界、完成标准",
                                "expect": "减少澄清轮次",
                                "window": "next-10-sessions",
                            }
                        ],
                        "labels": ["kickoff-context-gap"],
                    },
                    ensure_ascii=False,
                )
            },
            ensure_ascii=False,
        )
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("skill_runtime.subprocess.run", fake_subprocess_run)

    rc = run_api(
        run_id,
        jobs_root,
        provider="claude_cli",
        dry_run=False,
        skills_root=skills_root,
    )
    assert rc == 0
    result_path = jobs_root / run_id / "api_claude_cli_results.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    session = payload["sessions"][0]
    assert session["why"][0]["confidence"] == 0.72
    assert session["why"][0]["evidence"][0]["turn_id"] == 1
    assert session["how_to_improve"][0]["trigger"] == "新任务启动"


def test_run_api_codex_cli_provider_works_with_stubbed_cli(tmp_path: Path, monkeypatch) -> None:
    jobs_root = tmp_path / "jobs"
    skills_root = tmp_path / "skills"
    run_id = "run-codex-cli"
    _write_bundle(jobs_root, run_id)
    _write_skills(skills_root)

    def fake_subprocess_run(*args, **kwargs):
        cmd = list(args[0])
        out_idx = cmd.index("--output-last-message")
        out_path = Path(cmd[out_idx + 1])
        out_path.write_text(
            json.dumps(
                {
                    "summary": "codex 测试输出",
                    "event": "出现澄清循环",
                    "hypothesis": "初始约束不足",
                    "confidence": "0.66",
                    "evidence": [
                        {
                            "session_id": "s-1",
                            "turn_id": "1",
                            "snippet": "Please help",
                        }
                    ],
                    "interventions": [
                        {
                            "when": "新任务启动",
                            "do": "先定义目标和边界",
                            "expect": "减少返工",
                            "window": "next-7-days",
                        }
                    ],
                    "labels": ["kickoff-context-gap"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("skill_runtime.subprocess.run", fake_subprocess_run)

    rc = run_api(
        run_id,
        jobs_root,
        provider="codex_cli",
        dry_run=False,
        skills_root=skills_root,
    )
    assert rc == 0
    result_path = jobs_root / run_id / "api_codex_cli_results.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    session = payload["sessions"][0]
    assert session["summary"] == "codex 测试输出"
    assert session["why"][0]["confidence"] == 0.66
    assert session["how_to_improve"][0]["action"] == "先定义目标和边界"


def test_run_incremental_api_dry_run_writes_preview(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"
    skills_root = tmp_path / "skills"
    run_id = "inc-api-dry"
    _write_skills(skills_root)
    payload = {
        "schema_version": "incremental-input.v1",
        "period_id": "rolling_30d",
        "coverage": {"sessions_total": 1, "sessions_with_mechanism": 1},
        "sessions": [],
    }
    rc, path = run_incremental_api(
        run_id,
        jobs_root,
        provider="claude_cli",
        dry_run=True,
        incremental_input=payload,
        skills_root=skills_root,
    )
    assert rc == 0
    assert path is None
    preview_path = jobs_root / run_id / "incremental_api_claude_cli_preview.json"
    assert preview_path.is_file()
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert "coach.md" in preview.get("skill_files", [])
