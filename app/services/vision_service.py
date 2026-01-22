"""
Vision Service
Uses GPT-4o to generate summaries for visual content (images, tables, figures).
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
    
    VISION_PROMPT = """You are a document analysis assistant. Analyze the visual content provided and generate a concise, informative summary.

For TABLES:
- Describe the structure (rows, columns)
- Summarize the key data and patterns
- Note any important values or trends

For IMAGES/FIGURES/CHARTS:
- Describe what the image shows
- Explain any data, trends, or key information
- Note labels, legends, and important details

For DIAGRAMS:
- Describe the components and their relationships
- Explain the flow or structure being depicted

Keep your summary factual and under 200 words. Focus on information that would be useful for semantic search and question answering."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def summarize_visual(
        self,
        content: str,
        image_path: Optional[str] = None,
        context: Optional[str] = None
    ) -> str:
        """
        Generate a text summary for visual content.
        
        Args:
            content: Text representation of the visual (table HTML, figure caption)
            image_path: Optional path to image file for vision analysis
            context: Optional surrounding text for better understanding
            
        Returns:
            Text summary of the visual content
        """
        logger.info("Generating visual summary", has_image=bool(image_path))
        
        messages = [
            {"role": "system", "content": self.VISION_PROMPT}
        ]
        
        # Build user message
        user_content = []
        
        # Add context if available
        if context:
            user_content.append({
                "type": "text",
                "text": f"Context from document:\n{context[:500]}\n\n"
            })
        
        # Add text content (table HTML, captions, etc.)
        user_content.append({
            "type": "text",
            "text": f"Visual content to analyze:\n{content}"
        })
        
        # Add image if available
        if image_path and os.path.exists(image_path):
            try:
                base64_image = self._encode_image(image_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "high"
                    }
                })
            except Exception as e:
                logger.warning("Failed to encode image", error=str(e))
        
        messages.append({"role": "user", "content": user_content})
        
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.vision_model,
                messages=messages,
                max_tokens=300,
                temperature=0.3  # Lower temperature for factual descriptions
            )
            
            summary = response.choices[0].message.content
            logger.info("Visual summary generated", length=len(summary))
            return summary
            
        except Exception as e:
            logger.error("Failed to generate visual summary", error=str(e))
            # Return a fallback description
            return f"[Visual content: Unable to generate summary. Original content: {content[:200]}...]"
    
    async def process_visual_chunks(
        self,
        chunks: List[ChunkData]
    ) -> List[ChunkData]:
        """
        Process all chunks and add summaries for visual content.
        
        Args:
            chunks: List of ChunkData objects
            
        Returns:
            Updated chunks with image_summary populated for visual chunks
        """
        visual_chunks = [c for c in chunks if c.has_image]
        logger.info("Processing visual chunks", count=len(visual_chunks))
        
        for chunk in visual_chunks:
            try:
                # Get image path from metadata if available
                image_path = chunk.metadata.get("image_path")
                
                # Get context from surrounding chunks
                context = self._get_chunk_context(chunk, chunks)
                
                summary = await self.summarize_visual(
                    content=chunk.content,
                    image_path=image_path,
                    context=context
                )
                
                chunk.image_summary = summary
                
            except Exception as e:
                logger.error(
                    "Failed to process visual chunk",
                    chunk_index=chunk.chunk_index,
                    error=str(e)
                )
                chunk.image_summary = f"[Visual content at chunk {chunk.chunk_index}]"
        
        return chunks
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def _get_chunk_context(
        self,
        chunk: ChunkData,
        all_chunks: List[ChunkData],
        window: int = 1
    ) -> str:
        """Get surrounding context for a chunk."""
        idx = chunk.chunk_index
        context_parts = []
        
        # Get previous chunk
        if idx > 0:
            prev_chunk = next(
                (c for c in all_chunks if c.chunk_index == idx - 1),
                None
            )
            if prev_chunk:
                context_parts.append(prev_chunk.content[:200])
        
        # Get next chunk
        next_chunk = next(
            (c for c in all_chunks if c.chunk_index == idx + 1),
            None
        )
        if next_chunk:
            context_parts.append(next_chunk.content[:200])
        
        return " ... ".join(context_parts)


# Singleton instance
_vision_service: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    """Get singleton vision service instance."""
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service
