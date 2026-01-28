"""
Chunking Service
Chunks documents by title and extracts images as separate chunks.
"""
from typing import List, Optional, Tuple
import structlog
import base64
import os

from unstructured.documents.elements import Element, Title, Image, Table
from unstructured.chunking.title import chunk_by_title

from app.config import get_settings
from app.models.schemas import ChunkData

logger = structlog.get_logger()


class ChunkingService:
    """Chunks documents by title and separates images as standalone chunks."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def chunk_elements(
        self,
        elements: List[Element],
        max_characters: Optional[int] = None,
        combine_text_under_n_chars: Optional[int] = None,
    ) -> Tuple[List[ChunkData], List[ChunkData]]:
        """
        Chunk elements by title/heading boundaries.
        Extracts images as separate chunks.
        
        Args:
            elements: List of parsed document elements
            max_characters: Maximum characters per chunk
            combine_text_under_n_chars: Combine small sections under this limit
            
        Returns:
            Tuple of (text_chunks, image_chunks)
        """
        max_chars = max_characters or self.settings.max_chunk_size
        combine_limit = combine_text_under_n_chars or (max_chars // 3)
        
        logger.info(
            "Starting chunking",
            element_count=len(elements),
            max_characters=max_chars
        )
        
        # First pass: Extract images as separate elements
        image_elements = []
        text_elements = []
        
        for el in elements:
            if isinstance(el, Image):
                image_elements.append(el)
            elif self._has_image_in_orig(el):
                # Extract images from composite elements
                extracted = self._extract_images_from_composite(el)
                image_elements.extend(extracted)
                text_elements.append(el)  # Keep the text part
            else:
                text_elements.append(el)
        
        # Filter images: keep only "meaningful" images (not icons, logos, decorative)
        filtered_images = []
        skipped_count = 0
        for img_el in image_elements:
            image_path = self._get_image_path(img_el)
            if image_path and self._is_meaningful_image(image_path):
                filtered_images.append(img_el)
            else:
                skipped_count += 1
        
        logger.info(
            f"🖼️ Image filtering: {len(filtered_images)} kept, {skipped_count} skipped (icons/small)"
        )
        
        # Create text chunks using standard chunking
        text_chunks = []
        current_section = "Document Start"
        
        if text_elements:
            chunked_elements = chunk_by_title(
                text_elements,
                max_characters=max_chars,
                combine_text_under_n_chars=combine_limit,
                new_after_n_chars=max_chars - 200,
            )
            
            for idx, chunk in enumerate(chunked_elements):
                if hasattr(chunk, 'metadata') and chunk.metadata:
                    if hasattr(chunk.metadata, 'section'):
                        current_section = chunk.metadata.section or current_section
                
                content = self._get_chunk_text(chunk)
                if not content.strip():
                    continue
                
                chunk_data = ChunkData(
                    content=content,
                    section_title=current_section,
                    chunk_index=idx,
                    chunk_type="text",
                    has_image=False,
                    metadata={
                        "element_type": type(chunk).__name__,
                        "char_count": len(content),
                    }
                )
                text_chunks.append(chunk_data)
                
                if isinstance(chunk, Title):
                    current_section = content[:100]
        
        # Create image chunks (only filtered meaningful images)
        image_chunks = []
        for idx, img_el in enumerate(filtered_images):
            image_path = self._get_image_path(img_el)
            
            # Placeholder content - will be replaced with AI summary
            content = f"[Image {idx + 1}]"
            
            chunk_data = ChunkData(
                content=content,
                section_title=current_section,
                chunk_index=len(text_chunks) + idx,
                chunk_type="image",
                has_image=True,
                metadata={
                    "element_type": "Image",
                    "image_path": image_path,
                }
            )
            image_chunks.append(chunk_data)
        
        logger.info(
            "Chunking complete",
            text_chunks=len(text_chunks),
            image_chunks=len(image_chunks)
        )
        
        return text_chunks, image_chunks
    
    def _is_meaningful_image(self, image_path: str) -> bool:
        """
        Filter out small icons, logos, and decorative images.
        
        Criteria:
        - File size > 10KB (skip tiny icons)
        - Image dimensions > 100x100 pixels (if detectable)
        """
        if not image_path or not os.path.exists(image_path):
            return False
        
        # Check file size (skip if < 10KB)
        file_size = os.path.getsize(image_path)
        if file_size < 10 * 1024:  # 10KB
            logger.debug(f"Skipping small image: {image_path} ({file_size} bytes)")
            return False
        
        # Try to check dimensions using PIL if available
        try:
            from PIL import Image as PILImage
            with PILImage.open(image_path) as img:
                width, height = img.size
                if width < 100 or height < 100:
                    logger.debug(f"Skipping tiny image: {image_path} ({width}x{height})")
                    return False
        except ImportError:
            pass  # PIL not available, skip dimension check
        except Exception:
            pass  # Can't read image, allow it through
        
        return True
    
    def _has_image_in_orig(self, element: Element) -> bool:
        """Check if composite element contains images in orig_elements."""
        if hasattr(element, 'metadata') and element.metadata:
            orig = getattr(element.metadata, 'orig_elements', None)
            if orig:
                return any(isinstance(el, Image) for el in orig)
        return False
    
    def _extract_images_from_composite(self, element: Element) -> List[Element]:
        """Extract Image elements from a composite element."""
        images = []
        if hasattr(element, 'metadata') and element.metadata:
            orig = getattr(element.metadata, 'orig_elements', None)
            if orig:
                for el in orig:
                    if isinstance(el, Image):
                        images.append(el)
        return images
    
    def _get_image_path(self, element: Element) -> Optional[str]:
        """Get image path from element metadata."""
        if hasattr(element, 'metadata') and element.metadata:
            return getattr(element.metadata, 'image_path', None)
        return None
    
    def _get_chunk_text(self, element: Element) -> str:
        """Extract text from a chunk element."""
        if hasattr(element, 'text'):
            text = str(element.text)
        else:
            text = str(element)
        
        if isinstance(element, Table):
            if hasattr(element, 'metadata') and hasattr(element.metadata, 'text_as_html'):
                text = f"[TABLE]\n{text}"
        
        return text.strip()
    
    def encode_image_to_b64(self, image_path: str) -> Optional[str]:
        """Encode an image file to base64 string."""
        if not image_path or not os.path.exists(image_path):
            return None
        
        try:
            with open(image_path, "rb") as f:
                data = f.read()
            
            # Determine MIME type
            ext = os.path.splitext(image_path)[1].lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            mime = mime_map.get(ext, "image/png")
            
            b64 = base64.b64encode(data).decode("utf-8")
            return f"data:{mime};base64,{b64}"
            
        except Exception as e:
            logger.error(f"Failed to encode image: {e}")
            return None
    
    def get_chunk_for_embedding(self, chunk: ChunkData) -> str:
        """
        Prepare chunk text for embedding.
        For image chunks, uses the AI summary.
        """
        parts = []
        
        if chunk.section_title:
            parts.append(f"Section: {chunk.section_title}")
        
        if chunk.chunk_type == "image" and chunk.image_summary:
            # For image chunks, embed the AI summary
            parts.append(f"Image Description: {chunk.image_summary}")
        else:
            parts.append(chunk.content)
        
        return "\n\n".join(parts)


# Singleton
_chunking_service: Optional[ChunkingService] = None


def get_chunking_service() -> ChunkingService:
    """Get singleton chunking service instance."""
    global _chunking_service
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service
