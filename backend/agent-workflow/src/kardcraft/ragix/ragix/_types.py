# ragix/_types.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Doc(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embeddings: Optional[List[float]] = None

class Node(BaseModel):
    id: str
    label: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class Relation(BaseModel):
    src: str
    dst: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class Ref(BaseModel):
    text: str
    metadata: Dict[str, Any]
    score: float

class Answer(BaseModel):
    text: str
    citations: List[Ref]