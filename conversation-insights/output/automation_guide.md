# 自动化增量分析指南

conversation-insights 的自动化设置说明。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        自动化流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ 每日 00:00   │    │ 每周日 02:00 │    │ 手动触发     │      │
│  │ (cron)       │    │ (cron)       │    │ (Claude Code)│      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ 增量导入     │    │ batch-digest │    │ L1/L2/L3     │      │
│  │ - Claude Code│    │ + dashboard  │    │ 分析 (Skill) │      │
│  │ - Codex      │    │              │    │              │      │
│  │ - Claude Web │    │              │    │              │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 安装定时任务

```bash
cd /Users/allenzhou/MIRISE/agents/conversation-insights
python3 scripts/scheduler.py --setup-cron
```

验证安装：
```bash
crontab -l | grep conversation-insights
```

### 2. 查看状态

```bash
python3 scripts/scheduler.py --status
```

### 3. 手动执行（测试）

```bash
# 运行每日任务
python3 scripts/scheduler.py --run-daily

# 运行每周任务
python3 scripts/scheduler.py --run-weekly
```

---

## 完整工作流

### 每日流程（自动）

| 时间 | 任务 | 方式 |
|------|------|------|
| 00:00 | 增量导入 | cron 自动执行 |

导入的数据存储在 `data/conversations/`。

### 每周流程（半自动）

| 时间 | 任务 | 方式 |
|------|------|------|
| 周日 02:00 | batch-digest 生成 | cron 自动 |
| 周日 02:00 | dashboard 更新 | cron 自动 |
| 手动 | Claude Code 分析 | Skill 模式 |

**手动分析步骤**：

1. 打开 Claude Code
2. 运行分析命令：
   ```
   分析本周新增的对话数据
   ```
3. 或使用 batch-write 写回元数据：
   ```bash
   python3 scripts/enrich_helper.py batch-write /tmp/enrich_batch_50.json
   ```

### 每月流程（手动）

| 任务 | 方式 |
|------|------|
| 完整分析 | Claude Code Skill |
| 更新 System Prompt | Claude Code 生成 |
| 更新 Prompt 模板 | Claude Code 生成 |
| 更新改进建议 | Claude Code 生成 |

---

## 输出文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| System Prompt | `output/system_prompt.md` | 个性化配置 |
| Prompt 模板 | `output/prompt_templates.md` | 高效 Prompt 模板 |
| 改进建议 | `output/improvement_guide.md` | 具体行动指南 |
| 分析报告 | `output/analysis_report.md` | L1/L2 分析结果 |
| 仪表盘 | `output/dashboard.html` | 可视化数据 |
| 日志 | `logs/*.log` | 定时任务日志 |

---

## 移除定时任务

```bash
python3 scripts/scheduler.py --remove-cron
```

---

## 常见问题

### Q: 为什么分析不能完全自动化？

A: L1/L2/L3 分析需要 LLM 理解对话内容，目前由 Claude Code 在 Skill 模式下完成。
   这样设计的优点：
   - 分析质量更高（使用最新模型）
   - 可以交互式调整
   - 不需要管理 API Key 和费用

### Q: 如何查看定时任务日志？

```bash
# 查看每日日志
tail -f logs/daily.log

# 查看每周日志
tail -f logs/weekly.log
```

### Q: 如何处理 ChatGPT/Gemini 数据？

这些平台需要手动导出：

```bash
# ChatGPT（从 OpenAI 导出后）
python3 scripts/ingest_chatgpt.py <path-to-conversations.json>

# Gemini（从 Google Takeout 导出后）
python3 scripts/ingest_gemini.py <path-to-takeout>
```

---

## 推荐使用模式

### 轻量级（推荐）

- **每天**：自动导入（无需操作）
- **每周**：花 5 分钟运行 Claude Code 分析
- **每月**：花 15 分钟更新所有输出文件

### 深度分析

- **每天**：自动导入 + 手动分析当天对话
- **每周**：完整 L1/L2 分析 + 认知偏差检测
- **每月**：L3 处方层更新 + 目标追踪

---

生成时间: 2026-02-06
