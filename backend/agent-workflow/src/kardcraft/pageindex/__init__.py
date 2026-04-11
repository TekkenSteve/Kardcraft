"""Local PageIndex facade."""

from .api import build_document_tree
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
    "build_document_tree",
    "create_node_mapping",
    "flatten_nodes",
    "prune_nodes",
]
