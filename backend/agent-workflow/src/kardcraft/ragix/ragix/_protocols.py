from typing import Protocol, runtime_checkable, List, Any
from ._types import Doc, Node, Relation, Ref, Answer


@runtime_checkable
class VectorStore(Protocol):
    async def upsert(self, doc_id: str, chunks: Any) -> bool: ...
    async def search(
        self, query: str, top_k: int, filter_expr: Any = None
    ) -> List[Any]: ...


@runtime_checkable
class GraphStore(Protocol):
    async def upsert(self, nodes: List[Any], rels: List[Any]) -> bool: ...
    async def search(self, query: str, limit: int) -> List[Any]: ...


@runtime_checkable
class Builder(Protocol):
    def build(self, path: str) -> None: ...
    def retriever(self, top_k: int = 30): ...
    def enrich(self, doc_ids: List[str], extractor: "Extractor") -> None: ...


@runtime_checkable
class Extractor(Protocol):
    def extract(self, doc: Doc) -> tuple[List[Node], List[Relation]]: ...


@runtime_checkable
class Refiner(Protocol):
    def refine(self, question: str, chunks: List[str]) -> Answer: ...
