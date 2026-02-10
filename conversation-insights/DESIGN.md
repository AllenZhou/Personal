# Conversation Insights 设计文档

## 1. 目标与边界

### 1.1 目标

- 保留单一事实源：`data/conversations/*.json`
- 保留单一执行入口：`scripts/pipeline.py`
- 默认增量、支持全量
- 输出从统计转为机制洞察（what/why/how + evidence）

### 1.2 非目标

- 不做临床/心理学判断
- 不把 Notion 当事实源
- 不暴露多段式人工命令链给日常运行

## 2. 分层架构

| 层 | 组件 | 职责 | 输入 | 输出 |
|---|---|---|---|---|
| Data Source | `data/conversations/*.json` | 原始事实源 | ingest 产物 | 统一 schema 会话 |
| Enrich | `scripts/auto_enricher.py` | 统一补充 `metadata.llm_metadata` | conversation JSON | enriched conversation |
| Diagnose | `scripts/diagnose_helper.py` + `scripts/skill_runtime.py` + `skills/diagnose-session.md` + `skills/diagnose-incremental.md` + `skills/analyze-behavior.md` + `skills/analyze-attribution.md` + `skills/analyze-mental.md` + `skills/extract-pattern.md` + `skills/coach.md` | session backfill + Skill 机制推断 | conversations + session sidecars | session sidecar + incremental sidecar |
| Sync | `_sync_analysis_reports_core.py` + `_sync_notion_stats_core.py` | 写 Notion（报告/统计） | incremental sidecar + conversations | Notion pages（摘要字段 + 动态扩展详情 + upsert） |
| Presentation | `_dashboard_core.py` | 输出仪表盘 | local + optional Notion | HTML |
| Orchestrator | `scripts/pipeline.py` | 串行执行与失败传播 | CLI run/test/doctor | 运行结果 |

## 3. 运行契约

### 3.1 入口契约

- 默认：`python3 scripts/pipeline.py` 等价 `run --mode incremental`
- 全量：`python3 scripts/pipeline.py run --mode full`
- backfill：默认启用，自动补齐 missing/invalid/low-quality 的 session sidecar
- `diagnose_helper.py` 不再对外暴露 `prepare/run/apply` 中间命令；日常运行只走 `pipeline.py`
- 失败策略：任何步骤失败立即中止，返回非 0
- provider 默认：`claude_cli`（使用本机 Claude CLI 运行）
- provider 约束：凭证缺失时直接失败，不允许隐式 fallback 到 mock

### 3.2 数据契约

- `SessionMechanismV1`：`data/insights/session/<session_id>.json`
- `IncrementalMechanismV1`：`data/insights/incremental/<period_id>.json`

强约束：
- `why[*].evidence` 必填
- `why[*].evidence` 采用“去重 + 分层（primary/supporting）”组织，避免单一证据重复复用
- `SessionMechanismV1.generated_by` 必须来自真实执行路径（拒绝 `engine=manual` / `provider=skill-manual` 等模拟来源）
- `IncrementalMechanismV1.reports` 必填，且每条包含 `dimension/layer/title/key_insights/detail_lines`
- `IncrementalMechanismV1` 维度固定为当前 11 维（L2: 4 条，L3: 7 条），并按维度映射校验 `layer`
- Analysis Reports upsert 自然键固定为 `Dimension + Period`，避免同周期每日重复建页
- 同键冲突时执行去重归档，保留中文页（若无中文页则保留最近编辑页）
- 增量结论由 Skill 直接输出；Python 层不得内置归因/干预推断规则
- Skill 文件缺失直接失败（fail-fast），不允许隐式回退到内置默认 prompt
- incremental 运行时必须组合加载 `diagnose-incremental + analyze-behavior + analyze-attribution + analyze-mental + extract-pattern + coach`

## 4. 调度模型

- 定时增量（cron）：默认增量
- 周期全量（cron）：`run --mode full`（可按运维策略设置频率）
- 调度只触发 `pipeline.py`，不调用中间命令

## 5. 可观测性

- `pipeline doctor`：目录、schema、contract 健康检查
- `pipeline test --mode segmented|full`：分段/全量回归
