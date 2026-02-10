# Conversation Insights Lessons Learned

## 2026-02-06 - 架构迁移后文档与测试漂移

### 问题

代码主链已迁移到 `sync_*`，但文档和测试仍依赖 `analyze.py/generate_report.py/query_kb.py`，导致认知分裂和大面积测试失败。

### 原因

- 迁移时先改实现，未同步改文档与测试
- 缺少统一入口，CLI 分散导致事实源不一致

### 解决方案

- 新增 `scripts/pipeline.py` 作为统一入口
- 旧入口改为 wrapper 并加 deprecation 提示
- 测试拆分为按层验证（ingest/enrich/sync/pipeline/wrapper）

## 2026-02-06 - `--append` 语义与实现不一致

### 问题

`sync_notion_stats --append` 文档宣称 append/update，但实现实际仍 create，存在重复写入风险。

### 原因

- 没有定义 natural key
- 缺少 upsert 索引构建逻辑

### 解决方案

- 定义 natural key：Tool Stats=`Tool Name+Period`，Domain Map=`Domain`
- append 模式先拉取索引，再 `update_page` / `create_page`

## 2026-02-06 - 自动同步 enrich 统计路径错误

### 问题

`auto_sync.sh` 检查 `llm_metadata` 时读取了错误路径，导致待处理数误报。

### 原因

- schema 从顶层迁移到 `metadata.llm_metadata` 后脚本未更新

### 解决方案

- 修复读取路径为 `data['metadata']['llm_metadata']`
- auto sync 切换到 `pipeline.py`，避免多入口逻辑重复

## 2026-02-07 - 深层分析硬编码导致可演进性差

### 问题

深层分析（L3-L5）写在 Python 规则函数里，难以快速迭代分析框架，也难以保留证据链约束。

### 原因

- 推断逻辑与编排逻辑耦合在 `_sync_analysis_reports_core.py`
- 缺少明确的中间契约，Skill 输出无法直接落盘

### 解决方案

- 新增 `diagnose_helper.py` + `skill_runtime.py`，把 Python 限定为 I/O 与校验层
- 引入 sidecar 契约：
  - `SessionMechanismV1` → `data/insights/session/`
  - `IncrementalMechanismV1` → `data/insights/incremental/`
- `_sync_analysis_reports_core.py` 改为仅消费 incremental sidecar，不再做深层规则推断

## 2026-02-07 - weekly 到 incremental 迁移时参数兼容断裂

### 问题

`_sync_analysis_reports_core.py` 的加载函数已改为 `period_id`，但主函数仍传 `week` 命名参数，导致运行时报参数错误。

### 原因

- 接口改名后，调用点未同步修改
- 缺少针对新旧参数并存阶段的回归测试

### 解决方案

- 统一 `sync` 入口参数为 `--period-id`，保留 `--week` 兼容映射
- reports loader 改为优先读取 `data/insights/incremental/`，fallback `weekly/`

## 2026-02-07 - 多入口导致运行链不可控

### 问题

用户需要“无人值守串行执行”，但系统保留了 ingest/enrich/diagnose/sync/dashboard 等多入口，调度脚本和人工运行容易走出不同路径。

### 原因

- 历史兼容入口长期保留
- 调度依赖命令串联，缺少单入口封装

### 解决方案

- `pipeline.py` 收敛为单入口串行链（默认增量，支持全量）
- 无参数执行等价于 `run --mode incremental`
- `scheduler.py` 与 `auto_sync.sh` 只触发单入口
- 测试提供 `segmented/full` 两种模式以兼顾速度和覆盖率

## 2026-02-07 - 隐式 mock fallback 导致覆盖率假象

### 问题

全量链路曾出现“`sessions_total=601` 但 `sessions_with_mechanism=50`”的长期不一致；同时 API 模式在无凭证时会隐式走 mock，容易把“可运行”误判成“已完成真实分析”。

### 原因

- `pipeline run --mode full` 只做 incremental 聚合，没有先回填 session sidecar
- `run_api` 设计为无 provider 适配时自动 mock，缺少显式失败机制

### 解决方案

- 新增 `diagnose_helper backfill`，在主链中先回填 missing/invalid/low-quality sidecar
- `pipeline.py` 默认串行加入 backfill 阶段
- API provider 缺凭证时 fail-fast，不允许隐式 fallback；`mock` 仅作为显式测试 provider

## 2026-02-09 - Analysis Reports 自然键含 Date 导致重复页累积

### 问题

Analysis Reports 以 `Dimension + Period + Date` 作为 upsert key，导致同周期多次同步持续创建新页，出现中英双份与重复记录。

### 原因

- 自然键把展示字段 `Date` 混入业务键
- 缺少同步前的同键去重策略

### 解决方案

- upsert 自然键收敛为 `Dimension + Period`
- 同步前扫描并归档重复页：优先保留中文内容页；若都非中文，保留最近编辑页

## 2026-02-10 - Incremental 根因平铺导致 390 条低价值输出

### 问题

`why_patterns` 直接累积会话级假设，导致滚动全量周期出现数百条根因，洞察可用性下降。

### 原因

- 根因归一函数对未命中关键词的文本使用“原文截断”，几乎不会聚类
- 缺少 TopN 约束与机制 taxonomy

### 解决方案

- 删除 Python 侧增量推断实现，`incremental` 结论改为由 `diagnose-incremental` Skill 直接生成
- Python 仅保留输入打包、契约校验、sidecar 落盘和 Notion 写入
- 若未提供 Skill 结果（或运行失败），增量阶段直接 fail-fast，禁止隐式 fallback

## 2026-02-09 - Notion 批量操作超时未重试

### 问题

`purge_notion.py --analysis-only` 在归档中途抛出 `TimeoutError`，导致部分数据库清理中断。

### 原因

- `notion_client.py` 的 `_request` 只重试了 `HTTPError/URLError`
- `socket` 读超时在当前环境抛出 `TimeoutError`，未被重试分支覆盖

### 解决方案

- 在 `_request` 增加 `TimeoutError` 重试分支，沿用现有 backoff 策略
- 清理任务可重入（再次执行会从剩余页面继续）

## 2026-02-09 - 兼容 wrapper 误触发全链路导入

### 问题

直接运行 `sync_notion_stats.py` / `dashboard.py` 会触发 `pipeline.py run`，导致额外会话导入和长时间运行，偏离“单步骤操作”预期。

### 原因

- wrapper 虽标注 deprecation，但实现仍绑定全链路入口
- 未区分“兼容入口”与“编排入口”

### 解决方案

- wrapper 改为真正 thin wrapper，只转发对应 core 脚本
- 保留 deprecation 提示，但不再附带跨阶段副作用

## 2026-02-10 - Incremental 契约未统一导致旧分析字段反复回流

### 问题

虽然同步层已改为消费 `reports`，但 runtime 提示词、manual 模板和测试 fixture 仍沿用 `why_patterns/interventions`，导致“去 Python 硬编码分析”目标反复失效。

### 原因

- 只改了下游写入层，未同步改上游生成契约
- 校验器与测试样例未统一到单一事实契约

### 解决方案

- Incremental 契约收敛为 `coverage + reports` 必填
- Skill 提示词改为直接输出中文 `reports`
- Python 侧仅做契约校验、sidecar 落盘与 Notion 写入，不再依赖旧分析字段
- 测试全部切换到 `reports` 契约，移除旧字段依赖

## 2026-02-10 - 历史 manual sidecar 污染增量分析

### 问题

`data/insights/session` 中保留了 `generated_by.engine=manual` / `provider=skill-manual` 的历史 sidecar，增量聚合会把这些“非真实运行路径”结果当作有效机制，导致结论质量不稳定。

### 原因

- 会话契约仅检查字段完整性，未校验生成来源是否可信
- 读取 sidecar 时未对历史模拟 run_id（如 `replace-mock-sidecars-*`）进行阻断

### 解决方案

- 在 `validate_session_mechanism` 增加来源门禁，阻断 `manual/skill-manual/api-mock` 等来源
- sidecar 加载阶段二次过滤被阻断来源，避免污染增量输入
- 清理历史模拟 sidecar 后再执行全量 backfill + incremental 重建

## 2026-02-10 - 增量维度与展示顺序漂移导致“分析像统计罗列”

### 问题

Skill 输出维度和 dashboard/Notion 展示顺序未统一，且未接入 `coach` 扩展维度，导致结果出现“维度缺失 + 顺序混乱 + 大量平铺条目”。

### 原因

- 维度定义分散在多个文件，缺少单一映射源
- runtime 组合技能未包含 `coach.md`
- 校验器只校验字段完整性，未校验维度合法性与层级映射

### 解决方案

- 新增 `scripts/incremental_dimensions.py` 作为维度映射与排序单一事实源
- incremental runtime 强制加载 `coach.md`
- `validate_incremental_mechanism` 增加维度合法性、layer 映射、重复键检测与“逐会话倾倒”门禁
- sync/dashboard 统一按维度顺序渲染

## 2026-02-10 - Skill 文件缺失时隐式默认 prompt 降级

### 问题

当 `skills/diagnose-session.md` 或 `skills/diagnose-incremental.md` 缺失时，runtime 会使用内置默认 prompt 继续执行，造成“看似成功、实际偏离设计”的隐式降级。

### 原因

- `_load_skill_prompt` / `_load_incremental_skill_prompt` 采用默认字符串兜底
- 调用方未把“技能文件缺失”视为硬错误

### 解决方案

- 技能文件缺失改为 fail-fast（抛错并返回非 0）
- `run_api` / `run_incremental_api` 显式报错退出，避免隐式推断路径

## 2026-02-10 - 中间命令残留导致“单入口”约束失真

### 问题

虽然主链已切到 `pipeline.py`，但 `diagnose_helper.py` 仍暴露 `prepare/run/apply`，与“单入口串行执行”要求冲突。

### 原因

- 迁移时仅做了 help 隐藏，没有移除命令解析入口
- 测试仍依赖旧命令，导致收敛动作被延后

### 解决方案

- 从 CLI parser 中移除 `prepare/run/apply`
- 保留内部复用函数用于 `backfill` 自动 apply，不对外暴露命令
- 测试改为覆盖 `backfill -> incremental` 主链与内部 apply 函数

## 2026-02-10 - Dashboard 离线模式未消费本地机制报告

### 问题

`dashboard --no-notion` 会显示“暂无分析报告数据（需连接 Notion）”，即使本地已有 `incremental` sidecar。

### 原因

- 报告区数据仅从 Notion `analysis_reports` 拉取
- 本地 `data/insights/incremental/*.json` 未接入 dashboard 数据源

### 解决方案

- 新增本地报告加载逻辑：读取最新 incremental sidecar 的 `reports`
- dashboard 报告区离线可展示本地 `key_insights + detail_lines`
- Notion 连接可用时继续覆盖为云端最新报告

## 2026-02-10 - codex_cli 在增量分片下频繁超时重试

### 问题

`diagnose_helper.py incremental --provider codex_cli` 在大输入分片场景下，首片推理长时间无返回并进入超时重试，导致整链路卡住、dashboard 无新数据。

### 原因

- `codex_cli` 默认模型使用 `gpt-5.3-codex`，在当前环境默认 `reasoning effort=xhigh`
- 大 prompt（组合技能 + 分片输入）下，`xhigh` 推理耗时明显上升，触发 `timeout` 与重试链

### 解决方案

- `codex_cli` 默认模型改为 `gpt-5-codex`
- 运行命令固定追加 `-c model_reasoning_effort="medium"`，稳定缩短分片推理时延
- `codex exec` 使用隔离目录（`/tmp/conversation-insights-codex-runtime`）运行，避免仓库级 AGENTS 指令导致的额外推理开销
- incremental 运行时 prompt 仅注入 `diagnose-incremental.md + coach.md`，其余方法论 skill 不注入执行 prompt，避免触发不必要的 agentic 文件扫描步骤
- 保持 Skill-first 推断路径不变，Python 仍仅负责编排、校验、落盘与同步
