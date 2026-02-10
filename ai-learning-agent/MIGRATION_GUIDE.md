# 从 AI 特定系统迁移到通用学习系统

## 概述

系统已从 AI 特定的学习系统泛化为支持任意领域的通用学习框架。

## 主要变化

### 1. 技能名称变更
- 旧：`/ai-lesson`
- 新：`/universal-lesson [domain] [topic-or-phase]`

### 2. 数据结构变更
所有数据文件现在支持多领域结构：

**旧格式** (`concept_index.yaml`):
```yaml
P0: []
P1: []
```

**新格式**:
```yaml
domains:
  ai-llm-agent:
    P0: []
    P1: []
  python-programming:
    P0: []
```

### 3. 文件位置变更
- 旧：`learning_journal/learning_log.jsonl`
- 新：`learning_journal/{domain}/learning_log.jsonl`

## 迁移步骤

### 步骤 1：迁移现有 AI 学习数据

如果你已有 `learning_journal/` 目录下的数据，需要迁移到新格式：

```bash
# 创建迁移脚本（如果需要）
python3 .claude/skills/universal-lesson/scripts/migrate_legacy_data.py
```

### 步骤 2：使用新的技能命令

**旧方式**：
```
/ai-lesson P0
```

**新方式**：
```
/universal-lesson ai-llm-agent P0
```

### 步骤 3：创建新领域（可选）

如果你想学习新领域：

```bash
# 1. 创建领域配置
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py

# 2. 初始化学习日志
bash .claude/skills/universal-lesson/scripts/journal_init.sh {domain-identifier}

# 3. 开始学习
/universal-lesson {domain-identifier} P0
```

## 兼容性说明

### 向后兼容
- 旧的 `ai-lesson` 技能仍然可用（如果保留）
- 旧的数据格式可以通过脚本自动迁移

### 数据迁移
系统会自动检测旧格式并迁移到新格式，但建议：
1. 备份现有数据
2. 测试迁移后的数据完整性

## 新功能

### 1. 多领域支持
可以同时学习多个领域，数据完全隔离。

### 2. 可配置课程
通过 YAML 配置文件定义任意领域的课程路径。

### 3. 领域特定专家角色
每个领域可以定义不同的专家角色，调整教学风格。

### 4. 灵活的阶段门禁
每个领域可以自定义阶段门禁规则。

## 常见问题

### Q: 我的旧数据会丢失吗？
A: 不会。系统支持自动迁移，旧数据会转换为新格式。

### Q: 可以同时使用旧技能和新技能吗？
A: 可以，但建议统一使用新技能 `/universal-lesson`。

### Q: 如何迁移现有学习进度？
A: 运行迁移脚本，或手动将数据复制到 `learning_journal/{domain}/` 目录。

## 示例：创建 Python 编程领域

```bash
# 1. 创建配置
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py
# 输入：python-programming, Python 编程, ...

# 2. 初始化
bash .claude/skills/universal-lesson/scripts/journal_init.sh python-programming

# 3. 开始学习
/universal-lesson python-programming P0
```

## 技术支持

如有问题，请查看：
- `domain_configs/README.md` - 领域配置说明
- `.claude/skills/universal-lesson/SKILL.md` - 技能使用说明
