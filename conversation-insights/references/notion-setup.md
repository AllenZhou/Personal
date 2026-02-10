# Notion 配置指南

## 步骤 1：创建 Notion Integration

1. 访问 https://www.notion.so/my-integrations
2. 点击 "New integration"
3. 名称: `Conversation Insights`
4. 关联 workspace: 选择你的 workspace
5. Capabilities: 勾选 Read content / Update content / Insert content
6. 复制 Internal Integration Secret（`ntn_` 开头）

## 步骤 2：创建 Parent Page

1. 在 Notion 中创建一个页面（如 "AI Analytics"）
2. 点击页面右上角 `...` → Connections → 添加 `Conversation Insights` integration
3. 复制页面 URL 中的 page ID（URL 最后一段 32 位 hex，去掉 `-`）

示例 URL: `https://www.notion.so/My-Page-abc123def456...`
Page ID: `abc123def456...`（32 位 hex）

## 步骤 3：运行初始化

```bash
cd skills/conversation-insights
python scripts/notion_setup.py --api-key ntn_xxxx --parent-page xxxx
```

此脚本会自动创建以下结构并将 IDs 写入 `config.yaml`：

```
📄 Conversation Insights (顶层 Page)
├── 🗄 Conversations (Database)
├── 🗄 Analysis Reports (Database)
├── 🗄 Tool Stats (Database)
├── 🗄 Domain Map (Database)
├── 🗄 Analysis Log (Database)
└── 📄 User Profile (Page)
```

## Database Schemas

### Conversations

| Property | Type | 说明 |
|----------|------|------|
| Title | Title | 对话标题/首条 prompt |
| Session ID | Rich Text | 唯一标识符 |
| Source | Select | `chatgpt` / `claude_code` / `codex` / `gemini` / `claude_web` |
| Model | Rich Text | 模型名称 |
| Project Path | Rich Text | 项目路径 |
| Created At | Date | 对话创建时间 |
| Total Turns | Number | 总轮次 |
| Total Tool Uses | Number | 工具调用总次数 |
| Domains | Multi-select | 检测到的领域标签 |
| Language | Select | `en` / `zh` / `mixed` |
| Git Branch | Rich Text | 分支名 |
| Processed | Checkbox | 是否已分析 |

Page Body: Toggle heading per turn，包含用户消息、AI 响应摘要、工具调用列表。

### Analysis Reports

| Property | Type | 说明 |
|----------|------|------|
| Title | Title | 报告标题 |
| Dimension | Select | 分析维度名 |
| Layer | Select | `L1` / `L2` / `L3` |
| Period | Select | `rolling_30d` / `rolling_all-time` / `<since>_to_<until>` |
| Date | Date | 报告日期 |
| Conversations Analyzed | Number | 分析的对话数 |
| Key Insights | Rich Text | 核心发现摘要 |

### Tool Stats

| Property | Type | 说明 |
|----------|------|------|
| Tool Name | Title | 工具名称 |
| Period | Rich Text | 统计周期 |
| Usage Count | Number | 使用次数 |
| Success Rate | Number | 成功率 (0-100) |
| Common Sequences | Rich Text | 常见工具链 |
| Last Updated | Date | 最近更新 |

### Domain Map

| Property | Type | 说明 |
|----------|------|------|
| Domain | Title | 领域名 |
| Category | Select | 领域分类 |
| Conversation Count | Number | 相关对话数 |
| Depth Score | Number | 深度评分 (1-10) |
| Trend | Select | `growing` / `stable` / `declining` / `new` |
| Last Seen | Date | 最近出现 |
| Gap Indicator | Checkbox | 是否为知识空白 |

### Analysis Log

| Property | Type | 说明 |
|----------|------|------|
| Title | Title | 运行描述 |
| Run Type | Select | `full` / `incremental` |
| Started At | Date | 开始时间 |
| Status | Select | `running` / `completed` / `failed` |
| Sessions Processed | Number | 处理的会话数 |

## config.yaml 格式

```yaml
notion:
  api_key: "ntn_xxxx"
  parent_page_id: "xxxx"
  databases:
    conversations: "db-id-1"
    analysis_reports: "db-id-2"
    tool_stats: "db-id-3"
    domain_map: "db-id-4"
    analysis_log: "db-id-5"
  pages:
    user_profile: "page-id-1"
    root: "page-id-0"
```
