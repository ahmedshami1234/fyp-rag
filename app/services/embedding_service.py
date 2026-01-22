"""
Embedding Service
Generates vector embeddings using OpenAI's text-embedding-3-large model.
"""
from typing import List
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models.schemas import ChunkData
from app.services.chunking_service import get_chunking_service

logger = structlog.get_logger()


class EmbeddingService:
    """Generates embeddings using OpenAI's embedding models."""
    
    # Maximum tokens per request (model limit)
    MAX_TOKENS_PER_REQUEST = 8191
    # Batch size for embedding requests
    BATCH_SIZE = 100
    
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.chunking_service = get_chunking_service()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector (3072 dimensions)
        """
        # Truncate if too long (rough estimate: 4 chars per token)
        max_chars = self.MAX_TOKENS_PER_REQUEST * 4
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.warning("Text truncated for embedding", original_length=len(text))
        
        response = await self.client.embeddings.create(
            model=self.settings.embedding_model,
            input=text,
            dimensions=self.settings.embedding_dimensions
        )
        
        return response.data[0].embedding
    
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        logger.info("Generating embeddings", count=len(texts))
        
        all_embeddings = []
        
        # Process in batches
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            
            # Truncate long texts
            batch = [
                t[:self.MAX_TOKENS_PER_REQUEST * 4] if len(t) > self.MAX_TOKENS_PER_REQUEST * 4 else t
                for t in batch
            ]
            
            try:
                response = await self.client.embeddings.create(
                    model=self.settings.embedding_model,
                    input=batch,
                    dimensions=self.settings.embedding_dimensions
                )
                
                # Extract embeddings in order
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
                logger.info(
                    "Batch embedded",
                    batch_num=i // self.BATCH_SIZE + 1,
                    batch_size=len(batch)
                )
                
            except Exception as e:
                logger.error("Batch embedding failed", error=str(e))
                raise
        
        logger.info(
            "Embeddings complete",
            total=len(all_embeddings),
            dimensions=self.settings.embedding_dimensions
        )
        
        return all_embeddings
    
    async def embed_chunks(
        self,
        chunks: List[ChunkData]
    ) -> List[List[float]]:
        """
        Generate embeddings for document chunks.
        Combines chunk content with image summaries for visual chunks.
        
        Args:
            chunks: List of ChunkData objects
            
        Returns:
            List of embedding vectors (one per chunk)
        """
        # Prepare texts for embedding
        texts = []
        for chunk in chunks:
            # Use the chunking service to prepare embedding text
            text = self.chunking_service.get_chunk_for_embedding(chunk)
            texts.append(text)
        
        return await self.embed_texts(texts)
    
    async def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a search query.
        
        Args:
            query: User's search query
            
        Returns:
            Query embedding vector
        """
        return await self.embed_text(query)


# Singleton instance
_embedding_service = None


def get_embedding_service() -> EmbeddingService:
    """Get singleton embedding service instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
