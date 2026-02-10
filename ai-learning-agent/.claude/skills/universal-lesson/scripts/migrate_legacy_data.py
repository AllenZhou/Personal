#!/usr/bin/env python3
"""
迁移旧格式数据到新格式（支持多领域）
"""
import json
import yaml
from pathlib import Path
from datetime import datetime

def migrate_concept_index(old_path: Path, new_path: Path, domain: str):
    """迁移概念索引"""
    if not old_path.exists():
        print(f"⚠️  {old_path} 不存在，跳过")
        return
    
    with old_path.open("r", encoding="utf-8") as f:
        old_data = yaml.safe_load(f) or {}
    
    # 转换为新格式
    new_data = {
        "domains": {
            domain: old_data
        }
    }
    
    new_path.parent.mkdir(parents=True, exist_ok=True)
    with new_path.open("w", encoding="utf-8") as f:
        yaml.dump(new_data, f, allow_unicode=True, sort_keys=False)
    
    print(f"✅ 迁移概念索引: {old_path} -> {new_path}")

def migrate_review_queue(old_path: Path, new_path: Path, domain: str):
    """迁移复习队列"""
    if not old_path.exists():
        print(f"⚠️  {old_path} 不存在，跳过")
        return
    
    with old_path.open("r", encoding="utf-8") as f:
        old_data = yaml.safe_load(f) or []
    
    if not isinstance(old_data, list):
        old_data = []
    
    # 转换为新格式
    new_data = {
        "domains": {
            domain: old_data
        }
    }
    
    new_path.parent.mkdir(parents=True, exist_ok=True)
    with new_path.open("w", encoding="utf-8") as f:
        yaml.dump(new_data, f, allow_unicode=True, sort_keys=False)
    
    print(f"✅ 迁移复习队列: {old_path} -> {new_path}")

def migrate_phase_gates(old_path: Path, new_path: Path, domain: str):
    """迁移阶段门禁"""
    if not old_path.exists():
        print(f"⚠️  {old_path} 不存在，跳过")
        return
    
    with old_path.open("r", encoding="utf-8") as f:
        old_data = yaml.safe_load(f) or {}
    
    # 转换为新格式
    new_data = {
        "domains": {
            domain: old_data
        }
    }
    
    new_path.parent.mkdir(parents=True, exist_ok=True)
    with new_path.open("w", encoding="utf-8") as f:
        yaml.dump(new_data, f, allow_unicode=True, sort_keys=False)
    
    print(f"✅ 迁移阶段门禁: {old_path} -> {new_path}")

def migrate_learning_log(old_path: Path, new_path: Path, domain: str):
    """迁移学习日志"""
    if not old_path.exists():
        print(f"⚠️  {old_path} 不存在，跳过")
        return
    
    count = 0
    new_path.parent.mkdir(parents=True, exist_ok=True)
    
    with old_path.open("r", encoding="utf-8") as f_in, \
         new_path.open("w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # 添加 domain 字段
                if "domain" not in record:
                    record["domain"] = domain
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
            except Exception as e:
                print(f"⚠️  跳过无效日志行: {e}")
                continue
    
    print(f"✅ 迁移学习日志: {old_path} -> {new_path} ({count} 条记录)")

def main():
    import sys
    
    domain = sys.argv[1] if len(sys.argv) > 1 else "ai-llm-agent"
    project_root = Path(__file__).parent.parent.parent.parent
    
    old_journal = project_root / "learning_journal"
    new_journal = project_root / "learning_journal" / domain
    
    if not old_journal.exists():
        print(f"❌ 旧的学习日志目录不存在: {old_journal}")
        return
    
    print(f"🚀 开始迁移数据到领域: {domain}")
    print(f"📁 源目录: {old_journal}")
    print(f"📁 目标目录: {new_journal}")
    print()
    
    # 迁移各项数据
    migrate_concept_index(
        old_journal / "concept_index.yaml",
        new_journal / "concept_index.yaml",
        domain
    )
    
    migrate_review_queue(
        old_journal / "review_queue.yaml",
        new_journal / "review_queue.yaml",
        domain
    )
    
    migrate_phase_gates(
        old_journal / "phase_gates.yaml",
        new_journal / "phase_gates.yaml",
        domain
    )
    
    migrate_learning_log(
        old_journal / "learning_log.jsonl",
        new_journal / "learning_log.jsonl",
        domain
    )
    
    # 迁移 assets 目录
    old_assets = old_journal / "assets"
    new_assets = new_journal / "assets"
    if old_assets.exists():
        import shutil
        if new_assets.exists():
            print(f"⚠️  {new_assets} 已存在，跳过 assets 迁移")
        else:
            shutil.copytree(old_assets, new_assets)
            print(f"✅ 迁移 assets: {old_assets} -> {new_assets}")
    
    print()
    print("✅ 迁移完成！")
    print(f"\n下一步：使用 /universal-lesson {domain} 开始学习")

if __name__ == "__main__":
    main()
