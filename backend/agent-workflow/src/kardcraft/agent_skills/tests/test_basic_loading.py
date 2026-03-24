"""
Basic tests for agent_skills loading functionality.

Run with:
    cd backend/agent-workflow/src
    python -m kardcraft.agent_skills.tests.test_basic_loading
"""

from kardcraft.agent_skills import list_skills, SkillMetadata
from pathlib import Path


def test_load_test_skill():
    """Test loading the architecture-extractor skill from tests directory."""
    print("\n" + "="*60)
    print("测试 1: 加载测试 skill (architecture-extractor)")
    print("="*60)
    
    skills_dir = Path(__file__).parent
    skills = list_skills(project_skills_dir=skills_dir)
    
    print(f'✅ 找到 {len(skills)} 个 skill')
    
    for skill in skills:
        print(f'\n  Skill: {skill["name"]}')
        print(f'  Description: {skill["description"]}')
        print(f'  Path: {skill["path"]}')
        print(f'  Source: {skill["source"]}')
        
        # 验证文件存在
        skill_path = Path(skill['path'])
        assert skill_path.exists(), f"Skill file not found: {skill_path}"
        
        # 验证可以读取内容
        content = skill_path.read_text(encoding='utf-8')
        assert len(content) > 0, f"Skill file is empty: {skill_path}"
        print(f'  ✓ 文件可读 ({len(content)} 字节)')
    
    return True


def test_load_project_skills():
    """Test loading skills from .deepagents/skills directory."""
    print("\n" + "="*60)
    print("测试 2: 加载项目 skills (.deepagents/skills)")
    print("="*60)
    
    # 从当前文件向上找到 kardcraft 目录
    current_file = Path(__file__)
    kardcraft_dir = current_file.parent.parent.parent
    skills_dir = kardcraft_dir / '.deepagents' / 'skills'
    
    print(f'📂 Skills 目录: {skills_dir}')
    print(f'📂 绝对路径: {skills_dir.absolute()}')
    print(f'📂 目录存在: {skills_dir.exists()}')
    
    if not skills_dir.exists():
        print('⚠️  目录不存在，跳过测试')
        return True
    
    skills = list_skills(project_skills_dir=skills_dir)
    print(f'✅ 找到 {len(skills)} 个 skill')
    
    # 只显示前 5 个
    for skill in skills[:5]:
        print(f'  - {skill["name"]}: {skill["description"][:60]}...')
    
    if len(skills) > 5:
        print(f'  ... 还有 {len(skills) - 5} 个 skills')
    
    return True


def test_skill_content_reading():
    """Test reading skill content."""
    print("\n" + "="*60)
    print("测试 3: 读取 skill 内容")
    print("="*60)
    
    skills_dir = Path(__file__).parent
    skills = list_skills(project_skills_dir=skills_dir)
    
    if not skills:
        print('⚠️  没有找到 skills')
        return False
    
    skill = skills[0]
    print(f'✅ Skill: {skill["name"]}')
    
    # 读取 SKILL.md 内容
    skill_path = Path(skill['path'])
    content = skill_path.read_text(encoding='utf-8')
    
    print(f'✅ 内容长度: {len(content)} 字节')
    print(f'✅ 前 200 个字符:')
    print(content[:200])
    print('...')
    
    return True


def test_imports():
    """Test that all imports work correctly."""
    print("\n" + "="*60)
    print("测试 4: 模块导入")
    print("="*60)
    
    from kardcraft.agent_skills import (
        list_skills, 
        SkillMetadata,
        SkillsMiddleware, 
        NoSkillsMiddleware,
        ShellMiddleware
    )
    
    print('✅ 所有模块导入成功')
    print(f'  - list_skills: {type(list_skills).__name__}')
    print(f'  - SkillMetadata: {SkillMetadata}')
    print(f'  - SkillsMiddleware: {SkillsMiddleware.__name__}')
    print(f'  - NoSkillsMiddleware: {NoSkillsMiddleware.__name__}')
    print(f'  - ShellMiddleware: {ShellMiddleware.__name__}')
    
    return True


if __name__ == "__main__":
    print("="*60)
    print("Agent Skills 基础功能测试")
    print("="*60)
    
    tests = [
        test_imports,
        test_load_test_skill,
        test_skill_content_reading,
        test_load_project_skills,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
                print(f'❌ {test.__name__} 失败')
        except Exception as e:
            failed += 1
            print(f'❌ {test.__name__} 出错: {e}')
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*60)
    
    if failed == 0:
        print("✅ 所有测试通过!")
    else:
        print("❌ 有测试失败")
