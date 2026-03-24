# implementations/storage/__init__.py - 存储组件实现模块
"""
存储组件实现

支持多种存储后端：
- MinIO: 对象存储
- Milvus: 向量存储
- Neo4j: 图存储
"""

from .minio import MinIOStorage

# 尝试导入向量存储和图存储
try:
    from .milvus import MilvusVectorStore, MilvusConfig
except ImportError:
    MilvusVectorStore = None
    MilvusConfig = None

try:
    from .neo4j import Neo4jGraphStore, Neo4jConfig
except ImportError:
    Neo4jGraphStore = None
    Neo4jConfig = None

__all__ = [
    "MinIOStorage",
    "MilvusVectorStore",
    "MilvusConfig",
    "Neo4jGraphStore",
    "Neo4jConfig",
]
