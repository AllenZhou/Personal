# 分析维度规范（Skill-first）

## 1. 目标

本文件定义 `conversation-insights` 的分析维度与证据规则。  
原则：**机制结论由 Skill 产出，Python 仅负责输入打包、契约校验、持久化与同步**。

## 2. 分层定义

### L1 事实层（Data Facts）

来源：
- `data/conversations/*.json`
- `metadata.llm_metadata`
- `data/insights/session/*.json`（仅作为机制衍生输入，不回写原始事实）

产出：
- 基础分布、流程状态、覆盖度基线
- 仅作为证据上下文，不直接生成“为什么/怎么改”的归因结论

### L2 会话机制层（Session Mechanism）

主技能：
- `skills/diagnose-session.md`

扩展技能（已纳入主流程）：
- `skills/analyze-behavior.md`
- `skills/analyze-attribution.md`
- `skills/analyze-mental.md`
- `skills/extract-pattern.md`

核心问题：
- 发生了什么（what happened）
- 为什么发生（mechanism hypothesis + evidence）
- 怎么改（trigger/action/expected_gain/validation_window）

输出契约：
- `SessionMechanismV1`
- 强制 `why[*].evidence` 存在且可追溯到 `session_id + turn_id + snippet`

### L3 增量机制层（Incremental Mechanism）

主技能：
- `skills/diagnose-incremental.md`

输入：
- `IncrementalInputV1`（由 Python 从会话事实与 session sidecar 聚合）

输出：
- `IncrementalMechanismV1.reports`
- 每条 report 必须包含：
  - `dimension`
  - `layer`
  - `title`
  - `key_insights`
  - `detail_lines`

说明：
- L3 结论必须是“机制解释 + 证据指向 + 干预动作”，不能退化为纯计数罗列。

## 3. 证据规则

1. 每条 root-cause / trigger-chain 必须有文本证据。
2. 证据使用“去重 + 分层（primary/supporting）”组织。
3. 禁止无证据心理推断。
4. 允许数字，但数字只能作为证据，不得替代机制解释。

## 4. 主流程接入点

入口：
- `scripts/pipeline.py`（串行）

执行链：
1. ingest
2. enrich
3. `diagnose_helper.py backfill`（session mechanism）
4. `diagnose_helper.py incremental`（incremental mechanism）
5. Notion sync + dashboard

运行时：
- `scripts/skill_runtime.py` 会在 incremental 阶段组合加载：
  - `diagnose-incremental.md`
  - `analyze-behavior.md`
  - `analyze-attribution.md`
  - `analyze-mental.md`
  - `extract-pattern.md`

缺失任一必需技能文件时 fail-fast。

## 5. 非目标

- 不再使用旧的 `analyze_*.py` 规则推断模块作为主链分析引擎。
- 不在 Python 中硬编码 root-cause / intervention 文案模板。
- 不将 Notion 作为事实源。
