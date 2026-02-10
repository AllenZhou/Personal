# 通用学习系统 - 使用指南

## 系统概述

系统已从 AI 特定的学习系统泛化为支持**任意知识领域**的通用学习框架。

## 核心特性

### 1. 多领域支持
- 每个领域有独立的配置文件和数据结构
- 可以同时学习多个领域，数据完全隔离
- 领域配置通过 YAML 文件定义

### 2. 可配置课程路径
- 通过 `domain_configs/{domain}.yaml` 定义课程阶段
- 每个阶段包含多个课程（lessons）
- 每个课程定义核心概念

### 3. 领域特定专家角色
- 每个领域可以定义不同的专家角色
- 系统会根据角色调整教学风格和重点

### 4. 灵活的阶段门禁
- 每个领域可以自定义门禁规则
- 支持掌握度阈值、覆盖比例、新鲜度等指标

## 快速开始

### 使用现有领域（AI/LLM/Agent）

```bash
# 1. 初始化学习日志
bash .claude/skills/universal-lesson/scripts/journal_init.sh ai-llm-agent

# 2. 开始学习
/universal-lesson ai-llm-agent P0
```

### 创建新领域

```bash
# 1. 创建领域配置（交互式）
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py

# 2. 初始化学习日志
bash .claude/skills/universal-lesson/scripts/journal_init.sh {domain-identifier}

# 3. 开始学习
/universal-lesson {domain-identifier} P0
```

## 文件结构

```
项目根目录/
├── domain_configs/              # 领域配置目录
│   ├── ai-llm-agent.yaml        # AI 领域配置
│   ├── python-programming.yaml # Python 领域配置（示例）
│   └── README.md                # 配置说明
│
├── learning_journal/            # 学习数据目录（按领域隔离）
│   ├── ai-llm-agent/
│   │   ├── learning_log.jsonl
│   │   ├── concept_index.yaml
│   │   ├── review_queue.yaml
│   │   ├── phase_gates.yaml
│   │   └── assets/
│   └── python-programming/
│       └── ...
│
└── .claude/skills/
    └── universal-lesson/        # 通用学习技能
        ├── SKILL.md             # 技能定义
        ├── pedagogy.md           # 教学方法（通用）
        ├── schemas.md            # 数据结构（支持多领域）
        └── scripts/              # 支持脚本
            ├── journal_init.sh
            ├── phase_gate_check.py
            ├── concept_index_update.py
            ├── review_queue.py
            ├── journal_append.py
            ├── create_domain_config.py
            └── migrate_legacy_data.py
```

## 领域配置示例

### 最小配置

```yaml
domain:
  name: "领域名称"
  identifier: "domain-id"

expert_roles:
  - name: "专家角色"
    expertise: ["专长1", "专长2"]

learning_goals:
  primary: "学习目标"

phases:
  P0:
    name: "阶段名称"
    lessons:
      - id: "P0-L1"
        title: "课程标题"
        concepts: ["概念1", "概念2"]

phase_gates:
  policy:
    pass_mastery: 3
    covered_ratio: 0.8
    freshness_days: 14
    min_mastery_floor: 2
  gates:
    P0:
      required_concepts: ["概念1"]
```

## 命令参考

### 学习命令

```
/universal-lesson [domain] [topic-or-phase] [constraints]
```

- `domain`: 领域标识符（必需）
- `topic-or-phase`: 主题或阶段（可选，如 P0, P1-L2）
- `constraints`: 约束条件（可选）

### 脚本命令

```bash
# 初始化学习日志
bash .claude/skills/universal-lesson/scripts/journal_init.sh {domain}

# 创建领域配置
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py

# 迁移旧数据
python3 .claude/skills/universal-lesson/scripts/migrate_legacy_data.py {domain}
```

## 数据迁移

如果你有旧格式的数据，可以运行迁移脚本：

```bash
python3 .claude/skills/universal-lesson/scripts/migrate_legacy_data.py ai-llm-agent
```

这将把 `learning_journal/` 下的旧数据迁移到 `learning_journal/ai-llm-agent/` 目录。

## 使用场景示例

### 场景 1：学习 Python 编程

```bash
# 1. 创建配置
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py
# 输入：python-programming, Python 编程
# 定义阶段：P0 基础语法, P1 面向对象, P2 高级特性...

# 2. 初始化
bash .claude/skills/universal-lesson/scripts/journal_init.sh python-programming

# 3. 开始学习
/universal-lesson python-programming P0
```

### 场景 2：学习机器学习

```bash
# 1. 创建配置
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py
# 输入：machine-learning, 机器学习
# 定义阶段：P0 基础概念, P1 监督学习, P2 无监督学习...

# 2. 初始化
bash .claude/skills/universal-lesson/scripts/journal_init.sh machine-learning

# 3. 开始学习
/universal-lesson machine-learning P0
```

### 场景 3：同时学习多个领域

系统支持同时学习多个领域，数据完全隔离：

```bash
# 学习 AI
/universal-lesson ai-llm-agent P2

# 学习 Python
/universal-lesson python-programming P1

# 学习机器学习
/universal-lesson machine-learning P0
```

每个领域的学习进度、概念掌握度、复习队列都是独立的。

## 核心优势

1. **通用性**：支持任意知识领域
2. **可扩展性**：通过配置文件轻松添加新领域
3. **数据隔离**：多领域数据互不干扰
4. **一致性**：所有领域使用相同的学习科学方法
5. **灵活性**：每个领域可以自定义课程路径和门禁规则

## 相关文档

- `domain_configs/README.md` - 领域配置详细说明
- `MIGRATION_GUIDE.md` - 从旧系统迁移指南
- `.claude/skills/universal-lesson/SKILL.md` - 技能使用说明
