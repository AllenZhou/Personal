# Conversation-Insights 深度分析计划 v2

> 创建日期：2026-02-06
> 状态：执行中

## 目标

从「回顾型分析工具」升级为「实时型 AI 协作教练」

```
当前：回顾型分析 → 生成报告 → 用户自己看
目标：实时型教练 → 主动干预 → 持续改进循环
```

## 阶段划分

基于差距分析，按 **ROI 优先级** 分 4 个阶段：

| 阶段 | 目标 | 时间 | 核心交付物 |
|------|------|------|-----------|
| **Phase 1** | 深化分析 L2→85%, L3→80% | 2 周 | 行为链分析、归因追溯、心智模型 |
| **Phase 2** | 复利基础 | 2 周 | 知识库 Schema、自动入库、失败案例库 |
| **Phase 3** | 闭环追踪 | 1 周 | 建议追踪系统、有效性验证 |
| **Phase 4** | 实时能力 | 2 周 | Claude Code Hook、任务前推荐、实时预警 |

---

## Phase 1: 深化分析（L2 70%→85%, L3 50%→80%）

**目标**：从「知道是什么」到「知道为什么」

### 1.1 跨对话行为链分析
**文件**：`scripts/behavior_chain_analyzer.py`

```python
# 输入：按时间排序的对话列表
# 输出：行为链模式

行为链示例：
- "学习 → 实践 → 遇阻 → 求助 → 解决" （健康循环）
- "想法 → 直接执行 → 失败 → 重来" （冲动模式）
- "研究 → 研究 → 研究 → 放弃" （分析瘫痪）
```

**实现要点**：
- 基于 `task_type` + `outcome` 序列识别
- 时间窗口：24 小时内的对话算一个 session
- 输出：`behavior_chains.json` + `behavior_chain_report.md`

### 1.2 归因链条追溯
**文件**：`scripts/attribution_analyzer.py`

```python
# 对每个认知模式（如 scope_creep）追溯触发因素

归因链示例：
scope_creep (58 次)
├── 触发因素 1: 任务定义模糊（42%）
│   └── 证据：首条消息平均 <50 字
├── 触发因素 2: 中途发现新需求（35%）
│   └── 证据：Turn 5+ 出现 "另外"/"还有"
└── 触发因素 3: AI 主动扩展（23%）
    └── 证据：AI 响应中包含 "你可能还需要"
```

**实现要点**：
- 为每种认知模式定义 3-5 个可能触发因素
- 通过关键词 + 位置 + 统计验证
- 输出置信度分数

### 1.3 心智模型初步建模
**文件**：`scripts/mental_model_analyzer.py`

```python
# 从对话中提取用户的问题框架方式

心智模型维度：
- 问题分解习惯：整体思考 vs 拆分思考
- 假设检验方式：先做再验 vs 先验再做
- 不确定性应对：容忍模糊 vs 追求确定
```

**输出**：更新 `cognitive_profile.md` 增加心智模型章节

---

## Phase 2: 复利基础（知识库结构化）

**目标**：从「静态文件」到「结构化知识库」

### 2.1 知识库 Schema 设计
**文件**：`data/knowledge_base/schema.json`

```json
{
  "patterns": {
    "id": "string",
    "name": "string",
    "type": "success|failure|neutral",
    "trigger_conditions": ["string"],
    "evidence_conversations": ["session_id"],
    "effectiveness_score": 0-100,
    "domain_applicability": ["domain"],
    "created_at": "ISO-8601",
    "last_validated": "ISO-8601"
  },
  "templates": {
    "id": "string",
    "content": "string",
    "task_type": "string",
    "success_rate": 0-100,
    "usage_count": "int",
    "avg_turns_to_resolve": "float"
  }
}
```

### 2.2 自动入库脚本
**文件**：`scripts/knowledge_extractor.py`

**触发条件**：
- 对话 outcome = "resolved" 且 turns ≤ 5 → 提取为成功模式
- 对话有 3+ 次纠正 → 提取为失败案例
- Prompt 质量 ≥ 70 → 提取为模板候选

**输出**：
- `data/knowledge_base/patterns.json`
- `data/knowledge_base/templates.json`
- `data/knowledge_base/failures.json`

### 2.3 失败案例库
**文件**：`output/failure_library.md`

```markdown
## 失败案例 #1: JWT 认证调试循环

**背景**：
- 对话 ID: xxx
- 任务：修复 JWT token 过期问题
- 结果：12 轮未解决

**失败原因**：
- 首条消息未提供错误堆栈
- 中途切换了 3 种方案
- 未明确定义"成功"标准

**避免方法**：
1. 调试类任务必须附带完整错误信息
2. 定义明确的验收标准再开始
3. 单次对话只尝试 1 种方案

**关联模式**：scope_creep, debugging_without_context
```

---

## Phase 3: 闭环追踪（建议有效性验证）

**目标**：知道建议是否真的有用

### 3.1 建议追踪系统
**文件**：`data/recommendations/tracker.json`

```json
{
  "recommendation_id": "rec_001",
  "content": "调试任务先附带错误堆栈",
  "created_at": "2026-02-01",
  "target_metric": "debugging_first_turn_success_rate",
  "baseline_value": 32,
  "target_value": 50,
  "status": "active|adopted|rejected|validated",
  "adoption_evidence": ["session_id"],
  "current_value": 45,
  "validated_at": null
}
```

### 3.2 周度验证报告
**文件**：`scripts/recommendation_validator.py`

**逻辑**：
1. 读取 active recommendations
2. 计算本周 target_metric 值
3. 对比 baseline，判断是否改善
4. 更新 status 和 current_value

**输出**：`output/recommendation_effectiveness.md`

---

## Phase 4: 实时能力（Claude Code Hook 集成）

**目标**：从「事后分析」到「实时干预」

### 4.1 Claude Code Hook 设计
**文件**：`.claude/hooks/conversation_coach.py`

**触发点**：
- `pre_message`: 任务开始前，推荐相关模板
- `post_turn`: 每轮结束，检测风险信号
- `post_session`: 对话结束，自动入库

### 4.2 任务前推荐
**触发**：用户发送第一条消息时

```python
def pre_message_hook(message: str) -> str | None:
    # 1. 识别任务类型
    task_type = detect_task_type(message)

    # 2. 查找相关模板和经验
    templates = query_templates(task_type)
    failures = query_failures(task_type)

    # 3. 生成推荐提示
    if templates or failures:
        return f"""
💡 基于历史经验的建议：
- 推荐模板：{templates[0].content}
- 常见陷阱：{failures[0].summary}
"""
    return None
```

### 4.3 实时预警
**触发**：检测到风险信号时

```python
# 风险信号
RISK_SIGNALS = {
    "scope_creep": ["另外", "还有一个", "顺便"],
    "endless_loop": turns > 15,
    "vague_request": first_message_words < 20
}

def post_turn_hook(session) -> str | None:
    for signal, detector in RISK_SIGNALS.items():
        if detector(session):
            return f"⚠️ 检测到 {signal} 信号，建议：{get_advice(signal)}"
    return None
```

---

## 实现优先级矩阵

| 任务 | 影响 | 复杂度 | 优先级 |
|------|------|--------|--------|
| 1.1 行为链分析 | 高 | 中 | P0 |
| 1.2 归因链条 | 高 | 中 | P0 |
| 2.2 自动入库 | 高 | 低 | P0 |
| 2.3 失败案例库 | 高 | 低 | P1 |
| 3.1 建议追踪 | 中 | 低 | P1 |
| 1.3 心智模型 | 中 | 高 | P2 |
| 4.1 Hook 集成 | 高 | 高 | P2 |

---

## 验证方法

1. **单元测试**：每个新分析器都有测试用例
2. **回归验证**：新分析不破坏现有报告
3. **效果验证**：Phase 3 的追踪系统自动验证
4. **用户体验**：Phase 4 的 Hook 需要实际使用反馈

---

## 关键文件清单

| 阶段 | 新增/修改文件 |
|------|--------------|
| Phase 1 | `scripts/behavior_chain_analyzer.py`, `scripts/attribution_analyzer.py`, `scripts/mental_model_analyzer.py` |
| Phase 2 | `data/knowledge_base/schema.json`, `scripts/knowledge_extractor.py`, `output/failure_library.md` |
| Phase 3 | `data/recommendations/tracker.json`, `scripts/recommendation_validator.py` |
| Phase 4 | `.claude/hooks/conversation_coach.py`, `scripts/hook_helpers.py` |

---

## 进度追踪

- [ ] Phase 1.1 行为链分析
- [ ] Phase 1.2 归因链条
- [ ] Phase 1.3 心智模型
- [ ] Phase 2.1 知识库 Schema
- [ ] Phase 2.2 自动入库
- [ ] Phase 2.3 失败案例库
- [ ] Phase 3.1 建议追踪
- [ ] Phase 3.2 周度验证
- [ ] Phase 4.1 Hook 设计
- [ ] Phase 4.2 任务前推荐
- [ ] Phase 4.3 实时预警
