# 领域配置系统

## 概述

通用学习系统支持通过领域配置文件来定义不同知识领域的学习路径。每个领域有独立的：
- 课程阶段和课程内容
- 专家角色定义
- 阶段门禁规则
- 学习目标

## 创建新领域

### 方法 1：使用交互式工具（推荐）

```bash
python3 .claude/skills/universal-lesson/scripts/create_domain_config.py
```

工具会引导你：
1. 输入领域标识符和名称
2. 定义专家角色
3. 设置学习目标
4. 创建课程阶段和课程
5. 配置阶段门禁规则

### 方法 2：手动创建配置文件

在 `domain_configs/` 目录下创建 `{domain-identifier}.yaml` 文件，参考 `ai-llm-agent.yaml` 的格式。

## 配置文件结构

```yaml
domain:
  name: "领域显示名称"
  identifier: "领域标识符（英文）"
  description: "领域描述"

expert_roles:
  - name: "专家角色1"
    expertise: ["专长1", "专长2"]
  - name: "专家角色2"
    expertise: ["专长1", "专长2"]

learning_goals:
  primary: "主要学习目标"
  secondary: []

phases:
  P0:
    name: "阶段名称"
    description: "阶段描述"
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
      required_concepts: ["概念1", "概念2"]

example_types:
  - "示例类型1"
  - "示例类型2"

asset_types:
  - "资产类型1"
  - "资产类型2"
```

## 使用新领域

1. **初始化学习日志**：
```bash
bash .claude/skills/universal-lesson/scripts/journal_init.sh {domain-identifier}
```

2. **开始学习**：
```
/universal-lesson {domain-identifier} P0
```

3. **继续学习**：
```
/universal-lesson {domain-identifier}
```

## 现有领域

- `ai-llm-agent`: AI/LLM/Agent 工程实践

## 数据隔离

每个领域的学习数据存储在独立的目录：
- `learning_journal/{domain-identifier}/learning_log.jsonl`
- `learning_journal/{domain-identifier}/concept_index.yaml`
- `learning_journal/{domain-identifier}/review_queue.yaml`
- `learning_journal/{domain-identifier}/phase_gates.yaml`
- `learning_journal/{domain-identifier}/assets/`

这样可以同时学习多个领域，数据互不干扰。
