"""Local PageIndex facade."""

from .api import build_document_tree_async
from .contracts import (
    DocumentNode,
    DocumentTree,
    NodeRef,
    PageIndexBuildConfig,
    create_node_mapping,
    flatten_nodes,
    prune_nodes,
)

__all__ = [
    "DocumentNode",
    "DocumentTree",
    "NodeRef",
    "PageIndexBuildConfig",
    "build_document_tree_async",
    "create_node_mapping",
    "flatten_nodes",
    "prune_nodes",
]
