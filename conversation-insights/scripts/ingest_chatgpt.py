#!/usr/bin/env python3
"""
Ingest ChatGPT conversations from an exported conversations.json into Notion.

Usage:
    python scripts/ingest_chatgpt.py <path-to-conversations.json> [--since YYYY-MM-DD]

The script:
    1. Loads conversations from the JSON export file
    2. Flattens the tree-structured mapping into linear turns
    3. Detects language and domains from user messages
    4. Deduplicates against existing Notion records (by session_id + source=chatgpt)
    5. Creates Notion pages with properties and toggle-block turn bodies
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup -- allow importing sibling modules from the scripts/ directory
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from notion_client import NotionClient  # noqa: E402
# llm_enricher removed - use Skill mode for metadata extraction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE = "chatgpt"
MAX_BLOCK_TEXT_LENGTH = 1900  # Leave headroom for UTF-16 surrogate pairs (Notion counts UTF-16 code units)
_DATA_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "data", "conversations"))


def _save_local(conv: dict) -> None:
    """Save normalized conversation dict to local JSON file."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    session_id = conv.get("session_id", "unknown")
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    path = os.path.join(_DATA_DIR, f"{safe_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)


# Domain keyword mapping used for lightweight detection.
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "react", "vue", "angular", "css", "html", "tailwind", "nextjs",
        "next.js", "svelte", "dom", "browser", "webpack", "vite",
        "javascript", "typescript", "jsx", "tsx", "styled-components",
    ],
    "backend": [
        "express", "fastapi", "django", "flask", "spring", "rails",
        "api", "rest", "graphql", "grpc", "server", "endpoint",
        "middleware", "routing", "controller",
    ],
    "devops": [
        "docker", "kubernetes", "k8s", "ci/cd", "jenkins", "github actions",
        "terraform", "ansible", "nginx", "helm", "aws", "gcp", "azure",
        "deployment", "pipeline", "infrastructure",
    ],
    "database": [
        "sql", "postgres", "mysql", "mongodb", "redis", "sqlite",
        "migration", "schema", "query", "index", "orm", "prisma",
        "sequelize", "typeorm", "knex",
    ],
    "data-science": [
        "pandas", "numpy", "matplotlib", "jupyter", "dataset",
        "visualization", "statistics", "analysis", "csv", "dataframe",
        "seaborn", "plotly", "scipy",
    ],
    "mobile": [
        "ios", "android", "react native", "flutter", "swift",
        "kotlin", "xcode", "mobile app",
    ],
    "security": [
        "authentication", "authorization", "oauth", "jwt", "cors",
        "encryption", "vulnerability", "xss", "csrf", "ssl", "tls",
        "password", "hash", "token",
    ],
    "testing": [
        "test", "jest", "pytest", "mocha", "cypress", "playwright",
        "unittest", "coverage", "mock", "stub", "fixture", "assertion",
    ],
    "documentation": [
        "readme", "docs", "documentation", "markdown", "jsdoc",
        "docstring", "comment", "specification",
    ],
    "architecture": [
        "design pattern", "microservice", "monolith", "clean architecture",
        "dependency injection", "solid", "refactor", "modular",
        "event-driven", "message queue",
    ],
    "legal": [
        "compliance", "regulation", "license", "gdpr", "privacy",
        "terms of service", "contract", "legal",
    ],
    "finance": [
        "payment", "stripe", "invoice", "accounting", "financial",
        "transaction", "billing", "subscription",
    ],
    "design": [
        "ui", "ux", "figma", "wireframe", "prototype", "layout",
        "color", "typography", "responsive", "accessibility",
    ],
    "ai-ml": [
        "machine learning", "deep learning", "neural network", "model",
        "training", "inference", "llm", "transformer", "embedding",
        "fine-tuning", "prompt engineering", "openai", "langchain",
        "vector", "rag", "agent", "gpt", "claude", "gemini",
        "提示词", "prompt", "ai助手",
    ],
    "marketing": [
        "marketing", "seo", "sem", "广告", "营销", "推广", "社交媒体",
        "social media", "content marketing", "品牌", "brand", "抖音",
        "tiktok", "instagram", "facebook", "youtube", "短视频",
        "influencer", "kol", "用户增长", "growth", "留存", "conversion",
        "campaign", "运营", "引流", "获客",
    ],
    "business": [
        "商业模式", "business model", "strategy", "策略", "市场分析",
        "竞品", "competitor", "融资", "投资", "startup", "创业",
        "盈利", "revenue", "profit", "成本", "roi", "商业计划",
        "供应链", "supply chain", "b2b", "b2c", "saas",
    ],
    "real-estate": [
        "房产", "房地产", "real estate", "property", "别墅", "公寓",
        "apartment", "物业", "租金", "rent", "房价", "楼盘",
        "开发商", "developer", "迪拜房", "dubai property",
    ],
    "education": [
        "学习", "教育", "course", "课程", "培训", "training",
        "教程", "tutorial", "学校", "大学", "university", "emba",
        "mba", "在线教育", "e-learning",
    ],
    "writing": [
        "翻译", "translate", "translation", "写作", "writing",
        "copywriting", "文案", "编辑", "editing", "校对", "proofread",
        "摘要", "summary", "总结", "润色", "rewrite",
    ],
    "creative": [
        "视频", "video", "图片", "image", "设计", "design",
        "创意", "creative", "剪辑", "editing", "动画", "animation",
        "海报", "poster", "logo", "photoshop", "illustrator",
        "midjourney", "stable diffusion",
    ],
    "research": [
        "研究", "research", "报告", "report", "分析", "analysis",
        "数据分析", "data analysis", "调研", "survey", "统计",
        "趋势", "trend", "洞察", "insight", "白皮书",
    ],
    "ecommerce": [
        "电商", "ecommerce", "e-commerce", "shopify", "amazon",
        "淘宝", "拼多多", "跨境", "cross-border", "物流",
        "logistics", "仓储", "warehouse", "salla", "woocommerce",
    ],
    "crypto-web3": [
        "区块链", "blockchain", "crypto", "bitcoin", "ethereum",
        "nft", "defi", "web3", "钱包", "wallet", "交易所",
        "exchange", "币安", "binance", "token", "smart contract",
    ],
    "immigration": [
        "签证", "visa", "移民", "immigration", "居留", "residence",
        "护照", "passport", "工作许可", "work permit", "自贸区",
        "free zone", "公司注册", "company formation", "营业执照",
        "trade license",
    ],
    "automotive": [
        "汽车", "car", "automobile", "vehicle", "出口", "export",
        "平行进口", "进口车", "4s店", "dealer", "新能源",
        "electric vehicle", "ev",
    ],
    "food": [
        "做法", "recipe", "烹饪", "cooking", "美食", "food",
        "餐厅", "restaurant", "菜谱", "ingredient", "烘焙", "baking",
    ],
    "health": [
        "健康", "health", "医疗", "medical", "运动", "fitness",
        "exercise", "营养", "nutrition", "心理", "psychology",
        "mental health", "睡眠", "sleep",
    ],
    "productivity": [
        "效率", "productivity", "workflow", "工作流", "自动化",
        "automation", "notion", "obsidian", "工具", "tool",
        "时间管理", "time management", "模板", "template",
    ],
}

# Correction detection patterns (from unified-schema.md).
CORRECTION_PATTERNS: list[dict[str, str]] = [
    {"type": "factual", "indicator": r"(?i)^no[,.\s]"},
    {"type": "factual", "indicator": r"^不是"},
    {"type": "factual", "indicator": r"^不对"},
    {"type": "factual", "indicator": r"(?i)\bwrong\b"},
    {"type": "style", "indicator": r"(?i)\bI meant\b"},
    {"type": "style", "indicator": r"我的意思是"},
    {"type": "style", "indicator": r"(?i)\binstead\b"},
    {"type": "scope", "indicator": r"(?i)\bonly\b"},
    {"type": "scope", "indicator": r"(?i)\bjust\b"},
    {"type": "scope", "indicator": r"只需要"},
    {"type": "scope", "indicator": r"不要"},
    {"type": "approach", "indicator": r"(?i)\bdon'?t use\b"},
    {"type": "approach", "indicator": r"别用"},
    {"type": "approach", "indicator": r"换个方式"},
]


# ---------------------------------------------------------------------------
# Helpers -- language & domain detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Detect language using CJK character ratio heuristic."""
    if not text:
        return "en"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ratio = cjk_count / max(len(text), 1)
    if ratio > 0.3:
        return "zh"
    if ratio < 0.05:
        return "en"
    return "mixed"


def detect_domains(text: str) -> list[str]:
    """Return a sorted list of domain tags matched via keyword search."""
    lower = text.lower()
    matched: set[str] = set()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                matched.add(domain)
                break
    return sorted(matched) if matched else ["other"]


def detect_corrections(text: str) -> list[dict[str, str]]:
    """Detect user corrections via regex pattern matching."""
    found: list[dict[str, str]] = []
    for pattern in CORRECTION_PATTERNS:
        if re.search(pattern["indicator"], text):
            found.append({"type": pattern["type"], "indicator": pattern["indicator"]})
    return found


# ChatGPT tool name normalisation: raw author.name / recipient → standard name.
_TOOL_NAME_MAP: dict[str, str] = {
    "web.run": "web_search",
    "web": "web_search",
    "web.search": "web_search",
    "browser": "web_browser",
    "browser.open": "web_browser",
    "browser.search": "web_browser",
    "browser.find": "web_browser",
    "browser.mclick": "web_browser",
    "myfiles_browser": "file_browser",
    "python": "code_interpreter",
    "container.exec": "code_interpreter",
    "container.download": "code_interpreter",
    "container.open_image": "code_interpreter",
    "file_search": "file_search",
    "file_search.msearch": "file_search",
    "dalle.text2im": "dalle",
    "image_gen.edit_image": "dalle",
    "bio": "memory",
    "canmore.create_textdoc": "canvas",
    "canmore.update_textdoc": "canvas",
    "canmore.comment_textdoc": "canvas",
    "computer.do": "computer_use",
    "computer.get": "computer_use",
    "computer.sync_file": "computer_use",
    "research_kickoff_tool.start_research_task": "deep_research",
    "research_kickoff_tool.clarify_with_text": "deep_research",
    "research_kickoff_tool": "deep_research",
    "api_tool.call_tool": "api_tool",
    "api_tool": "api_tool",
    "api_tool.widget_state": "api_tool",
}


def _normalise_tool_name(raw_name: str | None) -> str:
    """Map a raw ChatGPT tool author.name to a standard tool category."""
    if not raw_name:
        return "unknown"
    # Direct match
    if raw_name in _TOOL_NAME_MAP:
        return _TOOL_NAME_MAP[raw_name]
    # Plugin pattern: namespace__jit_plugin.method
    if "__jit_plugin" in raw_name:
        ns = raw_name.split("__jit_plugin")[0]
        # Take last segment of namespace (e.g. "bibigpt_co" from full name)
        parts = ns.rsplit(".", 1)
        return f"plugin:{parts[-1]}"
    # GPT-specific tool IDs (random-looking strings like "t2uay3k.sj1i4kz"
    # or short alphanumeric IDs like "a8km123")
    if "." in raw_name and len(raw_name.split(".")[0]) <= 8:
        return "gpt_action"
    # Short alphanumeric-only strings are also GPT action IDs
    if len(raw_name) <= 10 and raw_name.isalnum() and not raw_name.isalpha():
        return "gpt_action"
    return raw_name


def _has_code(text: str) -> bool:
    """Check whether the text contains inline code or code blocks."""
    return "```" in text or bool(re.search(r"`[^`]+`", text))


def _has_file_reference(text: str) -> bool:
    """Heuristic to detect file path references in text."""
    return bool(re.search(r"[/\\][\w.\-]+(?:[/\\][\w.\-]+)+", text))


def _word_count(text: str) -> int:
    """Count words (handles both CJK-heavy and Latin text)."""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin_words = len(re.findall(r"[a-zA-Z0-9_]+", text))
    return cjk + latin_words


def unix_to_iso(ts: Optional[float]) -> Optional[str]:
    """Convert a Unix timestamp to an ISO-8601 string, or return None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _utf16_len(s: str) -> int:
    """Return the length of *s* in UTF-16 code units (what Notion counts)."""
    return len(s.encode("utf-16-le")) // 2


def truncate(text: str, max_len: int = MAX_BLOCK_TEXT_LENGTH) -> str:
    """Truncate text to *max_len* UTF-16 code units, adding an ellipsis when trimmed."""
    if _utf16_len(text) <= max_len:
        return text
    # Trim character by character until we fit
    trimmed = text[: max_len - 3]
    while _utf16_len(trimmed) > max_len - 3:
        trimmed = trimmed[:-1]
    return trimmed + "..."


# ---------------------------------------------------------------------------
# Tree flattening
# ---------------------------------------------------------------------------

def _find_root_node(mapping: dict[str, Any]) -> Optional[str]:
    """
    Find the root node in the mapping tree.

    The root is a node whose ``parent`` is ``None`` or points to an ID that
    does not exist in the mapping.
    """
    for node_id, node in mapping.items():
        parent = node.get("parent")
        if parent is None or parent not in mapping:
            return node_id
    return None


def flatten_mapping(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Walk the main conversation line (children[0]) depth-first and return a
    list of turn dicts following the unified schema.

    System messages are skipped.  Tool messages are attached to the preceding
    assistant turn's ``tool_uses`` list.
    """
    root_id = _find_root_node(mapping)
    if root_id is None:
        return []

    # Collect ordered messages by walking children[0].
    ordered_messages: list[dict[str, Any]] = []
    current_id: Optional[str] = root_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        node = mapping.get(current_id)
        if node is None:
            break

        msg = node.get("message")
        if msg is not None:
            role = (msg.get("author") or {}).get("role", "")
            content_obj = msg.get("content") or {}
            parts = content_obj.get("parts") or []
            # Concatenate text parts (skip non-string items like image dicts).
            text_parts = [p for p in parts if isinstance(p, str)]
            text = "\n".join(text_parts).strip()

            if role in ("user", "assistant", "tool") and text:
                ordered_messages.append({
                    "role": role,
                    "text": text,
                    "create_time": msg.get("create_time"),
                    "metadata": msg.get("metadata") or {},
                    "author_name": (msg.get("author") or {}).get("name"),
                    "recipient": msg.get("recipient"),
                })

        children = node.get("children") or []
        current_id = children[0] if children else None

    # Pair user/assistant messages into turns.
    turns: list[dict[str, Any]] = []
    turn_id = 0
    i = 0
    while i < len(ordered_messages):
        msg = ordered_messages[i]

        if msg["role"] == "user":
            user_text = msg["text"]
            assistant_text = ""
            assistant_meta: dict[str, Any] = {}
            tool_uses: list[dict[str, Any]] = []
            assistant_time: Optional[float] = None

            # Consume subsequent assistant and tool messages.
            j = i + 1
            while j < len(ordered_messages) and ordered_messages[j]["role"] in ("assistant", "tool"):
                next_msg = ordered_messages[j]
                if next_msg["role"] == "assistant":
                    # Assistant messages with a recipient are tool invocations
                    # (input side); tool responses carry the output.
                    # Only update assistant_text for non-tool-call messages.
                    recv = next_msg.get("recipient")
                    if not recv or recv in ("all", ""):
                        assistant_text = next_msg["text"]
                    assistant_meta = next_msg["metadata"]
                    assistant_time = next_msg["create_time"]
                elif next_msg["role"] == "tool":
                    tool_meta = next_msg["metadata"]
                    # Primary: author.name from the raw message
                    raw_tool_name = next_msg.get("author_name")
                    tool_name = _normalise_tool_name(raw_tool_name)

                    # Extract tool input if available
                    tool_input = None
                    raw_input = tool_meta.get("input") or tool_meta.get("arguments")
                    if raw_input:
                        if isinstance(raw_input, str):
                            try:
                                raw_input = json.loads(raw_input)
                            except json.JSONDecodeError:
                                raw_input = None
                        if isinstance(raw_input, dict):
                            file_path = raw_input.get("file_path") or raw_input.get("path")
                            pattern = raw_input.get("pattern")
                            command = raw_input.get("command")
                            if file_path or pattern or command:
                                tool_input = {}
                                if file_path:
                                    tool_input["file_path"] = file_path
                                if pattern:
                                    tool_input["pattern"] = pattern
                                if command:
                                    tool_input["command"] = command[:500]

                    tool_uses.append({
                        "tool_name": tool_name,
                        "success": None,
                        "input": tool_input,
                    })
                j += 1

            turn_id += 1
            has_thinking = bool(assistant_meta.get("is_thinking") or assistant_meta.get("thought"))

            turns.append({
                "turn_id": turn_id,
                "timestamp": unix_to_iso(msg["create_time"]),
                "user_message": {
                    "content": user_text,
                    "word_count": _word_count(user_text),
                    "language": detect_language(user_text),
                    "has_code": _has_code(user_text),
                    "has_file_reference": _has_file_reference(user_text),
                },
                "assistant_response": {
                    "content": assistant_text,
                    "word_count": _word_count(assistant_text),
                    "tool_uses": [
                        {
                            "tool_name": tu["tool_name"],
                            "success": tu.get("success"),
                            "input": tu.get("input"),
                        }
                        for tu in tool_uses
                    ],
                    "has_thinking": has_thinking,
                },
                "corrections": detect_corrections(user_text),
                "_model_slug": assistant_meta.get("model_slug"),
            })

            i = j
        else:
            # Skip orphan assistant/tool messages that appear before the first
            # user message (e.g. system prompts that slipped through).
            i += 1

    return turns


# ---------------------------------------------------------------------------
# Conversation normalisation
# ---------------------------------------------------------------------------

def normalise_conversation(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a single raw ChatGPT conversation dict into the unified schema
    format described in ``references/unified-schema.md``.
    """
    mapping = raw.get("mapping") or {}
    turns = flatten_mapping(mapping)

    # Derive model from the first assistant turn that has a model_slug.
    model: Optional[str] = None
    for t in turns:
        slug = t.pop("_model_slug", None)
        if slug and model is None:
            model = slug

    # Aggregate user message text for language and domain detection.
    all_user_text = " ".join(t["user_message"]["content"] for t in turns)

    primary_language = detect_language(all_user_text)
    detected_domains = detect_domains(all_user_text)
    total_tool_uses = sum(len(t["assistant_response"]["tool_uses"]) for t in turns)

    return {
        "schema_version": "1.1",
        "session_id": raw["id"],
        "source": SOURCE,
        "model": model,
        "project_path": None,
        "title": raw.get("title") or "(untitled)",
        "created_at": unix_to_iso(raw.get("create_time")),
        "git_branch": None,
        "turns": turns,
        "metadata": {
            "total_turns": len(turns),
            "total_tool_uses": total_tool_uses,
            "primary_language": primary_language,
            "detected_domains": detected_domains,
            "has_sidechains": False,
            "has_file_changes": False,
            "token_count": None,
        },
    }


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config.yaml"))


def load_client() -> NotionClient:
    """Load a NotionClient from config.yaml. Exits on failure."""
    if not os.path.isfile(_CONFIG_PATH):
        print(f"Error: config file not found at {_CONFIG_PATH}", file=sys.stderr)
        print(
            "Run  python scripts/notion_setup.py --api-key <key> --parent-page <id>  first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return NotionClient.load_config(_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Notion interaction helpers
# ---------------------------------------------------------------------------

def fetch_existing_session_ids(client: NotionClient, db_id: str) -> set[str]:
    """
    Query the Conversations database for all pages where Source == 'chatgpt'
    and return their Session ID values as a set for O(1) dedup lookups.
    """
    existing: set[str] = set()

    filter_payload = {
        "property": "Source",
        "select": {"equals": SOURCE},
    }

    try:
        pages = client.query_database(db_id, filter=filter_payload)
    except Exception as exc:
        print(f"Warning: failed to query existing sessions: {exc}", file=sys.stderr)
        print("Proceeding without deduplication.", file=sys.stderr)
        return existing

    for page in pages:
        props = page.get("properties", {})
        session_prop = props.get("Session ID", {})
        # Session ID is Rich Text.
        rich_texts = session_prop.get("rich_text", [])
        if rich_texts:
            sid = rich_texts[0].get("plain_text", "")
            if sid:
                existing.add(sid)

    return existing


def _build_turn_blocks(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build Notion block children representing each turn as a toggle heading
    containing the user message, assistant response, and tool uses.
    """
    blocks: list[dict[str, Any]] = []

    for turn in turns:
        turn_id = turn["turn_id"]
        user_content = truncate(turn["user_message"]["content"])
        assistant_content = truncate(turn["assistant_response"]["content"])
        tool_uses = turn["assistant_response"].get("tool_uses") or []

        # Build inner children of the toggle.
        inner: list[dict[str, Any]] = []

        # User message paragraph.
        inner.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "User: "}, "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": user_content}},
                ],
            },
        })

        # Assistant response paragraph.
        if assistant_content:
            inner.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Assistant: "}, "annotations": {"bold": True}},
                        {"type": "text", "text": {"content": assistant_content}},
                    ],
                },
            })

        # Tool uses as a bulleted list.
        for tu in tool_uses:
            tool_label = tu.get("tool_name", "unknown")
            inner.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"Tool: {tool_label}"}},
                    ],
                },
            })

        # Toggle heading for the turn.
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"Turn {turn_id}"}},
                ],
                "children": inner,
            },
        })

    return blocks


def create_conversation_page(
    client: NotionClient,
    db_id: str,
    conv: dict[str, Any],
) -> str:
    """
    Create a Notion page in the Conversations database for the given
    normalised conversation.  Returns the created page ID.
    """
    meta = conv["metadata"]

    # Build properties dict matching the Conversations DB schema.
    properties: dict[str, Any] = {
        "Title": {
            "title": [{"type": "text", "text": {"content": conv["title"]}}],
        },
        "Session ID": {
            "rich_text": [{"type": "text", "text": {"content": conv["session_id"]}}],
        },
        "Source": {
            "select": {"name": SOURCE},
        },
        "Model": {
            "rich_text": [{"type": "text", "text": {"content": conv["model"] or ""}}],
        },
        "Total Turns": {
            "number": meta["total_turns"],
        },
        "Total Tool Uses": {
            "number": meta["total_tool_uses"],
        },
        "Language": {
            "select": {"name": meta["primary_language"]},
        },
        "Domains": {
            "multi_select": [{"name": d} for d in meta["detected_domains"]],
        },
        "Processed": {
            "checkbox": False,
        },
    }

    # Created At (date property).
    if conv["created_at"]:
        properties["Created At"] = {
            "date": {"start": conv["created_at"]},
        }

    # Project Path and Git Branch are None for ChatGPT but included for
    # schema completeness.
    if conv.get("project_path"):
        properties["Project Path"] = {
            "rich_text": [{"type": "text", "text": {"content": conv["project_path"]}}],
        }
    if conv.get("git_branch"):
        properties["Git Branch"] = {
            "rich_text": [{"type": "text", "text": {"content": conv["git_branch"]}}],
        }

    # Metadata-only: skip writing conversation body blocks to Notion.
    # Full conversation data lives in local JSON files.
    page = client.create_page(
        parent_id=db_id,
        properties=properties,
    )

    return page["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import ChatGPT conversations into Notion.",
    )
    parser.add_argument(
        "conversations_json",
        help="Path to the ChatGPT conversations.json export file.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only import conversations created on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        default=True,
        help="Skip LLM API enrichment during import (default). Use Mode F or --use-llm-api.",
    )
    parser.add_argument(
        "--use-llm-api",
        action="store_true",
        default=False,
        help="Enable LLM metadata enrichment via Anthropic API during import.",
    )
    return parser.parse_args()


def load_conversations(path: str) -> list[dict[str, Any]]:
    """Load and return the raw conversations list from the JSON file."""
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print(f"Error: expected a JSON array at top level in {path}.", file=sys.stderr)
        sys.exit(1)

    return data


def filter_by_date(
    conversations: list[dict[str, Any]],
    since: Optional[str],
) -> list[dict[str, Any]]:
    """Filter conversations to those created on or after *since* (YYYY-MM-DD)."""
    if since is None:
        return conversations

    try:
        cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Error: invalid --since date format: {since!r}. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    filtered: list[dict[str, Any]] = []
    for conv in conversations:
        create_time = conv.get("create_time")
        if create_time is None:
            # Include conversations without a timestamp (be conservative).
            filtered.append(conv)
            continue
        conv_dt = datetime.fromtimestamp(create_time, tz=timezone.utc)
        if conv_dt >= cutoff:
            filtered.append(conv)

    return filtered


def main() -> None:
    args = parse_args()

    # 0. Load LLM API key if enrichment is enabled.
    _llm_api_key = None
    if args.use_llm_api:
        try:
            pass  # LLM API removed - use Skill mode
        except RuntimeError:
            print("WARN: No Anthropic API key found. Skipping LLM enrichment.", file=sys.stderr)
            args.use_llm_api = False

    # 1. Load config and initialise Notion client.
    client = load_client()
    conversations_db_id: str = client.databases["conversations"]

    # 2. Load conversations from JSON.
    raw_conversations = load_conversations(args.conversations_json)
    print(f"Loaded {len(raw_conversations)} conversation(s) from {args.conversations_json}")

    # 3. Apply --since date filter.
    raw_conversations = filter_by_date(raw_conversations, args.since)
    if args.since:
        print(f"After --since {args.since} filter: {len(raw_conversations)} conversation(s)")

    if not raw_conversations:
        print("Nothing to import.")
        return

    # 4. Fetch existing session IDs for deduplication.
    print("Querying Notion for existing ChatGPT sessions...")
    existing_ids = fetch_existing_session_ids(client, conversations_db_id)
    print(f"Found {len(existing_ids)} existing session(s) in Notion.")

    # 5. Normalise and import.
    imported = 0
    skipped = 0
    errors = 0
    total = len(raw_conversations)

    for idx, raw in enumerate(raw_conversations, start=1):
        session_id = raw.get("id", "")
        title = raw.get("title") or "(untitled)"

        # Dedup check.
        if session_id in existing_ids:
            skipped += 1
            print(f"  [{idx}/{total}] SKIP (exists): {title}")
            continue

        # Normalise.
        try:
            conv = normalise_conversation(raw)
        except Exception as exc:
            errors += 1
            print(f"  [{idx}/{total}] ERROR normalising '{title}': {exc}", file=sys.stderr)
            continue

        # Skip conversations that produced zero turns (e.g. empty or system-only).
        if conv["metadata"]["total_turns"] == 0:
            skipped += 1
            print(f"  [{idx}/{total}] SKIP (no turns): {title}")
            continue

        # LLM metadata enrichment.
        if args.use_llm_api:
            try:
                pass  # LLM enrichment removed
            except Exception as exc:
                print(f"  [{idx}/{total}] WARN LLM enrich failed: {exc}", file=sys.stderr)

        # Save to local JSON.
        _save_local(conv)

        # Create Notion page.
        try:
            page_id = create_conversation_page(client, conversations_db_id, conv)
            imported += 1
            print(f"  [{idx}/{total}] IMPORTED: {title}  ({conv['metadata']['total_turns']} turns, page={page_id})")
        except Exception as exc:
            errors += 1
            print(f"  [{idx}/{total}] ERROR importing '{title}': {exc}", file=sys.stderr)

    # 6. Summary.
    print()
    print("=" * 60)
    print(f"  Total conversations : {total}")
    print(f"  Imported (new)      : {imported}")
    print(f"  Skipped (existing)  : {skipped}")
    if errors:
        print(f"  Errors              : {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
