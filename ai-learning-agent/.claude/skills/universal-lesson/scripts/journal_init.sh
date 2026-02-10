#!/usr/bin/env bash
set -euo pipefail

# 支持领域参数
DOMAIN=${1:-"default"}
PROJECT_ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
JOURNAL_DIR="$PROJECT_ROOT/learning_journal/$DOMAIN"
CONFIG_FILE="$PROJECT_ROOT/domain_configs/${DOMAIN}.yaml"

mkdir -p "$JOURNAL_DIR/assets"
touch "$JOURNAL_DIR/learning_log.jsonl"

# 从领域配置读取阶段列表
if [ -f "$CONFIG_FILE" ]; then
  # 使用 Python 解析 YAML 并生成概念索引
  python3 <<PYTHON
import yaml
import sys

try:
    with open("$CONFIG_FILE", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    phases = config.get("phases", {})
    concept_index = {}
    
    for phase_id in phases.keys():
        concept_index[phase_id] = []
    
    # 输出 YAML
    print("domains:")
    print(f"  {config['domain']['identifier']}:")
    for phase_id, concepts in concept_index.items():
        print(f"    {phase_id}: []")
except Exception as e:
    print(f"# Error loading config: {e}", file=sys.stderr)
    print("domains:")
    print(f"  $DOMAIN:")
    print("    P0: []")
PYTHON > "$JOURNAL_DIR/concept_index.yaml"
else
  # 默认结构
  cat > "$JOURNAL_DIR/concept_index.yaml" <<YAML
domains:
  $DOMAIN:
    P0: []
YAML
fi

# 初始化复习队列
if [ ! -f "$JOURNAL_DIR/review_queue.yaml" ]; then
  cat > "$JOURNAL_DIR/review_queue.yaml" <<YAML
domains:
  $DOMAIN: []
YAML
fi

# 从领域配置同步阶段门禁
if [ -f "$CONFIG_FILE" ]; then
  python3 <<PYTHON
import yaml
import sys

try:
    with open("$CONFIG_FILE", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    domain_id = config['domain']['identifier']
    phase_gates = config.get("phase_gates", {})
    
    # 输出 YAML
    print("domains:")
    print(f"  {domain_id}:")
    print("    policy:")
    policy = phase_gates.get("policy", {})
    print(f"      pass_mastery: {policy.get('pass_mastery', 3)}")
    print(f"      covered_ratio: {policy.get('covered_ratio', 0.8)}")
    print(f"      freshness_days: {policy.get('freshness_days', 14)}")
    print(f"      min_mastery_floor: {policy.get('min_mastery_floor', 2)}")
    print("    gates:")
    gates = phase_gates.get("gates", {})
    for phase_id, gate_config in gates.items():
        print(f"      {phase_id}:")
        print("        required_concepts:")
        for concept in gate_config.get("required_concepts", []):
            print(f"          - {concept}")
except Exception as e:
    print(f"# Error loading config: {e}", file=sys.stderr)
    print("domains:")
    print(f"  $DOMAIN:")
    print("    policy:")
    print("      pass_mastery: 3")
    print("      covered_ratio: 0.8")
    print("      freshness_days: 14")
    print("      min_mastery_floor: 2")
    print("    gates:")
    print("      P0:")
    print("        required_concepts: []")
PYTHON > "$JOURNAL_DIR/phase_gates.yaml"
else
  # 默认门禁配置
  cat > "$JOURNAL_DIR/phase_gates.yaml" <<YAML
domains:
  $DOMAIN:
    policy:
      pass_mastery: 3
      covered_ratio: 0.8
      freshness_days: 14
      min_mastery_floor: 2
    gates:
      P0:
        required_concepts: []
YAML
fi

echo "Initialized learning_journal/$DOMAIN/"
