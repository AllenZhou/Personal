from __future__ import annotations

import json
from pathlib import Path

from auto_enricher import batch_enrich, enrich_conversation_heuristic
from conftest import make_conversation, write_json
from enrich_helper import build_conversation_digest


REQUIRED_FIELDS = {
    "conversation_intent",
    "task_type",
    "actual_domains",
    "difficulty",
    "outcome",
    "key_topics",
    "prompt_quality",
    "correction_analysis",
    "cognitive_patterns",
    "conversation_summary",
}


def test_enrich_conversation_heuristic_writes_metadata() -> None:
    conv = make_conversation()
    conv["metadata"].pop("llm_metadata", None)
    conv["schema_version"] = "1.1"

    enriched = enrich_conversation_heuristic(conv)
    meta = enriched["metadata"]["llm_metadata"]

    assert enriched["schema_version"] == "1.2"
    assert REQUIRED_FIELDS.issubset(set(meta.keys()))
    assert isinstance(meta["prompt_quality"], dict)


def test_batch_enrich_updates_files(tmp_path: Path) -> None:
    conv = make_conversation(session_id="enrich-me")
    conv["metadata"].pop("llm_metadata", None)
    write_json(tmp_path / "enrich-me.json", conv)

    stats = batch_enrich(str(tmp_path), force=False)
    assert stats["enriched"] == 1
    assert stats["errors"] == 0

    updated = json.loads((tmp_path / "enrich-me.json").read_text(encoding="utf-8"))
    assert "llm_metadata" in updated["metadata"]


def test_build_conversation_digest_contains_core_sections() -> None:
    conv = make_conversation(session_id="digest-1", source="codex")
    digest = build_conversation_digest(conv)

    assert "Source:" in digest
    assert "Turns:" in digest
    assert "Conversation Flow" in digest
