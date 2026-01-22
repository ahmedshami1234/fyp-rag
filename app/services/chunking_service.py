"""
Chunking Service
Chunks documents by title using unstructured.io's chunking strategy.
"""
from typing import List, Optional
import structlog

from unstructured.documents.elements import Element, Title, Image, Table
from unstructured.chunking.title import chunk_by_title

from app.config import get_settings
from app.models.schemas import ChunkData

logger = structlog.get_logger()


class ChunkingService:
    """Chunks documents by title for semantic coherence."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def chunk_elements(
        self,
        elements: List[Element],
        max_characters: Optional[int] = None,
        combine_text_under_n_chars: Optional[int] = None,
    ) -> List[ChunkData]:
        """
        Chunk elements by title/heading boundaries.
        
        Args:
            elements: List of parsed document elements
            max_characters: Maximum characters per chunk (default from settings)
            combine_text_under_n_chars: Combine small sections under this limit
            
        Returns:
            List of ChunkData objects ready for embedding
        """
        max_chars = max_characters or self.settings.max_chunk_size
        combine_limit = combine_text_under_n_chars or (max_chars // 3)
        
        logger.info(
            "Starting chunking",
            element_count=len(elements),
            max_characters=max_chars,
            combine_under=combine_limit
        )
        
        # Use unstructured's chunk_by_title
        chunked_elements = chunk_by_title(
            elements,
            max_characters=max_chars,
            combine_text_under_n_chars=combine_limit,
            new_after_n_chars=max_chars - 200,  # Soft limit before forcing split
        )
        
        # Convert to ChunkData format
        chunks = []
        current_section = "Document Start"
        
        for idx, chunk in enumerate(chunked_elements):
            # Extract section title from metadata if available
            if hasattr(chunk, 'metadata') and chunk.metadata:
                if hasattr(chunk.metadata, 'section'):
                    current_section = chunk.metadata.section or current_section
            
            # Determine if chunk contains visual elements
            has_image = self._contains_visual_content(chunk)
            
            # Get the text content
            content = self._get_chunk_text(chunk)
            
            if not content.strip():
                continue  # Skip empty chunks
            
            chunk_data = ChunkData(
                content=content,
                section_title=current_section,
                chunk_index=idx,
                has_image=has_image,
                metadata={
                    "element_type": type(chunk).__name__,
                    "char_count": len(content),
                }
            )
            chunks.append(chunk_data)
            
            # Update section title if this is a title element
            if isinstance(chunk, Title):
                current_section = content[:100]  # Limit title length
        
        logger.info(
            "Chunking complete",
            chunk_count=len(chunks),
            visual_chunks=sum(1 for c in chunks if c.has_image)
        )
        
        return chunks
    
    def _contains_visual_content(self, element: Element) -> bool:
        """Check if element or its children contain visual content."""
        if isinstance(element, (Image, Table)):
            return True
        
        # Check metadata for image references
        if hasattr(element, 'metadata') and element.metadata:
            if hasattr(element.metadata, 'image_path') and element.metadata.image_path:
                return True
            if hasattr(element.metadata, 'text_as_html') and element.metadata.text_as_html:
                # Tables often have HTML representation
                if '<table' in str(element.metadata.text_as_html).lower():
                    return True
        
        return False
    
    def _get_chunk_text(self, element: Element) -> str:
        """Extract text from a chunk element."""
        if hasattr(element, 'text'):
            text = str(element.text)
        else:
            text = str(element)
        
        # If it's a table with HTML, include a note
        if isinstance(element, Table):
            if hasattr(element, 'metadata') and hasattr(element.metadata, 'text_as_html'):
                text = f"[TABLE]\n{text}"
        
        return text.strip()
    
    def get_chunk_for_embedding(self, chunk: ChunkData) -> str:
        """
        Prepare chunk text for embedding.
        Combines content with image summary if available.
        
        Args:
            chunk: ChunkData object
            
        Returns:
            Text ready for embedding
        """
        parts = []
        
        # Add section context
        if chunk.section_title:
            parts.append(f"Section: {chunk.section_title}")
        
        # Add main content
        parts.append(chunk.content)
        
        # Add image summary if available
        if chunk.image_summary:
            parts.append(f"\n[AI Visual Description]: {chunk.image_summary}")
        
        return "\n\n".join(parts)


# Singleton instance
_chunking_service: Optional[ChunkingService] = None


def get_chunking_service() -> ChunkingService:
    """Get singleton chunking service instance."""
    global _chunking_service
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service
