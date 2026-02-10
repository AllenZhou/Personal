"""
Heuristic-based conversation metadata enricher (Tier 0).

Extracts ``llm_metadata`` using pure Python rule-based analysis — no LLM API
calls, zero cost, runs instantly. Designed as the standard pipeline step
integrated into ``pipeline.py``.

Fields extracted:
    conversation_intent, task_type, actual_domains, difficulty, outcome,
    key_topics, prompt_quality, correction_analysis, cognitive_patterns,
    conversation_summary

Higher-fidelity enrichment (Mode E/F) can override these results later.

Usage as library::

    from auto_enricher import enrich_conversation_heuristic, batch_enrich

    # Single conversation
    conv = enrich_conversation_heuristic(conv)

    # Batch (modifies in-place + saves to disk)
    stats = batch_enrich(data_dir, force=False)
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Task-type keyword map
# ---------------------------------------------------------------------------

_TASK_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "debugging": [
        "bug", "error", "fix", "issue", "crash", "exception", "traceback",
        "debug", "broken", "fail", "报错", "错误", "修复", "异常", "崩溃",
        "问题", "出错", "不工作", "不生效",
    ],
    "new-feature": [
        "implement", "create", "build", "add feature", "new feature", "develop",
        "构建", "实现", "开发", "新功能", "添加", "创建",
    ],
    "refactoring": [
        "refactor", "clean up", "restructure", "reorganize", "simplify",
        "重构", "清理", "简化", "优化代码",
    ],
    "research": [
        "research", "compare", "evaluate", "investigate", "explore", "analysis",
        "study", "survey", "查找", "研究", "调研", "分析", "对比", "评估",
        "了解", "探索",
    ],
    "learning": [
        "learn", "explain", "how does", "what is", "tutorial", "understand",
        "teach", "学习", "解释", "什么是", "怎么", "教程", "理解", "教我",
        "是什么", "怎样",
    ],
    "documentation": [
        "document", "readme", "docs", "comment", "docstring", "write doc",
        "文档", "注释", "说明",
    ],
    "deployment": [
        "deploy", "release", "publish", "ci/cd", "pipeline", "docker",
        "kubernetes", "部署", "发布", "上线",
    ],
    "configuration": [
        "config", "setup", "install", "setting", "env", "configure",
        "配置", "设置", "安装", "环境",
    ],
    "brainstorming": [
        "brainstorm", "idea", "suggest", "design", "plan", "strategy",
        "头脑风暴", "想法", "建议", "策划", "方案",
    ],
    "code-review": [
        "review", "check", "audit", "inspect", "审查", "检查", "审核",
    ],
    "data-analysis": [
        "data", "csv", "excel", "statistics", "chart", "graph", "plot",
        "数据", "统计", "图表", "可视化",
    ],
    "writing": [
        "write", "draft", "compose", "email", "letter", "article", "blog",
        "essay", "写作", "撰写", "邮件", "文章", "博客",
    ],
    "design": [
        "design", "ui", "ux", "layout", "mockup", "wireframe", "style",
        "设计", "界面", "布局", "样式",
    ],
}

# Domain mapping: keyword -> hierarchical domain
_DOMAIN_KEYWORDS: Dict[str, str] = {
    # Backend
    "api": "backend.api", "rest": "backend.api", "graphql": "backend.graphql",
    "database": "backend.database", "sql": "backend.database", "postgres": "backend.database",
    "mongodb": "backend.database", "redis": "backend.cache",
    "auth": "backend.auth", "authentication": "backend.auth", "jwt": "backend.auth",
    "oauth": "backend.auth",
    "server": "backend.server", "express": "backend.nodejs", "fastapi": "backend.python",
    "django": "backend.python", "flask": "backend.python",
    # Frontend
    "react": "frontend.react", "vue": "frontend.vue", "angular": "frontend.angular",
    "css": "frontend.css", "html": "frontend.html", "javascript": "frontend.javascript",
    "typescript": "frontend.typescript", "tailwind": "frontend.css",
    "component": "frontend.components", "responsive": "frontend.responsive",
    # DevOps
    "docker": "devops.docker", "kubernetes": "devops.kubernetes", "k8s": "devops.kubernetes",
    "ci/cd": "devops.cicd", "github actions": "devops.cicd", "terraform": "devops.iac",
    "aws": "devops.cloud", "gcp": "devops.cloud", "azure": "devops.cloud",
    "nginx": "devops.server", "linux": "devops.linux",
    # AI/ML
    "machine learning": "ai-ml.ml", "deep learning": "ai-ml.dl",
    "llm": "ai-ml.llm", "gpt": "ai-ml.llm", "claude": "ai-ml.llm",
    "prompt": "ai-ml.prompting", "fine-tune": "ai-ml.finetuning",
    "embedding": "ai-ml.embeddings", "rag": "ai-ml.rag",
    "langchain": "ai-ml.frameworks", "model": "ai-ml.models",
    # Business
    "marketing": "business.marketing", "sales": "business.sales",
    "finance": "business.finance", "accounting": "business.accounting",
    "startup": "business.startup", "product": "business.product",
    "management": "business.management", "strategy": "business.strategy",
    # Legal
    "legal": "legal.general", "contract": "legal.contracts", "compliance": "legal.compliance",
    "regulation": "legal.regulation", "license": "legal.licensing",
    "corporate": "legal.corporate", "law": "legal.general",
    # Other
    "python": "programming.python", "java": "programming.java",
    "rust": "programming.rust", "go": "programming.go", "golang": "programming.go",
    "swift": "programming.swift", "kotlin": "programming.kotlin",
    "c++": "programming.cpp", "shell": "programming.shell", "bash": "programming.shell",
    "git": "tools.git", "vim": "tools.vim", "vscode": "tools.vscode",
    "notion": "tools.notion", "slack": "tools.slack",
    "scraping": "data.scraping", "crawl": "data.scraping",
    "blockchain": "web3.blockchain", "smart contract": "web3.smart-contracts",
    "ethereum": "web3.ethereum", "solidity": "web3.solidity",
    "uniswap": "web3.defi", "defi": "web3.defi",
    "crypto": "web3.crypto",
}

# Generic domain → hierarchical mapping for existing detected_domains
_GENERIC_DOMAIN_MAP: Dict[str, str] = {
    "ai-ml": "ai-ml.general",
    "backend": "backend.general",
    "frontend": "frontend.general",
    "devops": "devops.general",
    "business": "business.general",
    "ecommerce": "business.ecommerce",
    "marketing": "business.marketing",
    "education": "education.general",
    "creative": "creative.general",
    "writing": "writing.general",
    "health": "health.general",
    "research": "research.general",
    "legal": "legal.general",
    "productivity": "productivity.general",
    "other": "other",
}


# ---------------------------------------------------------------------------
# Core heuristic functions
# ---------------------------------------------------------------------------

def _get_text_content(conv: dict) -> str:
    """Concatenate all user + assistant text for keyword analysis."""
    parts = []
    title = conv.get("title", "")
    if title:
        parts.append(title)
    for turn in conv.get("turns", []):
        user_msg = turn.get("user_message", {}).get("content", "")
        if user_msg:
            parts.append(user_msg[:500])
        asst_msg = turn.get("assistant_response", {}).get("content", "")
        if asst_msg:
            parts.append(asst_msg[:300])
    return " ".join(parts).lower()


def _get_first_user_message(conv: dict) -> str:
    """Get the first user message content."""
    turns = conv.get("turns", [])
    if turns:
        return turns[0].get("user_message", {}).get("content", "")
    return ""


def _detect_task_type(text: str, title: str) -> str:
    """Detect task type from conversation text."""
    combined = (title + " " + text).lower()
    scores: Dict[str, int] = {}
    for task_type, keywords in _TASK_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[task_type] = score

    if not scores:
        return "other"
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def _detect_domains(conv: dict, text: str) -> List[str]:
    """Detect hierarchical domains from content and existing metadata."""
    domains: set = set()

    # Map existing detected_domains to hierarchical format
    existing = conv.get("metadata", {}).get("detected_domains", [])
    for d in existing:
        mapped = _GENERIC_DOMAIN_MAP.get(d.lower())
        if mapped:
            domains.add(mapped)

    # Keyword-based detection
    for keyword, domain in _DOMAIN_KEYWORDS.items():
        if keyword in text:
            domains.add(domain)

    if not domains:
        domains.add("other")

    return sorted(domains)[:5]  # Cap at 5


def _estimate_difficulty(conv: dict) -> int:
    """Estimate difficulty on a 1-10 scale."""
    turns = conv.get("turns", [])
    total_turns = len(turns)
    total_tools = sum(
        len(t.get("assistant_response", {}).get("tool_uses", []))
        for t in turns
    )
    total_corrections = sum(1 for t in turns if t.get("corrections"))

    # Heuristic formula
    score = 1.0
    score += min(total_turns * 0.3, 3.0)      # More turns = harder
    score += min(total_tools * 0.1, 2.0)       # More tools = harder
    score += min(total_corrections * 0.5, 2.0) # Corrections = complexity
    # Word count contribution
    total_words = sum(
        t.get("user_message", {}).get("word_count", 0) for t in turns
    )
    score += min(total_words / 500, 2.0)

    return max(1, min(10, round(score)))


def _estimate_outcome(conv: dict) -> str:
    """Estimate conversation outcome."""
    turns = conv.get("turns", [])
    if not turns:
        return "abandoned"

    total_turns = len(turns)

    # Very short conversations might be abandoned
    if total_turns == 1:
        return "exploratory"

    # Check last turn for resolution indicators
    last_user = turns[-1].get("user_message", {}).get("content", "").lower()
    last_asst = turns[-1].get("assistant_response", {}).get("content", "").lower()

    resolution_keywords = [
        "thank", "thanks", "perfect", "great", "done", "works",
        "got it", "resolved", "fixed", "谢谢", "好的", "完成",
        "可以了", "解决了", "搞定", "明白了", "懂了",
    ]
    for kw in resolution_keywords:
        if kw in last_user or kw in last_asst:
            return "resolved"

    abandon_keywords = [
        "never mind", "forget it", "算了", "不用了", "放弃",
    ]
    for kw in abandon_keywords:
        if kw in last_user:
            return "abandoned"

    # If many turns completed, probably resolved
    if total_turns >= 5:
        return "resolved"

    return "partial"


def _extract_key_topics(conv: dict, text: str) -> List[str]:
    """Extract key topics from conversation."""
    topics: List[str] = []

    # Title is the primary topic signal
    title = conv.get("title", "")
    if title:
        topics.append(title[:50])

    # Extract frequent meaningful words
    words = re.findall(r'[\w\u4e00-\u9fff]{3,}', text)
    stop_words = {
        "the", "and", "for", "that", "this", "with", "from", "have", "are",
        "was", "were", "been", "being", "will", "would", "could", "should",
        "not", "but", "can", "you", "your", "about", "into", "than", "its",
        "also", "just", "more", "some", "other", "all", "any", "most",
        "这个", "那个", "一个", "可以", "没有", "不是", "已经", "还是",
        "但是", "如果", "因为", "所以", "需要", "使用", "这些", "那些",
    }
    filtered = [w for w in words if w.lower() not in stop_words]
    freq = Counter(filtered).most_common(10)
    for word, count in freq:
        if count >= 2 and word not in topics:
            topics.append(word)
            if len(topics) >= 5:
                break

    return topics[:5]


def _assess_prompt_quality(conv: dict) -> Dict[str, Any]:
    """Assess the quality of user prompts."""
    first_msg = _get_first_user_message(conv)
    turns = conv.get("turns", [])
    strengths: List[str] = []
    weaknesses: List[str] = []
    score = 50  # Base score

    if not first_msg:
        return {"score": 20, "strengths": [], "weaknesses": ["no content"]}

    word_count = len(first_msg.split())

    # Length analysis
    if word_count >= 20:
        strengths.append("detailed description")
        score += 10
    elif word_count < 5:
        weaknesses.append("too brief")
        score -= 15

    # Context signals
    if any(kw in first_msg.lower() for kw in ["file", "code", "function", "class", "文件", "代码", "函数"]):
        strengths.append("references code")
        score += 5

    # Error/context provision
    if any(kw in first_msg.lower() for kw in ["error", "traceback", "log", "报错", "日志"]):
        strengths.append("provides error context")
        score += 10

    # Specificity
    if any(kw in first_msg.lower() for kw in ["please", "want", "need", "should", "请", "需要", "希望"]):
        strengths.append("clear intent")
        score += 5

    # Has code block
    if "```" in first_msg or "    " in first_msg:
        strengths.append("includes code")
        score += 10

    # Project context
    if conv.get("project_path"):
        strengths.append("project context available")
        score += 5

    # Corrections indicate room for improvement
    total_corrections = sum(1 for t in turns if t.get("corrections"))
    if total_corrections > 2:
        weaknesses.append("multiple corrections needed")
        score -= 10
    elif total_corrections > 0:
        weaknesses.append("some corrections needed")
        score -= 5

    # Many short messages might indicate unclear prompting
    short_msgs = sum(1 for t in turns
                     if t.get("user_message", {}).get("word_count", 0) < 5)
    if short_msgs > len(turns) * 0.5 and len(turns) > 3:
        weaknesses.append("many short messages")
        score -= 5

    if not strengths:
        strengths.append("basic request")
    if not weaknesses:
        weaknesses.append("could add more context")

    return {
        "score": max(10, min(95, score)),
        "strengths": strengths[:3],
        "weaknesses": weaknesses[:3],
    }


def _analyze_corrections(conv: dict) -> List[Dict[str, Any]]:
    """Analyze corrections in the conversation."""
    results: List[Dict[str, Any]] = []
    for turn in conv.get("turns", []):
        corrections = turn.get("corrections", [])
        if not corrections:
            continue
        turn_id = turn.get("turn_id", 0)
        for corr in corrections:
            ctype = corr.get("type", "unknown")
            indicator = corr.get("indicator", "")
            # Map correction type to reason
            reason = "user_changed_mind"
            if any(kw in indicator.lower() for kw in ["error", "wrong", "mistake", "incorrect"]):
                reason = "ai_error"
            elif any(kw in indicator.lower() for kw in ["actually", "instead", "change", "rather"]):
                reason = "user_changed_mind"
            elif any(kw in indicator.lower() for kw in ["also", "add", "more", "expand"]):
                reason = "scope_change"
            elif any(kw in indicator.lower() for kw in ["style", "format", "prefer"]):
                reason = "style_preference"

            results.append({
                "turn_id": turn_id,
                "reason": reason,
                "description": f"{ctype}: {indicator}" if indicator else ctype,
            })

    return results[:5]  # Cap


def _detect_cognitive_patterns(conv: dict) -> List[Dict[str, Any]]:
    """Detect cognitive patterns from conversation behavior."""
    patterns: List[Dict[str, Any]] = []
    turns = conv.get("turns", [])
    if not turns:
        return patterns

    # Perfectionism: many small corrections or rewording
    corrections = sum(1 for t in turns if t.get("corrections"))
    if corrections > 3:
        patterns.append({
            "pattern": "perfectionism",
            "evidence": f"{corrections} corrections across {len(turns)} turns",
            "severity": "moderate" if corrections > 5 else "mild",
        })

    # Scope creep: conversation grows much longer than typical
    if len(turns) > 20:
        patterns.append({
            "pattern": "scope_creep",
            "evidence": f"conversation extended to {len(turns)} turns",
            "severity": "moderate" if len(turns) > 30 else "mild",
        })

    return patterns[:3]


def _generate_summary(conv: dict, task_type: str, outcome: str) -> str:
    """Generate a brief conversation summary."""
    title = conv.get("title", "")
    source = conv.get("source", "unknown")
    turns = conv.get("turns", [])
    total_turns = len(turns)

    # Determine primary language
    lang = conv.get("metadata", {}).get("primary_language", "en")

    if lang in ("zh", "mixed"):
        # Chinese summary
        outcome_zh = {
            "resolved": "完成", "partial": "部分完成",
            "abandoned": "放弃", "exploratory": "探索性对话",
        }.get(outcome, outcome)
        task_zh = {
            "debugging": "调试", "new-feature": "新功能开发",
            "research": "研究", "learning": "学习",
            "refactoring": "重构", "documentation": "文档编写",
            "configuration": "配置", "brainstorming": "头脑风暴",
            "writing": "写作", "design": "设计",
            "data-analysis": "数据分析", "deployment": "部署",
            "code-review": "代码审查", "other": "其他",
        }.get(task_type, task_type)
        if title:
            return f"{title}。{task_zh}类任务，共{total_turns}轮对话，{outcome_zh}。"
        return f"{task_zh}类任务，共{total_turns}轮对话，{outcome_zh}。"
    else:
        # English summary
        if title:
            return f"{title}. {task_type} task across {total_turns} turns, {outcome}."
        first_msg = _get_first_user_message(conv)[:80]
        return f"{task_type} task: {first_msg}... ({total_turns} turns, {outcome})"


def _build_intent(conv: dict, task_type: str) -> str:
    """Build conversation intent description."""
    title = conv.get("title", "")
    first_msg = _get_first_user_message(conv)[:100]

    if title:
        return title[:80]
    if first_msg:
        return first_msg[:80]
    return f"{task_type} task"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_conversation_heuristic(conv: dict, *, force: bool = False) -> dict:
    """Enrich a conversation dict with heuristic-based metadata.

    Adds ``conv["metadata"]["llm_metadata"]`` in-place. Skips if already
    present unless *force* is True.

    Parameters
    ----------
    conv : dict
        A unified-schema conversation dict.
    force : bool
        If True, overwrite existing llm_metadata.

    Returns
    -------
    dict
        The same conversation dict with ``metadata.llm_metadata`` populated.
    """
    existing = conv.get("metadata", {}).get("llm_metadata")
    if existing and not force:
        return conv

    text = _get_text_content(conv)
    title = conv.get("title", "")
    task_type = _detect_task_type(text, title)
    outcome = _estimate_outcome(conv)

    llm_metadata = {
        "version": "1.0",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "heuristic-v1",
        "conversation_intent": _build_intent(conv, task_type),
        "task_type": task_type,
        "actual_domains": _detect_domains(conv, text),
        "difficulty": _estimate_difficulty(conv),
        "outcome": outcome,
        "key_topics": _extract_key_topics(conv, text),
        "prompt_quality": _assess_prompt_quality(conv),
        "correction_analysis": _analyze_corrections(conv),
        "cognitive_patterns": _detect_cognitive_patterns(conv),
        "conversation_summary": _generate_summary(conv, task_type, outcome),
    }

    if "metadata" not in conv:
        conv["metadata"] = {}
    conv["metadata"]["llm_metadata"] = llm_metadata
    conv["schema_version"] = "1.2"
    return conv


def batch_enrich(
    data_dir: Optional[str] = None,
    *,
    force: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """Batch-enrich all local conversation files.

    Parameters
    ----------
    data_dir : str, optional
        Path to ``data/conversations/``.
    force : bool
        If True, re-enrich files that already have llm_metadata.
    limit : int, optional
        Max files to process.

    Returns
    -------
    dict
        Stats: ``{enriched, skipped, errors, total}``.
    """
    if data_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, os.pardir, "data", "conversations")

    if not os.path.isdir(data_dir):
        return {"enriched": 0, "skipped": 0, "errors": 0, "total": 0}

    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))
    total = len(files)
    enriched = 0
    skipped = 0
    errors = 0

    for i, filename in enumerate(files):
        if limit is not None and enriched >= limit:
            break

        filepath = os.path.join(data_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                conv = json.load(fh)
        except (json.JSONDecodeError, OSError):
            errors += 1
            continue

        existing = conv.get("metadata", {}).get("llm_metadata")
        if existing and not force:
            skipped += 1
            continue

        try:
            enrich_conversation_heuristic(conv, force=force)
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(conv, fh, indent=2, ensure_ascii=False)
            enriched += 1
        except Exception:
            errors += 1

    return {"enriched": enriched, "skipped": skipped, "errors": errors, "total": total}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    force = "--force" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    print("自动启发式元数据提取...")
    stats = batch_enrich(force=force, limit=limit)
    print(f"完成: {stats['enriched']} enriched, {stats['skipped']} skipped, "
          f"{stats['errors']} errors (total: {stats['total']})")


if __name__ == "__main__":
    main()
