# Conversation Insights — 工程文档

## 1. 执行模型

当前只保留单入口串行执行：

```bash
python3 scripts/pipeline.py
```

默认行为：增量链路（导入→增强→机制诊断→Notion 同步→dashboard）。
说明：当前主链为导入→增强→`backfill session sidecar`→`diagnose-incremental skill`→同步→dashboard。
说明：`diagnose_helper.py` 已移除 `prepare/run/apply` 中间命令，仅保留 `backfill/incremental` 供编排调用。

## 2. CLI

### 2.1 run

```bash
python3 scripts/pipeline.py run --mode incremental|full
python3 scripts/pipeline.py run --dry-run
python3 scripts/pipeline.py run --skip-ingest
python3 scripts/pipeline.py run --skip-enrich
python3 scripts/pipeline.py run --skip-backfill
python3 scripts/pipeline.py run --skill-provider claude_cli|codex_cli|openai|anthropic
python3 scripts/pipeline.py run --skill-model <model>
python3 scripts/pipeline.py run --skill-max-workers 4
python3 scripts/pipeline.py run --allow-partial-backfill
python3 scripts/pipeline.py run --report-limit 100   # dashboard 报告条数上限（0=不限）
```

### 2.2 doctor

```bash
python3 scripts/pipeline.py doctor --json
```

### 2.3 test

```bash
python3 scripts/pipeline.py test --mode segmented
python3 scripts/pipeline.py test --mode full
```

## 3. 调度

### 3.1 scheduler.py

- Daily：`python scripts/pipeline.py`
- 周期全量：`python scripts/pipeline.py run --mode full`（由 cron 频率决定，不绑定 weekly 语义）

### 3.2 auto_sync.sh

- 默认执行增量
- `PIPELINE_MODE=full` 可切全量

## 4. 兼容脚本

- `sync_analysis_reports.py`
- `sync_notion_stats.py`
- `dashboard.py`
- `snapshot.py`

以上仅保留 deprecation thin wrapper，不再触发全链路：
- `sync_analysis_reports.py` -> `_sync_analysis_reports_core.py`
- `sync_notion_stats.py` -> `_sync_notion_stats_core.py`
- `dashboard.py` -> `_dashboard_core.py`
- `snapshot.py` -> `_snapshot_core.py`

## 5. 契约与落盘

- `references/contracts/session_mechanism_v1.md`
- `references/contracts/incremental_mechanism_v1.md`

落盘目录：
- `data/insights/session/`
- `data/insights/incremental/`
- `output/skill_jobs/<run_id>/invalid_session_mechanisms.json`（`allow-partial` 时记录被跳过的无效会话结果）

增量机制产物要求至少包含：
- 覆盖信息（coverage）
- 报告列表（reports）
- 每条报告至少包含 `dimension/layer/title/key_insights/detail_lines`
- 可选扩展字段允许存在，但 Python 不依赖这些字段生成分析文案

语言约束：
- Skill 直接输出中文文案。
- 报告层只做结构拼装，不做翻译转换。
- `incremental` 阶段不再内置 Python 聚合推断逻辑；若无 Skill 结果则失败。
- 默认 provider 为 `claude_cli`（本机 CLI 套餐路径）；`codex_cli/openai/anthropic` 为可选路径。
- `codex_cli` 默认模型为 `gpt-5-codex`，并在运行时固定 `model_reasoning_effort=medium`，用于避免大输入下超时重试抖动。
- `codex_cli` 调用使用隔离工作目录（`/tmp/conversation-insights-codex-runtime`），避免读取仓库级 AGENTS 指令污染推断时延与输出形态。
- 禁止隐式降级：API provider 缺少凭证时直接失败，不允许自动退回 mock。
- 禁止隐式 prompt 降级：`skills/diagnose-session.md` 缺失时直接失败。
- incremental 阶段运行时仅加载组合技能：`skills/diagnose-incremental.md` + `skills/coach.md`；缺失任一文件直接失败。
- `skills/analyze-behavior.md`、`skills/analyze-attribution.md`、`skills/analyze-mental.md`、`skills/extract-pattern.md` 保留为方法论参考，不直接注入 codex_cli 运行时 prompt，避免 agentic 执行步骤拖慢推理。
- 禁止消费历史模拟 sidecar：`generated_by.engine=manual` / `generated_by.provider=skill-manual` 视为无效数据并跳过。
- Notion 报告写入采用“摘要 + 详情”双层结构：
  - `Key Insights` 仅写短摘要；
  - 页面正文写入完整逐条洞察（bulleted list，分行展示，不依赖单字段长度）。
- dashboard 报告表会读取 Notion 报告页正文的“详细洞察”区块，并在前端按行可展开显示。
- dashboard 报告读取条数由 `--report-limit` 控制（默认 50，0 表示不限）。
- dashboard 与 Notion 同步都按统一维度顺序渲染（由 `IncrementalMechanismV1` 维度映射驱动），避免显示顺序漂移。
- dashboard 在离线模式下会读取最新本地 `data/insights/incremental/*.json` 的 `reports`，避免“无 Notion 即无报告”。
- Analysis Reports 同步采用 upsert（自然键：`Dimension + Period`），`Date` 仅作为展示字段。
- Tool Stats 同步的 `Period` 标签与本次 incremental 运行窗口保持一致（不再固定 `all-time`）。
- 同步前执行去重归档：同一自然键仅保留一页，优先保留中文内容页，其余重复页自动 archive。
- session 结果默认严格校验（有无效则失败）；开启 `--allow-partial` 时会跳过无效记录并继续写入有效子集（由 `backfill` 内部 apply 阶段执行）。

## 6. 验收

- `python3 -m py_compile scripts/*.py`
- `python3 -m pytest -q tests`
- `python3 scripts/pipeline.py run --dry-run`
- 真实写入 Notion 前，确保 sidecar 与 incremental 契约均通过
