"""Standalone runner for Syllabus Agent."""

import asyncio
from .builder import build_syllabus_agent


async def main():
    """Test the syllabus agent."""

    # Build the agent
    agent = build_syllabus_agent()

    # Test case
    test_input = {
        "user_input": "帮我设计一个微积分课程大纲",
        "user_knowledge": """
        微积分是数学的一个重要分支，主要研究函数的极限、导数和积分。
        
        极限是微积分的基础概念，描述函数在某点附近的行为。
        导数表示函数的瞬时变化率，是极限的一个重要应用。
        积分是导数的逆运算，用于计算面积和体积。
        
        微分方程是包含未知函数及其导数的方程。
        偏导数用于多元函数的分析。
        """,
        "subject_domain": "mathematics",
        "complexity_level": "intermediate",
        "file_ids": [],
        "session_id": None,
        "user_id": None,
    }

    print("=== Syllabus Agent Test ===")
    print(f"Content: {test_input['user_input'][:100]}...")

    try:
        result = await agent.ainvoke(test_input)

        print(f"\n概念数量: {result.get('total_concepts', 0)}")
        print(f"学习时间: {result.get('estimated_learning_time', 0)} 分钟")
        print(f"难度分布: {result.get('difficulty_distribution', {})}")

        print("\n知识节点:")
        for node in result.get("knowledge_nodes", [])[:5]:  # Show first 5
            print(f"  - {node['title']} (Level {node['level']})")

        print(f"\n拓扑顺序: {result.get('topological_order', [])}")

        if result.get("error"):
            print(f"\n错误: {result['error']}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
