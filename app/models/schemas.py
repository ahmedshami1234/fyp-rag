"""
Data models for the RAG pipeline.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import uuid4

class ChunkData(BaseModel):
    """Internal model for document chunks during processing."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    section_title: Optional[str] = None
    chunk_index: int
    chunk_type: str = "text"  # "text" or "image"
    has_image: bool = False
    image_summary: Optional[str] = None
    image_b64: Optional[str] = None  # Base64 encoded image for image chunks
    metadata: Dict[str, Any] = {}

class ChunkResult(BaseModel):
    """Model for search results returned from vector query."""
    content: str
    score: float
    document_id: str
    file_name: str
    section_title: Optional[str] = None
    chunk_index: int
    has_image: bool = False
