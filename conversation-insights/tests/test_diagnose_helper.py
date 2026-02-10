from __future__ import annotations

import json
from pathlib import Path

import diagnose_helper
import pytest
from conftest import make_conversation, write_json


def test_intermediate_commands_are_removed() -> None:
    for cmd in ("prepare", "run", "apply"):
        with pytest.raises(SystemExit):
            diagnose_helper.main([cmd])


def test_backfill_then_incremental_flow(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data" / "conversations"
    insights_session_dir = tmp_path / "data" / "insights" / "session"
    insights_incremental_dir = tmp_path / "data" / "insights" / "incremental"
    jobs_dir = tmp_path / "output" / "skill_jobs"
    skills_dir = tmp_path / "skills"

    data_dir.mkdir(parents=True, exist_ok=True)
    insights_session_dir.mkdir(parents=True, exist_ok=True)
    insights_incremental_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    conv = make_conversation(session_id="d-1", created_at="2026-02-06T10:00:00+00:00")
    write_json(data_dir / "d-1.json", conv)

    monkeypatch.setattr(diagnose_helper, "_DATA_DIR", data_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_SESSION_DIR", insights_session_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_INCREMENTAL_DIR", insights_incremental_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILL_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILLS_DIR", skills_dir)

    run_id = "run-test"

    def fake_run_api(
        run_id: str,
        jobs_root: Path,
        provider: str,
        dry_run: bool,
        *,
        skills_root: Path | None = None,
        model: str | None = None,
        timeout_sec: int = 90,
        allow_partial: bool = False,
        max_workers: int = 1,
    ) -> int:
        run_dir = jobs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_dir / f"api_{provider}_results.json"
        result_payload = {
            "schema_version": "session-mechanism-batch.v1",
            "run_id": run_id,
            "sessions": [
                {
                    "schema_version": "session-mechanism.v1",
                    "session_id": "d-1",
                    "created_at": "2026-02-06T10:00:00+00:00",
                    "week": "2026-W06",
                    "summary": "summary",
                    "what_happened": ["fact"],
                    "why": [
                        {
                            "hypothesis": "missing context",
                            "confidence": 0.7,
                            "evidence": [
                                {
                                    "session_id": "d-1",
                                    "turn_id": 1,
                                    "snippet": "Please debug this API issue",
                                }
                            ],
                        }
                    ],
                    "how_to_improve": [
                        {
                            "trigger": "new session",
                            "action": "state goal first",
                            "expected_gain": "better first pass",
                            "validation_window": "next-7-days",
                        }
                    ],
                    "labels": ["scope"],
                    "generated_by": {
                        "engine": "api",
                        "provider": "claude_cli",
                        "model": "skill",
                        "run_id": run_id,
                        "generated_at": "2026-02-06T11:00:00+00:00",
                    },
                }
            ],
        }
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    monkeypatch.setattr(diagnose_helper, "run_api", fake_run_api)

    rc_backfill = diagnose_helper.main(
        [
            "backfill",
            "--window",
            "30d",
            "--provider",
            "claude_cli",
            "--run-id",
            run_id,
        ]
    )
    assert rc_backfill == 0
    assert (insights_session_dir / "d-1.json").is_file()

    incremental_payload = {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "week": "rolling_30d",
        "generated_at": "2026-02-06T12:00:00+00:00",
        "source_run_id": run_id,
        "coverage": {
            "sessions_total": 1,
            "sessions_with_mechanism": 1,
        },
        "reports": [
            {
                "dimension": "incremental-root-causes",
                "layer": "L3",
                "title": "增量根因假设 - rolling_30d",
                "key_insights": "开场上下文不足导致澄清循环。",
                "detail_lines": [
                    "证据: d-1#T1 Please debug this API issue",
                    "动作: 开场写目标/边界/完成标准。",
                ],
                "conversations_analyzed": 1,
                "period": "rolling_30d",
                "date": "2026-02-06",
            }
        ],
    }
    incremental_result_path = tmp_path / "incremental-result.json"
    incremental_result_path.write_text(
        json.dumps(incremental_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rc_incremental = diagnose_helper.main(
        [
            "incremental",
            "--window",
            "30d",
            "--run-id",
            run_id,
            "--result-file",
            str(incremental_result_path),
        ]
    )
    assert rc_incremental == 0

    incremental_files = list(insights_incremental_dir.glob("*.json"))
    assert len(incremental_files) == 1
    payload = json.loads(incremental_files[0].read_text(encoding="utf-8"))
    assert payload["coverage"]["sessions_total"] >= payload["coverage"]["sessions_with_mechanism"]
    assert isinstance(payload["reports"], list)
    assert payload["reports"][0]["dimension"] == "incremental-root-causes"


def test_backfill_auto_apply_creates_missing_sidecar(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data" / "conversations"
    insights_session_dir = tmp_path / "data" / "insights" / "session"
    insights_incremental_dir = tmp_path / "data" / "insights" / "incremental"
    jobs_dir = tmp_path / "output" / "skill_jobs"
    skills_dir = tmp_path / "skills"

    data_dir.mkdir(parents=True, exist_ok=True)
    insights_session_dir.mkdir(parents=True, exist_ok=True)
    insights_incremental_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    conv = make_conversation(session_id="b-1", created_at="2026-02-07T10:00:00+00:00")
    write_json(data_dir / "b-1.json", conv)

    monkeypatch.setattr(diagnose_helper, "_DATA_DIR", data_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_SESSION_DIR", insights_session_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_INCREMENTAL_DIR", insights_incremental_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILL_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILLS_DIR", skills_dir)

    def fake_run_api(
        run_id: str,
        jobs_root: Path,
        provider: str,
        dry_run: bool,
        *,
        skills_root: Path | None = None,
        model: str | None = None,
        timeout_sec: int = 90,
        allow_partial: bool = False,
        max_workers: int = 1,
    ) -> int:
        run_dir = jobs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_dir / f"api_{provider}_results.json"
        payload = {
            "schema_version": "session-mechanism-batch.v1",
            "run_id": run_id,
            "sessions": [
                {
                    "schema_version": "session-mechanism.v1",
                    "session_id": "b-1",
                    "created_at": "2026-02-07T10:00:00+00:00",
                    "week": "2026-W06",
                    "summary": "自动回填",
                    "what_happened": ["发生了边界澄清"],
                    "why": [
                        {
                            "hypothesis": "开场上下文不足",
                            "confidence": 0.73,
                            "evidence": [
                                {
                                    "session_id": "b-1",
                                    "turn_id": 1,
                                    "snippet": "请帮我处理这个任务",
                                }
                            ],
                        }
                    ],
                    "how_to_improve": [
                        {
                            "trigger": "开始新任务时",
                            "action": "先写4行开场契约",
                            "expected_gain": "减少澄清轮次",
                            "validation_window": "next-10-sessions",
                        }
                    ],
                    "labels": ["kickoff-context-gap"],
                }
            ],
        }
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    monkeypatch.setattr(diagnose_helper, "run_api", fake_run_api)

    rc = diagnose_helper.main(
        [
            "backfill",
            "--window",
            "all-time",
            "--provider",
            "openai",
            "--run-id",
            "backfill-test",
        ]
    )
    assert rc == 0
    assert (insights_session_dir / "b-1.json").is_file()


def test_apply_allow_partial_skips_invalid_records(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data" / "conversations"
    insights_session_dir = tmp_path / "data" / "insights" / "session"
    insights_incremental_dir = tmp_path / "data" / "insights" / "incremental"
    jobs_dir = tmp_path / "output" / "skill_jobs"
    skills_dir = tmp_path / "skills"

    data_dir.mkdir(parents=True, exist_ok=True)
    insights_session_dir.mkdir(parents=True, exist_ok=True)
    insights_incremental_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(diagnose_helper, "_DATA_DIR", data_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_SESSION_DIR", insights_session_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_INCREMENTAL_DIR", insights_incremental_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILL_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILLS_DIR", skills_dir)

    run_id = "apply-partial"
    result_payload = {
        "schema_version": "session-mechanism-batch.v1",
        "run_id": run_id,
        "sessions": [
            {
                "schema_version": "session-mechanism.v1",
                "session_id": "ok-1",
                "created_at": "2026-02-07T10:00:00+00:00",
                "week": "2026-W06",
                "summary": "有效记录",
                "what_happened": ["事实"],
                "why": [
                    {
                        "hypothesis": "原因",
                        "confidence": 0.7,
                        "evidence": [
                            {
                                "session_id": "ok-1",
                                "turn_id": 1,
                                "snippet": "证据",
                            }
                        ],
                    }
                ],
                "how_to_improve": [
                    {
                        "trigger": "触发",
                        "action": "动作",
                        "expected_gain": "收益",
                        "validation_window": "next-7-days",
                    }
                ],
                "labels": ["valid"],
            },
            {
                "schema_version": "session-mechanism.v1",
                "session_id": "bad-1",
                "created_at": "2026-02-07T10:00:00+00:00",
                "week": "2026-W06",
                "summary": "",
                "what_happened": [],
                "why": [],
                "how_to_improve": [],
                "labels": [],
            },
        ],
    }
    result_path = tmp_path / "partial-result.json"
    result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rc = diagnose_helper._apply_session_results(
        run_id=run_id,
        result_path=result_path,
        allow_partial=True,
    )
    assert rc == 0
    assert (insights_session_dir / "ok-1.json").is_file()
    assert not (insights_session_dir / "bad-1.json").exists()
    assert (jobs_dir / run_id / "invalid_session_mechanisms.json").is_file()


def test_incremental_without_result_file_uses_skill_runtime(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data" / "conversations"
    insights_session_dir = tmp_path / "data" / "insights" / "session"
    insights_incremental_dir = tmp_path / "data" / "insights" / "incremental"
    jobs_dir = tmp_path / "output" / "skill_jobs"
    skills_dir = tmp_path / "skills"

    data_dir.mkdir(parents=True, exist_ok=True)
    insights_session_dir.mkdir(parents=True, exist_ok=True)
    insights_incremental_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    conv = make_conversation(session_id="inc-1", created_at="2026-02-07T10:00:00+00:00")
    write_json(data_dir / "inc-1.json", conv)
    session_payload = {
        "schema_version": "session-mechanism.v1",
        "session_id": "inc-1",
        "created_at": "2026-02-07T10:00:00+00:00",
        "week": "2026-W06",
        "summary": "summary",
        "what_happened": ["fact"],
        "why": [
            {
                "hypothesis": "missing context",
                "confidence": 0.7,
                "evidence": [
                    {"session_id": "inc-1", "turn_id": 1, "snippet": "Please help"}
                ],
            }
        ],
        "how_to_improve": [
            {
                "trigger": "new task",
                "action": "state constraints",
                "expected_gain": "fewer loops",
                "validation_window": "next-7-days",
            }
        ],
        "labels": ["kickoff-context-gap"],
        "generated_by": {
            "engine": "api",
            "provider": "claude_cli",
            "model": "sonnet",
            "run_id": "r1",
            "generated_at": "2026-02-07T10:00:00+00:00",
        },
    }
    write_json(insights_session_dir / "inc-1.json", session_payload)

    monkeypatch.setattr(diagnose_helper, "_DATA_DIR", data_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_SESSION_DIR", insights_session_dir)
    monkeypatch.setattr(diagnose_helper, "_INSIGHTS_INCREMENTAL_DIR", insights_incremental_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILL_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(diagnose_helper, "_SKILLS_DIR", skills_dir)

    def fake_run_incremental_api(*args, **kwargs):
        run_id = kwargs["run_id"]
        result_path = jobs_dir / run_id / "incremental_api_claude_cli_result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_payload = {
            "schema_version": "incremental-mechanism.v1",
            "period_id": "rolling_30d",
            "week": "rolling_30d",
            "generated_at": "2026-02-07T11:00:00+00:00",
            "source_run_id": run_id,
            "coverage": {"sessions_total": 1, "sessions_with_mechanism": 1},
            "reports": [
                {
                    "dimension": "incremental-root-causes",
                    "layer": "L3",
                    "title": "增量根因假设 - rolling_30d",
                    "key_insights": "开场上下文不足导致首轮返工。",
                    "detail_lines": [
                        "证据: inc-1#T1 Please help",
                        "动作: 开场先写目标/边界/完成标准。",
                    ],
                    "conversations_analyzed": 1,
                    "period": "rolling_30d",
                    "date": "2026-02-07",
                }
            ],
        }
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0, result_path

    monkeypatch.setattr(diagnose_helper, "run_incremental_api", fake_run_incremental_api)

    rc = diagnose_helper.main(
        [
            "incremental",
            "--window",
            "30d",
            "--run-id",
            "inc-run",
        ]
    )
    assert rc == 0
    files = sorted(insights_incremental_dir.glob("*.json"))
    assert files
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "incremental-mechanism.v1"
    assert payload["period_id"] == "rolling_30d"
