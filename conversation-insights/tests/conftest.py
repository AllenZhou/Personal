from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

TESTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def make_conversation(
    session_id: str = "test-001",
    source: str = "claude_code",
    created_at: str = "2026-02-01T10:00:00+00:00",
) -> Dict[str, Any]:
    return {
        "schema_version": "1.2",
        "session_id": session_id,
        "source": source,
        "model": "test-model",
        "title": "test title",
        "created_at": created_at,
        "project_path": None,
        "git_branch": None,
        "turns": [
            {
                "turn_id": 0,
                "timestamp": created_at,
                "user_message": {
                    "content": "Please debug this API issue",
                    "word_count": 6,
                    "language": "en",
                    "has_code": False,
                    "has_file_reference": False,
                },
                "assistant_response": {
                    "content": "I will inspect the error and suggest fixes.",
                    "word_count": 8,
                    "tool_uses": [{"tool_name": "Read", "success": True, "input": None}],
                    "has_thinking": False,
                },
                "corrections": [],
            }
        ],
        "metadata": {
            "total_turns": 1,
            "total_tool_uses": 1,
            "primary_language": "en",
            "detected_domains": ["backend"],
            "has_sidechains": False,
            "has_file_changes": False,
            "token_count": None,
            "file_changes": None,
            "llm_metadata": {
                "version": "1.0",
                "extracted_at": "2026-02-01T10:00:00+00:00",
                "model_used": "heuristic-v1",
                "conversation_intent": "debug API issue",
                "task_type": "debugging",
                "actual_domains": ["backend.api"],
                "difficulty": 4,
                "outcome": "resolved",
                "key_topics": ["api", "debug"],
                "prompt_quality": {
                    "score": 70,
                    "strengths": ["clear goal"],
                    "weaknesses": [],
                },
                "correction_analysis": [],
                "cognitive_patterns": [],
                "conversation_summary": "Debugged an API issue and resolved it.",
            },
        },
    }


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
