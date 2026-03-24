# ragix/__init__.py
"""
Ragix - 真正组件化的 RAG 框架

基于以下设计原则：
- 组合优于继承：功能作为独立组件组合，而非继承层次
- 依赖注入：所有组件通过配置注入，而非硬编码
- 装饰器模式：功能通过装饰器添加，而非修改基类
- 协议驱动：清晰的接口定义，而非具体实现绑定
- 策略模式：算法作为可替换策略

使用示例：
    # 基础用法
    from ragix import RagixClient

    client = RagixClient()
    await client.add_document("document.pdf")
    answer = await client.query("什么是机器学习？")

    # 高级用法
    # 使用环境变量 / .env.ragix 配置 LightRAG Server 地址与鉴权
    client = RagixClient()
    await client.initialize()
"""

# 核心客户端
from .core.ragix_client import RagixClient
from .core.container import RagixContainer

# 数据类型
from ._types import Doc, Answer, Ref, Node, Relation

# 协议类型
from ._protocols import GraphStore, VectorStore

__version__ = "2.0.0"

__all__ = [
    # 核心类
    "RagixClient",
    "RagixContainer",
    # 数据类型
    "Doc",
    "Answer",
    "Ref",
    "Node",
    "Relation",
    # 协议类型
    "VectorStore",
    "GraphStore",
]


# 便捷创建函数
def create_client() -> RagixClient:
    """
    创建 Ragix 客户端的便捷函数

    Args:
    Returns:
        RagixClient: 客户端实例
    """
    return RagixClient()
