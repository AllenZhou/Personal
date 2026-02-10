from __future__ import annotations

from pathlib import Path

from conftest import make_conversation, write_json
from ingest_claude_code import detect_language as detect_language_claude
from ingest_codex import detect_language as detect_language_codex
from local_loader import get_conversation, load_conversations


def test_local_loader_filters_and_sorting(tmp_path: Path) -> None:
    conv1 = make_conversation(session_id="a", source="chatgpt", created_at="2026-02-01T00:00:00+00:00")
    conv2 = make_conversation(session_id="b", source="codex", created_at="2026-02-03T00:00:00+00:00")
    conv3 = make_conversation(session_id="c", source="chatgpt", created_at="2026-02-02T00:00:00+00:00")

    write_json(tmp_path / "a.json", conv1)
    write_json(tmp_path / "b.json", conv2)
    write_json(tmp_path / "c.json", conv3)

    loaded = load_conversations(str(tmp_path), source="chatgpt")
    assert [c["session_id"] for c in loaded] == ["c", "a"]

    filtered = load_conversations(str(tmp_path), since="2026-02-02", until="2026-02-03")
    assert [c["session_id"] for c in filtered] == ["b", "c"]


def test_local_loader_skips_malformed_json(tmp_path: Path) -> None:
    write_json(tmp_path / "ok.json", make_conversation())
    (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")

    loaded = load_conversations(str(tmp_path))
    assert len(loaded) == 1


def test_get_conversation_by_id(tmp_path: Path) -> None:
    conv = make_conversation(session_id="lookup-id")
    write_json(tmp_path / "lookup-id.json", conv)

    loaded = get_conversation("lookup-id", str(tmp_path))
    assert loaded is not None
    assert loaded["session_id"] == "lookup-id"


def test_language_detection_contract() -> None:
    assert detect_language_claude("请帮我修复这个 bug") == "zh"
    assert detect_language_codex("Please fix this bug") == "en"
    mixed = detect_language_codex("Fix 这个 bug")
    assert mixed in {"mixed", "en", "zh"}
