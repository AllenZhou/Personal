from __future__ import annotations

from diagnose_helper import validate_incremental_mechanism, validate_session_mechanism


def _valid_session() -> dict:
    return {
        "schema_version": "session-mechanism.v1",
        "session_id": "s-1",
        "created_at": "2026-02-06T10:00:00+00:00",
        "week": "2026-W06",
        "summary": "summary",
        "what_happened": ["fact"],
        "why": [
            {
                "hypothesis": "hyp",
                "confidence": 0.7,
                "evidence": [
                    {
                        "session_id": "s-1",
                        "turn_id": 1,
                        "snippet": "evidence text",
                    }
                ],
            }
        ],
        "how_to_improve": [
            {
                "trigger": "trigger",
                "action": "action",
                "expected_gain": "gain",
                "validation_window": "next-7-days",
            }
        ],
        "labels": ["scope"],
        "generated_by": {
            "engine": "api",
            "provider": "claude_cli",
            "model": "skill",
            "run_id": "run-1",
            "generated_at": "2026-02-06T10:00:00+00:00",
        },
    }


def _valid_incremental() -> dict:
    return {
        "schema_version": "incremental-mechanism.v1",
        "period_id": "rolling_30d",
        "week": "rolling_30d",
        "generated_at": "2026-02-06T11:00:00+00:00",
        "source_run_id": "run-1",
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
                    "现象：首轮任务边界不清，出现往返澄清。",
                    "改进：开场写目标、边界、完成标准。",
                ],
                "conversations_analyzed": 1,
                "period": "rolling_30d",
                "date": "2026-02-06",
            }
        ],
    }


def test_validate_session_mechanism_accepts_valid_payload() -> None:
    assert validate_session_mechanism(_valid_session()) == []


def test_validate_session_mechanism_requires_evidence() -> None:
    payload = _valid_session()
    payload["why"][0]["evidence"] = []
    errors = validate_session_mechanism(payload)
    assert any("evidence" in err for err in errors)


def test_validate_session_mechanism_blocks_manual_generated_by() -> None:
    payload = _valid_session()
    payload["generated_by"]["engine"] = "manual"
    payload["generated_by"]["provider"] = "skill-manual"
    payload["generated_by"]["run_id"] = "replace-mock-sidecars-20260207"
    errors = validate_session_mechanism(payload)
    assert any("generated_by is blocked" in err for err in errors)


def test_validate_incremental_mechanism_accepts_valid_payload() -> None:
    assert validate_incremental_mechanism(_valid_incremental()) == []


def test_validate_incremental_mechanism_requires_reports() -> None:
    payload = _valid_incremental()
    payload["reports"] = []
    errors = validate_incremental_mechanism(payload)
    assert any("reports" in err for err in errors)


def test_validate_incremental_mechanism_rejects_invalid_coverage_ratio() -> None:
    payload = _valid_incremental()
    payload["coverage"]["sessions_total"] = 1
    payload["coverage"]["sessions_with_mechanism"] = 2
    errors = validate_incremental_mechanism(payload)
    assert any("cannot exceed" in err for err in errors)


def test_validate_incremental_mechanism_rejects_unknown_dimension() -> None:
    payload = _valid_incremental()
    payload["reports"][0]["dimension"] = "incremental-unknown"
    errors = validate_incremental_mechanism(payload)
    assert any("dimension must be one of" in err for err in errors)


def test_validate_incremental_mechanism_rejects_layer_mismatch() -> None:
    payload = _valid_incremental()
    payload["reports"][0]["dimension"] = "incremental-task-stratification"
    payload["reports"][0]["layer"] = "L3"
    errors = validate_incremental_mechanism(payload)
    assert any("layer must be 'L2'" in err for err in errors)
