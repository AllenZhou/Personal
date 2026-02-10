# Conversation Insights

多平台 AI 对话洞察系统（Local-first，Skill-first）。

## 现在的运行方式

只保留一个串行入口：

```bash
python3 scripts/pipeline.py
```

`diagnose_helper.py` 不再暴露 `prepare/run/apply` 中间命令，主链只保留 `backfill + incremental`。

默认执行 `incremental`，完整串行链路：
1. 导入（claude_code + codex）
2. 启发式增强
3. 自动回填 session sidecar（missing/invalid/low-quality）
   - 通过 Skill + API provider 生成 `SessionMechanismV1`
   - 默认 provider: `claude_cli`（可切 `codex_cli` / `openai` / `anthropic`）
   - 质量门禁会拒绝历史模拟产物（如 `generated_by.engine=manual` / `provider=skill-manual`）
4. 生成增量机制洞察并写入 Analysis Reports（Notion）
   - L2: trigger chains / first-pass diagnostics / mechanism coverage gap / task stratification
   - L3: root causes / change delta / interventions / intervention impact / validation loop / reuse assets / compounding
   - 增量洞察由 Skill 直接产出中文机制结论；Python 仅做输入打包、契约校验和落盘/同步
   - Incremental sidecar 以 `reports` 为主契约；Python 不再根据 `why_patterns/interventions` 拼接分析文本
   - 写入策略：`Key Insights` 仅存短摘要；完整洞察逐条写入页面正文 blocks（分行可读）
   - 证据策略：多证据去重 + 分层证据（primary/supporting）
   - upsert 策略：自然键 `Dimension + Period`；同步前自动归档重复页（优先保留中文）
5. 同步 Tool/Domain 统计（Notion）
   - 统计 `Period` 与本次 incremental 运行窗口对齐（不再固定 `all-time`）
6. 生成 dashboard
   - 报告区优先读取最新本地 `incremental` sidecar；如连接 Notion 则可覆盖为云端最新报告
   - 报告区显示 `Key Insights` 摘要，并可展开查看“详细洞察”分条内容
   - 报告条目数量可通过 `--report-limit` 控制（`0` 表示不限）

## 运行模式

```bash
# 默认（增量）
python3 scripts/pipeline.py

# 显式增量
python3 scripts/pipeline.py run --mode incremental

# 全量
python3 scripts/pipeline.py run --mode full

# 仅预演，不写 Notion
python3 scripts/pipeline.py run --dry-run

# 控制 dashboard 报告条目上限（默认 50，0=不限）
python3 scripts/pipeline.py run --report-limit 100

# 指定 Skill provider（全量）
python3 scripts/pipeline.py run --mode full --skill-provider claude_cli
python3 scripts/pipeline.py run --mode full --skill-provider codex_cli
python3 scripts/pipeline.py run --mode full --skill-provider openai
python3 scripts/pipeline.py run --mode full --skill-provider anthropic

# 提升全量回填速度（并发）
python3 scripts/pipeline.py run --mode full --skill-provider claude_cli --skill-max-workers 6

# 全量强刷 + 部分失败容忍（跳过无效记录并落盘错误明细）
python3 scripts/pipeline.py run --mode full --backfill-force-refresh --allow-partial-backfill

```

### Provider 前置环境变量

- `--skill-provider claude_cli` 需要本机 `claude` CLI 已登录可用
- `--skill-provider codex_cli` 需要本机 `codex` CLI 已登录可用
- `--skill-provider openai` 需要 `OPENAI_API_KEY`
- `--skill-provider anthropic` 需要 `ANTHROPIC_API_KEY`
- `skills/diagnose-session.md` 必须存在；缺失时 fail-fast
- incremental 组合技能必须完整存在（`skills/diagnose-incremental.md` + `skills/analyze-behavior.md` + `skills/analyze-attribution.md` + `skills/analyze-mental.md` + `skills/extract-pattern.md` + `skills/coach.md`）；缺失任一文件即 fail-fast

## 测试模式（分段/全量）

```bash
# 分段测试（快速）
python3 scripts/pipeline.py test --mode segmented

# 全量测试
python3 scripts/pipeline.py test --mode full
```

## 调度

- `scripts/scheduler.py --setup-cron`
  - 每日 00:00：`python scripts/pipeline.py`（增量）
  - 周期全量：`python scripts/pipeline.py run --mode full`（默认示例为每周日 02:00）
- `scripts/auto_sync.sh` 默认触发增量，可通过 `PIPELINE_MODE=full` 触发全量。

## 核心输出

- `data/conversations/*.json`：原始事实源
- `data/insights/session/<session_id>.json`：会话机制 sidecar
- `data/insights/incremental/<period_id>.json`：增量机制 sidecar
- `output/dashboard.html`：可视化仪表盘
- `output/skill_jobs/<run_id>/invalid_session_mechanisms.json`：被契约校验跳过的无效结果明细（仅在 `allow-partial` 时生成）

## 文档索引

- 架构设计：`DESIGN.md`
- 工程实施：`ENGINEERING.md`
- Skill 入口：`SKILL.md`
- 契约文档：
  - `references/contracts/session_mechanism_v1.md`
  - `references/contracts/incremental_mechanism_v1.md`
- 经验沉淀：`LESSONS.md`
