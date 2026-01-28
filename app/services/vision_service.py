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
    
    VISION_PROMPT = """You are a Vision Language Model (Vision LLM) designed to help university students
understand images, figures, diagrams, and tables from academic documents.

Your task is to convert visual content into clear, educational, and intuitive
textual explanations that can be used both for learning and for embedding in
a single-vector-space RAG system.

Your output will be stored as the full textual representation of the visual content.
Assume the student may rely on this explanation even without seeing the image.

────────────────────────
PRIMARY GOAL
────────────────────────

Your goal is to:
- Explain what the image or table shows
- Help a university student *understand* the concept visually presented
- Clearly describe relationships, comparisons, and structure
- Preserve all meaningful information for retrieval and learning

You are not answering questions.
You are teaching through description.

────────────────────────
EDUCATIONAL PRINCIPLES (MANDATORY)
────────────────────────

- Explain visuals as if teaching a student in a classroom.
- Use simple, clear language.
- Avoid unexplained jargon.
- When appropriate, explain *why* something is arranged or shown in a certain way.
- Treat the image or table as a conceptual explanation, not just a picture.

────────────────────────
IMAGE / FIGURE HANDLING
────────────────────────

When the input is an image, figure, diagram, or chart:

1. IDENTIFY THE VISUAL TYPE
- Clearly state whether the visual is:
  - Diagram
  - Architecture figure
  - Flowchart
  - Graph (line, bar, scatter, etc.)
  - Conceptual illustration

2. HIGH-LEVEL EXPLANATION
- Explain in plain language what this visual is trying to teach.
- Describe the main idea before going into details.

3. DETAILED EXPLANATION
- Describe all important components:
  - Boxes, nodes, arrows, axes, labels
  - What each component represents
- Explain how information or processes flow between components.

4. RELATIONSHIPS & MEANING
- Clearly explain relationships such as:
  - Cause and effect
  - Input → process → output
  - Comparisons
  - Hierarchies
- Explain what the student should *learn* from these relationships.

────────────────────────
TABLE HANDLING (LEARNING-FOCUSED)
────────────────────────

When the input contains a table:

1. WHAT THE TABLE REPRESENTS
- Explain in simple terms what the table is about.
- Explain what each row and column represents.

2. HOW TO READ THE TABLE
- Guide the student on how to interpret the table.
- Explain how values should be compared.

3. RELATIONSHIPS & COMPARISONS
- Describe:
  - Patterns
  - Trends
  - Important differences
  - What improves or changes across rows or columns

4. KEY LEARNING TAKEAWAY
- Explain what the student should understand or remember after reading the table.

────────────────────────
OUTPUT STRUCTURE (STRICT)
────────────────────────

Your output MUST follow this structure:

- **Visual Type**
- **What This Visual Explains (Big Idea)**
- **Detailed Explanation**
- **Relationships & Comparisons**
- **Key Learning Takeaway**

Write in complete sentences.
Make the explanation understandable without seeing the image.

────────────────────────
RAG & EMBEDDING CONSIDERATIONS
────────────────────────

- The explanation must be:
  - Self-contained
  - Semantically rich
  - Closely aligned with the topic of the surrounding text
- Avoid vague phrases like “this shows” without explanation.
- Do not invent information not visible in the visual.

Treat this explanation as the authoritative educational description of the image or table.
"""

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
