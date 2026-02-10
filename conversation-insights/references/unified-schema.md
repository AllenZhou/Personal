# 统一对话格式

所有导入脚本将不同平台的对话转换为此格式后写入 Notion。

## 内部表示（Python dict，用于脚本间传递）

```python
{
    "schema_version": "1.2",
    "session_id": str,          # 唯一标识（平台原始 ID）
    "source": str,              # "chatgpt" | "claude_code" | "codex" | "gemini" | "claude_web"
    "model": str | None,        # 模型名称（gpt-4o, claude-opus-4-5, gpt-5.2-codex...）
    "project_path": str | None, # 项目路径（Claude Code / Codex）
    "title": str,               # 对话标题或首条 prompt 摘要
    "created_at": str,          # ISO-8601 时间戳
    "git_branch": str | None,   # Git 分支名
    "turns": [
        {
            "turn_id": int,
            "timestamp": str | None,     # ISO-8601
            "user_message": {
                "content": str,          # 纯文本内容
                "word_count": int,
                "language": str,         # "en" | "zh" | "mixed"
                "has_code": bool,
                "has_file_reference": bool,
            },
            "assistant_response": {
                "content": str,          # 纯文本内容（摘要）
                "word_count": int,
                "tool_uses": [
                    {
                        "tool_name": str,
                        "success": bool | None,
                        "input": {                    # NEW v1.1: 工具输入参数
                            "file_path": str | None, # Edit/Write/Read/Grep/Glob
                            "pattern": str | None,   # Grep/Glob
                            "command": str | None,   # Bash
                        } | None,
                    }
                ],
                "has_thinking": bool,    # 是否有 extended thinking
            },
            "corrections": [             # 用户纠正（启发式检测）
                {
                    "type": str,         # "factual" | "style" | "approach" | "scope"
                    "indicator": str,    # 触发检测的关键词/模式
                }
            ],
        }
    ],
    "metadata": {
        "total_turns": int,
        "total_tool_uses": int,
        "primary_language": str,
        "detected_domains": list[str],
        "has_sidechains": bool,          # 是否有分支探索（Claude Code）
        "has_file_changes": bool,        # 是否有文件变更（Claude Code）
        "token_count": int | None,       # Token 统计（Codex）
        "file_changes": [                # v1.1: 文件变更详情（Claude Code）
            {
                "path": str,             # 文件路径
                "action": str,           # "add" | "modify" | "delete"
                "lines_added": int | None,
                "lines_removed": int | None,
            }
        ] | None,
        "llm_metadata": {               # NEW v1.2: LLM 语义预处理元数据
            "version": str,             # "1.0"
            "extracted_at": str,        # ISO-8601 提取时间
            "model_used": str,          # 提取用模型 "claude-3-5-haiku-..."
            "conversation_intent": str, # 简短意图: "debug-auth-middleware"
            "task_type": str,           # debugging | new-feature | research | learning |
                                        # refactoring | documentation | deployment |
                                        # configuration | brainstorming | code-review |
                                        # data-analysis | writing | design | other
            "actual_domains": [str],    # 细粒度领域: ["backend.auth", "security.jwt"]
            "difficulty": int,          # 1-10 任务难度
            "outcome": str,             # "resolved" | "partial" | "abandoned" | "exploratory"
            "key_topics": [str],        # 核心知识点列表
            "prompt_quality": {         # Prompt 质量语义评估
                "score": int,           # 0-100
                "strengths": [str],     # 优势点
                "weaknesses": [str],    # 不足点
            },
            "correction_analysis": [    # 每次纠正的语义分析
                {
                    "turn_id": int,
                    "reason": str,      # "ai_error" | "user_changed_mind" |
                                        # "scope_change" | "style_preference"
                    "description": str,
                }
            ],
            "cognitive_patterns": [     # 检测到的认知模式
                {
                    "pattern": str,     # "anchoring" | "sunk_cost" | "scope_creep" |
                                        # "confirmation_bias" | "perfectionism" |
                                        # "decision_fatigue"
                    "evidence": str,    # 具体证据描述
                    "severity": str,    # "mild" | "moderate" | "significant"
                }
            ],
            "conversation_summary": str, # 1-2 句话总结
        } | None,
    }
}
```

## 平台映射

### ChatGPT → 统一格式

| ChatGPT 字段 | 统一格式字段 |
|-------------|-------------|
| conversation `id` | `session_id` |
| `title` | `title` |
| `create_time` (unix) | `created_at` (ISO-8601) |
| `mapping` (树) | `turns` (展平为线性) |
| message `author.role` = "user" | `user_message` |
| message `author.role` = "assistant" | `assistant_response` |
| message `metadata.model_slug` | `model` |
| message `author.role` = "tool" | `tool_uses` entry |

树展平规则：从 root 沿 `children[0]` 遍历（取主线），忽略分支。

### Claude Code → 统一格式

| Claude Code 字段 | 统一格式字段 |
|-----------------|-------------|
| `sessionId` | `session_id` |
| sessions-index `firstPrompt`/`summary` | `title` |
| `timestamp` | `created_at` / turn `timestamp` |
| `type: user`, `message.content` | `user_message` |
| `type: assistant`, `message.content` | `assistant_response` |
| content `type: tool_use` | `tool_uses` entry |
| content `type: tool_use`, `input` | `tool_uses[].input` (NEW v1.1) |
| content `type: thinking` | `has_thinking = true` |
| `type: file-history-snapshot` | `has_file_changes` + `metadata.file_changes` (NEW v1.1) |
| `isSidechain` | `has_sidechains` |
| `cwd` | `project_path` |
| `gitBranch` | `git_branch` |

### Codex → 统一格式

| Codex 字段 | 统一格式字段 |
|-----------|-------------|
| session_meta `id` | `session_id` |
| session_meta `cwd` | `project_path` |
| session_meta `git.branch` | `git_branch` |
| event_msg `type: user_message` | `user_message` |
| event_msg `type: agent_message` | `assistant_response` |
| event_msg `type: agent_reasoning` | `has_thinking = true` |
| event_msg `type: token_count` | `token_count` |
| turn_context `model` | `model` |

## 语言检测

简单启发式（纯 Python）：
- 统计 CJK 字符比例（Unicode range `\u4e00-\u9fff`）
- CJK > 30%: `"zh"`
- CJK < 5%: `"en"`
- 其余: `"mixed"`

## 纠正检测

启发式模式匹配：
- 否定开头：`"no,"`、`"不是"`、`"不对"`、`"wrong"`
- 重新表述：`"I meant"`、`"我的意思是"`、`"instead"`
- 范围调整：`"only"`、`"just"`、`"只需要"`、`"不要"`
- 方法否定：`"don't use"`、`"别用"`、`"换个方式"`
