"""
Vision Service
Uses GPT-4o to generate summaries for images and visual content.
"""
import base64
import os
from typing import List, Optional
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models.schemas import ChunkData

logger = structlog.get_logger()


class VisionService:
    """Generates text summaries for visual content using GPT-4o Vision."""
    
    VISION_PROMPT = """You are a document analysis assistant. Analyze the image and generate a detailed, informative description.

For CHARTS/GRAPHS:
- Describe the type of chart (bar, line, pie, etc.)
- Summarize the key data, trends, and patterns
- Note axis labels, legends, and important values

For DIAGRAMS:
- Describe the components and their relationships
- Explain the flow or structure being depicted
- Note any labels or annotations

For PHOTOS/ILLUSTRATIONS:
- Describe what the image shows
- Note any text visible in the image
- Explain the context and purpose

For TABLES:
- Describe the structure (rows, columns)
- Summarize the key data and patterns

Keep your summary factual and under 200 words. Focus on information useful for semantic search."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def summarize_image(self, image_path: str, context: Optional[str] = None) -> str:
        """
        Generate a text summary for an image using GPT-4o Vision.
        
        Args:
            image_path: Path to the image file
            context: Optional surrounding text for better understanding
            
        Returns:
            Text summary of the image
        """
        if not image_path or not os.path.exists(image_path):
            return "[Image: File not found]"
        
        logger.info(f"🔍 AI Vision: Analyzing {os.path.basename(image_path)}...")
        
        # Encode image
        b64_image = self._encode_image(image_path)
        
        # Determine MIME type
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")
        
        # Build messages
        messages = [{"role": "system", "content": self.VISION_PROMPT}]
        
        user_content = []
        if context:
            user_content.append({
                "type": "text",
                "text": f"Context from document:\n{context[:500]}\n\nDescribe this image:"
            })
        else:
            user_content.append({
                "type": "text",
                "text": "Describe this image in detail:"
            })
        
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{b64_image}",
                "detail": "high"
            }
        })
        
        messages.append({"role": "user", "content": user_content})
        
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.vision_model,
                messages=messages,
                max_tokens=300,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content
            snippet = summary[:80].replace('\n', ' ') + "..."
            logger.info(f"✅ AI Vision: {snippet}")
            return summary
            
        except Exception as e:
            logger.error(f"Vision API failed: {e}")
            return f"[Image: Unable to analyze - {str(e)[:50]}]"
    
    async def process_image_chunks(
        self,
        image_chunks: List[ChunkData],
        text_chunks: List[ChunkData],
        chunking_service
    ) -> List[ChunkData]:
        """
        Process image chunks: generate AI summaries and encode to b64.
        
        Args:
            image_chunks: List of image ChunkData objects
            text_chunks: List of text chunks for context
            chunking_service: ChunkingService instance for b64 encoding
            
        Returns:
            Updated image chunks with content=summary and image_b64 set
        """
        if not image_chunks:
            return image_chunks
        
        logger.info(f"👁️ Processing {len(image_chunks)} image chunks with GPT-4o Vision...")
        
        for chunk in image_chunks:
            image_path = chunk.metadata.get("image_path")
            
            if not image_path:
                chunk.content = "[Image: No file path available]"
                chunk.image_summary = chunk.content
                continue
            
            # Get context from nearby text chunks
            context = self._get_context_from_text_chunks(text_chunks)
            
            # Generate AI summary
            summary = await self.summarize_image(image_path, context)
            
            # Set the summary as the content (this gets embedded)
            chunk.content = summary
            chunk.image_summary = summary
            
            # Encode image to b64 for metadata
            chunk.image_b64 = chunking_service.encode_image_to_b64(image_path)
            
            if chunk.image_b64:
                # Check size - Pinecone has 40KB metadata limit
                b64_size = len(chunk.image_b64)
                if b64_size > 35000:  # Leave room for other metadata
                    logger.warning(f"⚠️ Image b64 too large ({b64_size} bytes), truncating...")
                    # Store a note instead of the full image
                    chunk.image_b64 = None
                    chunk.metadata["image_too_large"] = True
        
        return image_chunks
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def _get_context_from_text_chunks(self, text_chunks: List[ChunkData], max_chars: int = 500) -> str:
        """Get context from nearby text chunks."""
        if not text_chunks:
            return ""
        
        # Use last few text chunks as context
        context_chunks = text_chunks[-3:]
        context = " ".join([c.content[:200] for c in context_chunks])
        return context[:max_chars]


# Singleton
_vision_service: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """Get singleton vision service instance."""
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service
