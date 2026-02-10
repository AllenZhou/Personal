#!/usr/bin/env python3
"""Runtime helpers for Skill-first diagnosis workflows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

_INCREMENTAL_EXTENSION_SKILL_FILES: Tuple[str, ...] = (
    "coach.md",
)
_MAX_BASE_INCREMENTAL_SKILL_CHARS = 1400
_MAX_EXTENSION_SKILL_CHARS = 180
_INCREMENTAL_CHUNK_SIZE = 24
_CODEX_CLI_REASONING_EFFORT = "medium"


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _codex_cli_workdir() -> str:
    """Return an isolated workdir to avoid repository-level agent instructions."""
    path = Path(tempfile.gettempdir()) / "conversation-insights-codex-runtime"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON file into a dictionary."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON with UTF-8 and deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _extract_json_payload(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from model text output."""
    content = str(text or "").strip()
    if not content:
        raise ValueError("empty model output")

    # Fast path when the whole response is JSON.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(content):
        if ch not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(content[idx:])
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found in model output")


def _load_skill_prompt(skills_root: Path) -> str:
    """Load diagnose-session skill prompt text."""
    path = skills_root / "diagnose-session.md"
    if not path.is_file():
        raise FileNotFoundError(f"skill prompt missing: {path}")
    return path.read_text(encoding="utf-8")


def _load_incremental_skill_prompt(skills_root: Path) -> str:
    """Load diagnose-incremental skill prompt text."""
    path = skills_root / "diagnose-incremental.md"
    if not path.is_file():
        raise FileNotFoundError(f"skill prompt missing: {path}")
    return path.read_text(encoding="utf-8")


def _load_incremental_skill_bundle(skills_root: Path) -> Tuple[str, List[str]]:
    """Load base incremental skill plus required extension skills."""
    used_files: List[str] = ["diagnose-incremental.md"]
    missing_files: List[str] = []

    base_prompt = _compact_skill_text(
        _load_incremental_skill_prompt(skills_root).strip(),
        limit_chars=_MAX_BASE_INCREMENTAL_SKILL_CHARS,
    )
    extension_sections: List[str] = []

    for filename in _INCREMENTAL_EXTENSION_SKILL_FILES:
        path = skills_root / filename
        if not path.is_file():
            missing_files.append(str(path))
            continue
        used_files.append(filename)
        raw_text = path.read_text(encoding="utf-8").strip()
        compact_text = _compact_skill_text(raw_text, limit_chars=_MAX_EXTENSION_SKILL_CHARS)
        extension_sections.append(
            "\n".join(
                [
                    f"## 扩展技能约束（{filename}）",
                    compact_text,
                ]
            )
        )

    if missing_files:
        raise FileNotFoundError(
            "required incremental extension skill(s) missing: "
            + ", ".join(missing_files)
        )

    composite_prompt = "\n\n".join(
        [
            base_prompt,
            "## 组合执行约束",
            "在满足 diagnose-incremental 主契约的前提下，必须同时遵循以下扩展技能约束：",
            *extension_sections,
        ]
    ).strip()
    return composite_prompt, used_files


def _compact_skill_text(text: str, *, limit_chars: int) -> str:
    """Keep essential non-empty lines while limiting prompt size."""
    if not text:
        return ""
    lines = [line.rstrip() for line in str(text).splitlines() if line.strip()]
    compact = "\n".join(lines)
    if len(compact) <= limit_chars:
        return compact
    return compact[:limit_chars].rstrip() + "\n...（运行时已截断，仅保留关键约束）"


def _post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """POST JSON and return decoded JSON response."""
    req = request.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc}") from exc


def _runtime_system_prompt() -> str:
    """Generic runtime guardrail: enforce JSON-only output."""
    return (
        "你是 Skill 运行时执行器。"
        "必须严格遵循用户提供的 Skill 文本。"
        "仅输出一个 JSON object。"
        "不要输出 markdown、解释或额外前后缀。"
    )


def _build_skill_user_prompt(
    *,
    skill_prompt: str,
    input_name: str,
    input_payload: Dict[str, Any],
    output_schema: str,
) -> str:
    """Build provider-agnostic user prompt from external Skill + input payload."""
    return (
        "请严格执行以下 Skill，按其约束生成结果。\n"
        "输出必须是单个 JSON object。\n\n"
        f"[Skill]\n{skill_prompt}\n\n"
        f"[{input_name}]\n{json.dumps(input_payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"[TargetSchema]\n{output_schema}\n"
    )


def _openai_infer_session(
    *,
    api_key: str,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call OpenAI Chat Completions API for one session digest."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="SessionDigestV1",
        input_payload=digest,
        output_schema="SessionMechanismV1",
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _runtime_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = _post_json(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        payload=payload,
        timeout_sec=timeout_sec,
    )
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    else:
        text = str(content or "")
    return _extract_json_payload(text)


def _anthropic_infer_session(
    *,
    api_key: str,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call Anthropic Messages API for one session digest."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="SessionDigestV1",
        input_payload=digest,
        output_schema="SessionMechanismV1",
    )
    payload = {
        "model": model,
        "max_tokens": 2000,
        "temperature": 0.2,
        "system": _runtime_system_prompt(),
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_prompt}],
            }
        ],
    }
    response = _post_json(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        payload=payload,
        timeout_sec=timeout_sec,
    )
    blocks = response.get("content") or []
    text = "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and str(block.get("type") or "") == "text"
    )
    return _extract_json_payload(text)


def _openai_infer_incremental(
    *,
    api_key: str,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call OpenAI Chat Completions API for one incremental input payload."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="IncrementalInputV1",
        input_payload=incremental_input,
        output_schema="IncrementalMechanismV1",
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _runtime_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = _post_json(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        payload=payload,
        timeout_sec=timeout_sec,
    )
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    else:
        text = str(content or "")
    return _extract_json_payload(text)


def _anthropic_infer_incremental(
    *,
    api_key: str,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call Anthropic Messages API for one incremental input payload."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="IncrementalInputV1",
        input_payload=incremental_input,
        output_schema="IncrementalMechanismV1",
    )
    payload = {
        "model": model,
        "max_tokens": 3000,
        "temperature": 0.2,
        "system": _runtime_system_prompt(),
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_prompt}],
            }
        ],
    }
    response = _post_json(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        payload=payload,
        timeout_sec=timeout_sec,
    )
    blocks = response.get("content") or []
    text = "".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and str(block.get("type") or "") == "text"
    )
    return _extract_json_payload(text)


def _default_model(provider: str) -> str:
    """Return default model per provider."""
    if provider == "anthropic":
        return "claude-3-5-sonnet-latest"
    if provider == "openai":
        return "gpt-4o-mini"
    if provider == "claude_cli":
        return "sonnet"
    if provider == "codex_cli":
        return "gpt-5-codex"
    raise ValueError(f"unsupported provider: {provider}")


def _extract_cli_json_response(stdout: str) -> Dict[str, Any]:
    """Parse Claude CLI JSON output and extract target JSON payload."""
    parsed = json.loads(str(stdout or "").strip())
    if isinstance(parsed, dict):
        # Common Claude CLI JSON output envelope.
        result = parsed.get("result")
        if isinstance(result, str) and result.strip():
            return _extract_json_payload(result)

        content = parsed.get("content")
        if isinstance(content, list):
            text = "".join(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and str(block.get("type") or "") == "text"
            )
            if text.strip():
                return _extract_json_payload(text)

        # Fallback: the object itself may already be the target payload.
        if parsed.get("schema_version") == "session-mechanism.v1" or parsed.get("session_id"):
            return parsed
    return _extract_json_payload(str(stdout or ""))


def _as_non_empty_text(value: Any) -> str:
    """Normalize any value into compact non-empty text."""
    text = " ".join(str(value or "").strip().split())
    return text


def _coerce_turn_id(value: Any) -> Optional[int]:
    """Coerce turn id into positive int when possible."""
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            parsed = int(raw)
            return parsed if parsed > 0 else None
    return None


def _coerce_confidence(value: Any) -> Optional[float]:
    """Coerce confidence into float when possible."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _normalize_evidence_list(value: Any) -> List[Dict[str, Any]]:
    """Normalize evidence list and drop invalid entries."""
    if isinstance(value, dict):
        entries = [value]
    elif isinstance(value, list):
        entries = [item for item in value if isinstance(item, dict)]
    else:
        entries = []

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        session_id = _as_non_empty_text(entry.get("session_id"))
        turn_id = _coerce_turn_id(entry.get("turn_id"))
        snippet = _as_non_empty_text(entry.get("snippet"))
        if not session_id or turn_id is None or not snippet:
            continue
        item: Dict[str, Any] = {
            "session_id": session_id,
            "turn_id": turn_id,
            "snippet": snippet,
        }
        tier = _as_non_empty_text(entry.get("tier"))
        if tier in {"primary", "supporting"}:
            item["tier"] = tier
        normalized.append(item)
    return normalized


def _first_non_empty_text(payload: Dict[str, Any], keys: List[str]) -> str:
    """Pick first non-empty string field from payload."""
    for key in keys:
        value = _as_non_empty_text(payload.get(key))
        if value:
            return value
    return ""


def _normalize_actions(value: Any) -> List[Dict[str, str]]:
    """Normalize action list to contract keys."""
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, dict)]
    else:
        items = []

    normalized: List[Dict[str, str]] = []
    for item in items:
        trigger = _first_non_empty_text(item, ["trigger", "when", "condition"])
        action = _first_non_empty_text(item, ["action", "do", "step"])
        expected_gain = _first_non_empty_text(item, ["expected_gain", "expect", "benefit", "outcome"])
        validation_window = _first_non_empty_text(item, ["validation_window", "validate", "window"])
        normalized.append(
            {
                "trigger": trigger,
                "action": action,
                "expected_gain": expected_gain,
                "validation_window": validation_window,
            }
        )
    return normalized


def _sanitize_session_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize model output into best-effort SessionMechanismV1 shape."""
    item = dict(raw or {})

    what_happened_raw = item.get("what_happened")
    what_happened: List[str] = []
    if isinstance(what_happened_raw, list):
        what_happened = [_as_non_empty_text(text) for text in what_happened_raw]
        what_happened = [text for text in what_happened if text]
    if not what_happened:
        for key in ("event", "outcome", "observed_behavior", "observation", "phenomenon"):
            text = _as_non_empty_text(item.get(key))
            if text:
                what_happened.append(text)
        if "snippet" in item:
            text = _as_non_empty_text(item.get("snippet"))
            if text:
                what_happened.append(text)
    item["what_happened"] = what_happened

    summary = _as_non_empty_text(item.get("summary"))
    if not summary and what_happened:
        summary = what_happened[0]
    item["summary"] = summary

    why_raw = item.get("why")
    why_items: List[Dict[str, Any]] = []
    if isinstance(why_raw, list):
        source_items = [entry for entry in why_raw if isinstance(entry, dict)]
    elif isinstance(why_raw, dict):
        source_items = [why_raw]
    else:
        source_items = []

    if not source_items and _as_non_empty_text(item.get("hypothesis")):
        source_items = [
            {
                "hypothesis": item.get("hypothesis"),
                "confidence": item.get("confidence"),
                "evidence": item.get("evidence"),
            }
        ]

    for entry in source_items:
        hypothesis = _first_non_empty_text(entry, ["hypothesis", "root_cause", "reasoning"])
        confidence = _coerce_confidence(entry.get("confidence"))
        evidence = _normalize_evidence_list(entry.get("evidence"))
        if not evidence and source_items and "evidence" in item:
            evidence = _normalize_evidence_list(item.get("evidence"))
        why_item: Dict[str, Any] = {"hypothesis": hypothesis, "evidence": evidence}
        if confidence is not None:
            why_item["confidence"] = confidence
        why_items.append(why_item)
    item["why"] = why_items

    actions = _normalize_actions(item.get("how_to_improve"))
    if not actions:
        for fallback_key in ("interventions", "recommendations", "actions"):
            actions = _normalize_actions(item.get(fallback_key))
            if actions:
                break
    item["how_to_improve"] = actions

    labels = item.get("labels")
    if isinstance(labels, str):
        item["labels"] = [labels.strip()] if labels.strip() else []
    elif isinstance(labels, list):
        item["labels"] = [_as_non_empty_text(label) for label in labels if _as_non_empty_text(label)]
    elif labels is None:
        item["labels"] = []
    else:
        item["labels"] = []

    return item


def _is_retryable_claude_error(exc: Exception) -> bool:
    """Return whether a Claude CLI error is worth retrying."""
    text = str(exc or "").lower()
    return (
        "timed out" in text
        or "failed rc=1" in text
        or "no json object found" in text
    )


def _is_retryable_codex_error(exc: Exception) -> bool:
    """Return whether a Codex CLI error is worth retrying."""
    text = str(exc or "").lower()
    return (
        "timed out" in text
        or "failed rc=1" in text
        or "no json object found" in text
        or "rate limit" in text
    )


def _infer_claude_with_retries(
    *,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """Run Claude CLI inference with retry for transient failures."""
    attempt = 0
    while True:
        try:
            return _claude_cli_infer_session(
                model=model,
                skill_prompt=skill_prompt,
                digest=digest,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_claude_error(exc):
                raise
            time.sleep(min(2 ** attempt, 4))
            attempt += 1


def _infer_codex_with_retries(
    *,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """Run Codex CLI inference with retry for transient failures."""
    attempt = 0
    while True:
        try:
            return _codex_cli_infer_session(
                model=model,
                skill_prompt=skill_prompt,
                digest=digest,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_codex_error(exc):
                raise
            time.sleep(min(2 ** attempt, 4))
            attempt += 1


def _infer_incremental_claude_with_retries(
    *,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """Run Claude CLI incremental inference with retry for transient failures."""
    attempt = 0
    while True:
        try:
            return _claude_cli_infer_incremental(
                model=model,
                skill_prompt=skill_prompt,
                incremental_input=incremental_input,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_claude_error(exc):
                raise
            time.sleep(min(2 ** attempt, 4))
            attempt += 1


def _infer_incremental_codex_with_retries(
    *,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """Run Codex CLI incremental inference with retry for transient failures."""
    attempt = 0
    while True:
        try:
            return _codex_cli_infer_incremental(
                model=model,
                skill_prompt=skill_prompt,
                incremental_input=incremental_input,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            if attempt >= max_retries or not _is_retryable_codex_error(exc):
                raise
            time.sleep(min(2 ** attempt, 4))
            attempt += 1


def _claude_cli_infer_session(
    *,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call local Claude CLI for one session digest."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="SessionDigestV1",
        input_payload=digest,
        output_schema="SessionMechanismV1",
    )

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--model",
        model,
        "--system-prompt",
        _runtime_system_prompt(),
        user_prompt,
    ]
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(timeout_sec, 10),
        check=False,
    )
    if completed.returncode != 0:
        stderr = str(completed.stderr or "").strip()
        raise RuntimeError(f"claude_cli failed rc={completed.returncode}: {stderr[:500]}")
    return _extract_cli_json_response(completed.stdout)


def _codex_cli_infer_session(
    *,
    model: str,
    skill_prompt: str,
    digest: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call local Codex CLI for one session digest."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="SessionDigestV1",
        input_payload=digest,
        output_schema="SessionMechanismV1",
    )

    output_fd, output_path_raw = tempfile.mkstemp(prefix="codex-last-msg-", suffix=".txt")
    os.close(output_fd)
    output_path = Path(output_path_raw)
    try:
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            _codex_cli_workdir(),
            "--sandbox",
            "workspace-write",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{_CODEX_CLI_REASONING_EFFORT}"',
            "--output-last-message",
            str(output_path),
            user_prompt,
        ]
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_sec, 10),
            check=False,
        )
        if completed.returncode != 0:
            stderr = str(completed.stderr or "").strip()
            stdout = str(completed.stdout or "").strip()
            hint = stderr or stdout
            raise RuntimeError(f"codex_cli failed rc={completed.returncode}: {hint[:500]}")

        if not output_path.is_file():
            raise RuntimeError("codex_cli finished without output-last-message file")

        text = output_path.read_text(encoding="utf-8", errors="replace")
        return _extract_json_payload(text)
    finally:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass


def _claude_cli_infer_incremental(
    *,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call local Claude CLI for incremental mechanism inference."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="IncrementalInputV1",
        input_payload=incremental_input,
        output_schema="IncrementalMechanismV1",
    )

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--model",
        model,
        "--system-prompt",
        _runtime_system_prompt(),
        user_prompt,
    ]
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(timeout_sec, 10),
        check=False,
    )
    if completed.returncode != 0:
        stderr = str(completed.stderr or "").strip()
        raise RuntimeError(f"claude_cli incremental failed rc={completed.returncode}: {stderr[:500]}")
    return _extract_cli_json_response(completed.stdout)


def _codex_cli_infer_incremental(
    *,
    model: str,
    skill_prompt: str,
    incremental_input: Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Call local Codex CLI for incremental mechanism inference."""
    user_prompt = _build_skill_user_prompt(
        skill_prompt=skill_prompt,
        input_name="IncrementalInputV1",
        input_payload=incremental_input,
        output_schema="IncrementalMechanismV1",
    )

    output_fd, output_path_raw = tempfile.mkstemp(prefix="codex-incremental-", suffix=".txt")
    os.close(output_fd)
    output_path = Path(output_path_raw)
    try:
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            _codex_cli_workdir(),
            "--sandbox",
            "workspace-write",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{_CODEX_CLI_REASONING_EFFORT}"',
            "--output-last-message",
            str(output_path),
            user_prompt,
        ]
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_sec, 10),
            check=False,
        )
        if completed.returncode != 0:
            stderr = str(completed.stderr or "").strip()
            stdout = str(completed.stdout or "").strip()
            hint = stderr or stdout
            raise RuntimeError(f"codex_cli incremental failed rc={completed.returncode}: {hint[:500]}")

        if not output_path.is_file():
            raise RuntimeError("codex_cli incremental finished without output-last-message file")

        text = output_path.read_text(encoding="utf-8", errors="replace")
        return _extract_json_payload(text)
    finally:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass


def _normalize_session_output(
    *,
    raw: Dict[str, Any],
    digest: Dict[str, Any],
    run_id: str,
    provider: str,
    model: str,
    engine: str,
) -> Dict[str, Any]:
    """Normalize model output into SessionMechanismV1 envelope."""
    item = _sanitize_session_output(raw)
    session_id = str(digest.get("session_id") or "")
    created_at = str(digest.get("created_at") or "")
    week = str(digest.get("week") or "")
    period_id = str(digest.get("period_id") or week)

    item["schema_version"] = "session-mechanism.v1"
    item["session_id"] = session_id
    item["created_at"] = created_at
    if week:
        item["week"] = week
    if period_id:
        item["period_id"] = period_id
    item["generated_by"] = {
        "engine": engine,
        "provider": provider,
        "model": model,
        "run_id": run_id,
        "generated_at": _now_iso(),
    }
    return item


def load_run_bundle(run_id: str, jobs_root: Path) -> Dict[str, Any]:
    """Load a diagnose run bundle from output/skill_jobs."""
    bundle_path = jobs_root / run_id / "session_digests.json"
    if not bundle_path.is_file():
        raise FileNotFoundError(f"run bundle not found: {bundle_path}")
    return _read_json(bundle_path)


def run_api(
    run_id: str,
    jobs_root: Path,
    provider: str,
    dry_run: bool,
    *,
    skills_root: Optional[Path] = None,
    model: Optional[str] = None,
    timeout_sec: int = 90,
    allow_partial: bool = False,
    max_workers: int = 1,
) -> int:
    """Run API-mode diagnosis.

    Provider behavior:
    - `claude_cli`: local Claude CLI execution (uses local login/subscription).
    - `codex_cli`: local Codex CLI execution (uses local login/subscription).
    - `openai`/`anthropic`: real API call; requires API key env vars.
    """
    run_dir = jobs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if provider not in {"claude_cli", "codex_cli", "openai", "anthropic"}:
        print(f"ERROR: unsupported provider: {provider}", file=sys.stderr)
        return 2

    bundle = load_run_bundle(run_id, jobs_root)
    sessions = bundle.get("sessions", [])
    try:
        selected_model = model or _default_model(provider)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    preview_path = run_dir / f"api_{provider}_preview.json"
    preview_payload = {
        "schema_version": "diagnose-api-preview.v1",
        "run_id": run_id,
        "provider": provider,
        "model": selected_model,
        "dry_run": dry_run,
        "session_count": len(sessions),
        "generated_at": _now_iso(),
        "note": "API execution preview. Non-dry-run requires valid provider credentials.",
    }
    _write_json(preview_path, preview_payload)

    if dry_run:
        print(f"[diagnose-run] api dry-run preview: {preview_path}")
        return 0

    try:
        skill_prompt = _load_skill_prompt(skills_root or (jobs_root.parent / "skills"))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if provider in {"claude_cli", "codex_cli"}:
        results: List[tuple[int, Dict[str, Any]]] = []
        errors_payload: List[Dict[str, Any]] = []
        session_items = [
            (idx, digest)
            for idx, digest in enumerate(sessions, start=1)
            if str(digest.get("session_id") or "")
        ]
        total_sessions = len(session_items)
        if total_sessions == 0:
            print("ERROR: no valid sessions in run bundle", file=sys.stderr)
            return 1

        infer_fn = _infer_claude_with_retries if provider == "claude_cli" else _infer_codex_with_retries
        workers = max(1, int(max_workers or 1))
        if workers == 1:
            for completed, (idx, digest) in enumerate(session_items, start=1):
                session_id = str(digest.get("session_id") or "")
                if completed == 1 or completed % 10 == 0 or completed == total_sessions:
                    print(
                        f"[diagnose-run] provider={provider} progress={completed}/{total_sessions}"
                    )
                try:
                    raw = infer_fn(
                        model=selected_model,
                        skill_prompt=skill_prompt,
                        digest=digest,
                        timeout_sec=timeout_sec,
                    )
                    normalized = _normalize_session_output(
                        raw=raw,
                        digest=digest,
                        run_id=run_id,
                        provider=provider,
                        model=selected_model,
                        engine="api",
                    )
                    results.append((idx, normalized))
                except Exception as exc:
                    errors_payload.append({"session_id": session_id, "error": str(exc)})
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(
                        infer_fn,
                        model=selected_model,
                        skill_prompt=skill_prompt,
                        digest=digest,
                        timeout_sec=timeout_sec,
                    ): (idx, digest)
                    for idx, digest in session_items
                }
                completed = 0
                for future in as_completed(future_map):
                    completed += 1
                    idx, digest = future_map[future]
                    session_id = str(digest.get("session_id") or "")
                    if completed == 1 or completed % 10 == 0 or completed == total_sessions:
                        print(
                            f"[diagnose-run] provider={provider} progress={completed}/{total_sessions}"
                        )
                    try:
                        raw = future.result()
                        normalized = _normalize_session_output(
                            raw=raw,
                            digest=digest,
                            run_id=run_id,
                            provider=provider,
                            model=selected_model,
                            engine="api",
                        )
                        results.append((idx, normalized))
                    except Exception as exc:
                        errors_payload.append({"session_id": session_id, "error": str(exc)})

        results.sort(key=lambda item: item[0])
        ordered_results = [item[1] for item in results]

        result_payload = {
            "schema_version": "session-mechanism-batch.v1",
            "run_id": run_id,
            "sessions": ordered_results,
        }
        result_path = run_dir / f"api_{provider}_results.json"
        _write_json(result_path, result_payload)
        if errors_payload:
            _write_json(
                run_dir / f"api_{provider}_errors.json",
                {
                    "schema_version": "diagnose-api-errors.v1",
                    "run_id": run_id,
                    "provider": provider,
                    "model": selected_model,
                    "failed_sessions": errors_payload,
                },
            )
        print(f"[diagnose-run] api preview: {preview_path}")
        print(f"[diagnose-run] api results: {result_path}")
        if errors_payload:
            print(f"[diagnose-run] api failed_sessions={len(errors_payload)}")
        if errors_payload and not allow_partial:
            print(
                "ERROR: partial API failures detected; use --allow-partial only when explicitly accepted",
                file=sys.stderr,
            )
            return 1
        if not results:
            print("ERROR: no session mechanisms generated", file=sys.stderr)
            return 1
        return 0

    key_env = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    api_key = os.getenv(key_env, "").strip()
    if not api_key:
        print(
            f"ERROR: {key_env} is not set",
            file=sys.stderr,
        )
        return 2

    results: List[tuple[int, Dict[str, Any]]] = []
    errors_payload: List[Dict[str, Any]] = []
    session_items = [
        (idx, digest)
        for idx, digest in enumerate(sessions, start=1)
        if str(digest.get("session_id") or "")
    ]
    total_sessions = len(session_items)
    workers = max(1, int(max_workers or 1))

    def infer_remote(digest: Dict[str, Any]) -> Dict[str, Any]:
        if provider == "openai":
            return _openai_infer_session(
                api_key=api_key,
                model=selected_model,
                skill_prompt=skill_prompt,
                digest=digest,
                timeout_sec=timeout_sec,
            )
        return _anthropic_infer_session(
            api_key=api_key,
            model=selected_model,
            skill_prompt=skill_prompt,
            digest=digest,
            timeout_sec=timeout_sec,
        )

    if workers == 1:
        for completed, (idx, digest) in enumerate(session_items, start=1):
            session_id = str(digest.get("session_id") or "")
            if completed == 1 or completed % 10 == 0 or completed == total_sessions:
                print(f"[diagnose-run] provider={provider} progress={completed}/{total_sessions}")
            try:
                raw = infer_remote(digest)
                normalized = _normalize_session_output(
                    raw=raw,
                    digest=digest,
                    run_id=run_id,
                    provider=provider,
                    model=selected_model,
                    engine="api",
                )
                results.append((idx, normalized))
            except Exception as exc:
                errors_payload.append({"session_id": session_id, "error": str(exc)})
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(infer_remote, digest): (idx, digest)
                for idx, digest in session_items
            }
            completed = 0
            for future in as_completed(future_map):
                completed += 1
                idx, digest = future_map[future]
                session_id = str(digest.get("session_id") or "")
                if completed == 1 or completed % 10 == 0 or completed == total_sessions:
                    print(f"[diagnose-run] provider={provider} progress={completed}/{total_sessions}")
                try:
                    raw = future.result()
                    normalized = _normalize_session_output(
                        raw=raw,
                        digest=digest,
                        run_id=run_id,
                        provider=provider,
                        model=selected_model,
                        engine="api",
                    )
                    results.append((idx, normalized))
                except Exception as exc:
                    errors_payload.append({"session_id": session_id, "error": str(exc)})

    results.sort(key=lambda item: item[0])
    ordered_results = [item[1] for item in results]

    result_payload = {
        "schema_version": "session-mechanism-batch.v1",
        "run_id": run_id,
        "sessions": ordered_results,
    }
    result_path = run_dir / f"api_{provider}_results.json"
    _write_json(result_path, result_payload)
    if errors_payload:
        _write_json(
            run_dir / f"api_{provider}_errors.json",
            {
                "schema_version": "diagnose-api-errors.v1",
                "run_id": run_id,
                "provider": provider,
                "model": selected_model,
                "failed_sessions": errors_payload,
            },
        )

    print(f"[diagnose-run] api preview: {preview_path}")
    print(f"[diagnose-run] api results: {result_path}")
    if errors_payload:
        print(f"[diagnose-run] api failed_sessions={len(errors_payload)}")
    if errors_payload and not allow_partial:
        print(
            "ERROR: partial API failures detected; use --allow-partial only when explicitly accepted",
            file=sys.stderr,
        )
        return 1
    if not ordered_results:
        print("ERROR: no session mechanisms generated", file=sys.stderr)
        return 1
    return 0


def run_incremental_api(
    run_id: str,
    jobs_root: Path,
    provider: str,
    dry_run: bool,
    incremental_input: Dict[str, Any],
    *,
    skills_root: Optional[Path] = None,
    model: Optional[str] = None,
    timeout_sec: int = 180,
) -> Tuple[int, Optional[Path]]:
    """Run provider-backed incremental mechanism inference."""
    run_dir = jobs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if provider not in {"claude_cli", "codex_cli", "openai", "anthropic"}:
        print(f"ERROR: unsupported provider: {provider}", file=sys.stderr)
        return 2, None

    try:
        selected_model = model or _default_model(provider)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2, None

    effective_skills_root = skills_root or (jobs_root.parent / "skills")
    try:
        skill_prompt, skill_files = _load_incremental_skill_bundle(effective_skills_root)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2, None

    input_path = run_dir / "incremental_input.json"
    _write_json(input_path, incremental_input)

    preview_path = run_dir / f"incremental_api_{provider}_preview.json"
    preview_payload = {
        "schema_version": "diagnose-incremental-preview.v1",
        "run_id": run_id,
        "provider": provider,
        "model": selected_model,
        "dry_run": dry_run,
        "period_id": str(incremental_input.get("period_id") or ""),
        "sessions_with_mechanism": int(
            (incremental_input.get("coverage") or {}).get("sessions_with_mechanism", 0) or 0
        ),
        "skill_files": skill_files,
        "generated_at": _now_iso(),
        "note": "Incremental mechanism inference preview.",
    }
    _write_json(preview_path, preview_payload)
    if dry_run:
        print(f"[diagnose-incremental] api dry-run preview: {preview_path}")
        return 0, None

    def _coerce_incremental_payload(raw: Any) -> Dict[str, Any]:
        """Normalize model output to incremental payload object."""
        if isinstance(raw, dict) and raw.get("schema_version") == "incremental-mechanism.v1":
            return raw
        if isinstance(raw, dict) and isinstance(raw.get("incremental"), dict):
            return raw["incremental"]
        return {}

    openai_key = ""
    anthropic_key = ""
    if provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key:
            print("ERROR: OPENAI_API_KEY is not set", file=sys.stderr)
            return 2, None
    if provider == "anthropic":
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not anthropic_key:
            print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2, None

    def _infer_once(prompt_text: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run one incremental inference call."""
        if provider == "claude_cli":
            return _infer_incremental_claude_with_retries(
                model=selected_model,
                skill_prompt=prompt_text,
                incremental_input=payload,
                timeout_sec=timeout_sec,
            )
        if provider == "codex_cli":
            return _infer_incremental_codex_with_retries(
                model=selected_model,
                skill_prompt=prompt_text,
                incremental_input=payload,
                timeout_sec=timeout_sec,
            )
        if provider == "openai":
            return _openai_infer_incremental(
                api_key=openai_key,
                model=selected_model,
                skill_prompt=prompt_text,
                incremental_input=payload,
                timeout_sec=timeout_sec,
            )
        return _anthropic_infer_incremental(
            api_key=anthropic_key,
            model=selected_model,
            skill_prompt=prompt_text,
            incremental_input=payload,
            timeout_sec=timeout_sec,
        )

    sessions = incremental_input.get("sessions")
    session_items = [item for item in sessions if isinstance(item, dict)] if isinstance(sessions, list) else []
    use_chunking = len(session_items) > _INCREMENTAL_CHUNK_SIZE

    try:
        if not use_chunking:
            result_payload = _infer_once(skill_prompt, incremental_input)
        else:
            total_chunks = (len(session_items) + _INCREMENTAL_CHUNK_SIZE - 1) // _INCREMENTAL_CHUNK_SIZE
            chunk_reports: List[Dict[str, Any]] = []
            chunk_prompt = (
                f"{skill_prompt}\n\n"
                "[分片执行约束]\n"
                "- 当前输入仅代表全量会话中的一个分片。\n"
                "- 只基于当前分片产出中间机制报告。\n"
                "- 不要假设未出现的数据。"
            )

            for chunk_idx in range(total_chunks):
                start = chunk_idx * _INCREMENTAL_CHUNK_SIZE
                end = min(start + _INCREMENTAL_CHUNK_SIZE, len(session_items))
                chunk_session_items = session_items[start:end]
                chunk_input = dict(incremental_input)
                chunk_input["sessions"] = chunk_session_items
                coverage = (
                    dict(chunk_input.get("coverage"))
                    if isinstance(chunk_input.get("coverage"), dict)
                    else {}
                )
                coverage["sessions_with_mechanism"] = len(chunk_session_items)
                chunk_input["coverage"] = coverage

                raw_chunk = _infer_once(chunk_prompt, chunk_input)
                chunk_payload = _coerce_incremental_payload(raw_chunk)
                if not chunk_payload:
                    raise RuntimeError(f"chunk {chunk_idx + 1}/{total_chunks} returned empty payload")

                chunk_file = run_dir / f"incremental_chunk_{chunk_idx + 1:02d}_of_{total_chunks:02d}.json"
                _write_json(chunk_file, chunk_payload)

                reports = chunk_payload.get("reports")
                chunk_reports.append(
                    {
                        "chunk_id": f"{chunk_idx + 1}/{total_chunks}",
                        "coverage": chunk_payload.get("coverage") if isinstance(chunk_payload.get("coverage"), dict) else {},
                        "reports": reports if isinstance(reports, list) else [],
                    }
                )
                print(
                    f"[diagnose-incremental] chunk={chunk_idx + 1}/{total_chunks} "
                    f"reports={len(chunk_reports[-1]['reports'])}"
                )

            merge_input = dict(incremental_input)
            merge_input["sessions"] = []
            merge_input["chunk_reports"] = chunk_reports

            merge_prompt = (
                f"{skill_prompt}\n\n"
                "[分片聚合约束]\n"
                "- 当前输入包含 chunk_reports（分片中间结果）。\n"
                "- 你必须基于 chunk_reports 做全局去重、合并和层级收敛。\n"
                "- 最终输出仍必须是 IncrementalMechanismV1。"
            )
            result_payload = _infer_once(merge_prompt, merge_input)
    except Exception as exc:
        print(f"ERROR: incremental api inference failed: {exc}", file=sys.stderr)
        return 1, None

    result_path = run_dir / f"incremental_api_{provider}_result.json"
    if isinstance(result_payload, dict):
        _write_json(result_path, result_payload)
    else:
        _write_json(result_path, {"incremental": result_payload})
    print(f"[diagnose-incremental] api preview: {preview_path}")
    print(f"[diagnose-incremental] api result: {result_path}")
    return 0, result_path
