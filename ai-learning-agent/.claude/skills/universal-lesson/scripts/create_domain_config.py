#!/usr/bin/env python3
"""
交互式创建新领域配置
"""
import yaml
from pathlib import Path
import sys

def create_domain_config():
    print("=" * 60)
    print("创建新领域学习配置")
    print("=" * 60)
    
    domain_identifier = input("\n领域标识符（英文，如：python-programming）: ").strip()
    if not domain_identifier:
        print("❌ 领域标识符不能为空")
        return None
    
    display_name = input("显示名称（中文，如：Python 编程）: ").strip()
    if not display_name:
        display_name = domain_identifier
    
    description = input("领域描述（可选）: ").strip()
    if not description:
        description = f"{display_name} 学习路径"
    
    print("\n" + "=" * 60)
    print("定义专家角色（至少2个）：")
    print("=" * 60)
    roles = []
    while len(roles) < 2:
        role_name = input(f"\n角色 {len(roles)+1} 名称: ").strip()
        if not role_name:
            if len(roles) >= 1:
                break
            print("⚠️  至少需要1个角色，继续...")
            continue
        expertise_str = input("专长（逗号分隔）: ").strip()
        expertise = [e.strip() for e in expertise_str.split(",") if e.strip()]
        if not expertise:
            expertise = ["领域专家"]
        roles.append({
            "name": role_name,
            "expertise": expertise
        })
        if len(roles) < 2:
            more = input("添加更多角色？(y/n, 默认y): ").strip().lower()
            if more == 'n':
                if len(roles) < 1:
                    print("⚠️  至少需要1个角色")
                    continue
                break
    
    primary_goal = input("\n主要学习目标: ").strip()
    if not primary_goal:
        primary_goal = f"掌握 {display_name} 核心能力"
    
    print("\n" + "=" * 60)
    print("定义课程阶段（至少1个）：")
    print("=" * 60)
    phases = {}
    phase_num = 0
    while True:
        phase_id = f"P{phase_num}"
        phase_name = input(f"\n阶段 {phase_id} 名称（回车结束）: ").strip()
        if not phase_name:
            if phase_num == 0:
                print("⚠️  至少需要1个阶段")
                continue
            break
        
        phase_desc = input(f"阶段 {phase_id} 描述（可选）: ").strip()
        if not phase_desc:
            phase_desc = f"{phase_name} 相关内容"
        
        print(f"\n  定义 {phase_id} 的课程：")
        lessons = []
        lesson_num = 1
        while True:
            lesson_title = input(f"  课程 L{lesson_num} 标题（回车结束）: ").strip()
            if not lesson_title:
                if lesson_num == 1:
                    print("    ⚠️  至少需要1个课程")
                    continue
                break
            concepts_str = input(f"    核心概念（逗号分隔）: ").strip()
            concepts = [c.strip() for c in concepts_str.split(",") if c.strip()]
            if not concepts:
                concepts = [lesson_title]
            lessons.append({
                "id": f"{phase_id}-L{lesson_num}",
                "title": lesson_title,
                "concepts": concepts
            })
            lesson_num += 1
        
        phases[phase_id] = {
            "name": phase_name,
            "description": phase_desc,
            "lessons": lessons
        }
        phase_num += 1
        
        more = input(f"\n添加更多阶段？(y/n, 默认n): ").strip().lower()
        if more != 'y':
            break
    
    print("\n" + "=" * 60)
    print("配置阶段门禁策略：")
    print("=" * 60)
    pass_mastery = input("通过掌握度阈值 (0-5, 默认3): ").strip()
    pass_mastery = int(pass_mastery) if pass_mastery else 3
    
    covered_ratio = input("覆盖比例要求 (0-1, 默认0.8): ").strip()
    covered_ratio = float(covered_ratio) if covered_ratio else 0.8
    
    freshness_days = input("新鲜度要求（天数, 默认14）: ").strip()
    freshness_days = int(freshness_days) if freshness_days else 14
    
    min_mastery_floor = input("最低掌握度底线 (0-5, 默认2): ").strip()
    min_mastery_floor = int(min_mastery_floor) if min_mastery_floor else 2
    
    print("\n" + "=" * 60)
    print("定义各阶段的门禁要求概念：")
    print("=" * 60)
    gates = {}
    for phase_id in phases.keys():
        print(f"\n阶段 {phase_id} ({phases[phase_id]['name']}) 的门禁要求：")
        required_str = input("必需概念（逗号分隔，可从该阶段的课程概念中选择）: ").strip()
        required = [c.strip() for c in required_str.split(",") if c.strip()]
        if not required:
            # 自动从该阶段的所有课程概念中提取
            all_concepts = []
            for lesson in phases[phase_id]["lessons"]:
                all_concepts.extend(lesson.get("concepts", []))
            required = list(set(all_concepts))[:5]  # 最多取5个
            print(f"  自动选择: {', '.join(required)}")
        gates[phase_id] = {
            "required_concepts": required
        }
    
    example_types_str = input("\n示例类型（逗号分隔，如：代码示例,实践案例, 默认：工程实践）: ").strip()
    example_types = [e.strip() for e in example_types_str.split(",") if e.strip()]
    if not example_types:
        example_types = ["工程实践"]
    
    asset_types_str = input("资产类型（逗号分隔，如：模板,检查清单, 默认：模板,清单）: ").strip()
    asset_types = [a.strip() for a in asset_types_str.split(",") if a.strip()]
    if not asset_types:
        asset_types = ["模板", "清单"]
    
    config = {
        "domain": {
            "name": display_name,
            "identifier": domain_identifier,
            "description": description
        },
        "expert_roles": roles,
        "learning_goals": {
            "primary": primary_goal,
            "secondary": []
        },
        "phases": phases,
        "phase_gates": {
            "policy": {
                "pass_mastery": pass_mastery,
                "covered_ratio": covered_ratio,
                "freshness_days": freshness_days,
                "min_mastery_floor": min_mastery_floor
            },
            "gates": gates
        },
        "example_types": example_types,
        "asset_types": asset_types
    }
    
    # 保存配置
    project_root = Path(__file__).parent.parent.parent.parent
    output_dir = project_root / "domain_configs"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{domain_identifier}.yaml"
    
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print("\n" + "=" * 60)
    print(f"✅ 配置已保存到: {output_path}")
    print("=" * 60)
    print("\n下一步：")
    print(f"1. 初始化学习日志: bash .claude/skills/universal-lesson/scripts/journal_init.sh {domain_identifier}")
    print(f"2. 开始学习: /universal-lesson {domain_identifier} P0")
    print("=" * 60)
    
    return output_path

if __name__ == "__main__":
    try:
        create_domain_config()
    except KeyboardInterrupt:
        print("\n\n❌ 已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
