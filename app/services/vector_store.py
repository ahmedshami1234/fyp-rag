"""
Vector Store Service
Manages vector storage in Pinecone with user namespaces and topic filtering.
"""
from typing import List, Optional, Dict, Any
import structlog
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models.schemas import ChunkData, ChunkResult

logger = structlog.get_logger()


class VectorStore:
    """Manages Pinecone vector storage with user isolation and topic filtering."""
    
    def __init__(self):
        self.settings = get_settings()
        self.pc = Pinecone(api_key=self.settings.pinecone_api_key)
        self.index = self.pc.Index(self.settings.pinecone_index)
        
        logger.info(
            "Vector store initialized",
            index=self.settings.pinecone_index
        )
    
    def _get_namespace(self, user_id: str) -> str:
        """Generate namespace for a user."""
        return f"user_{user_id}"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def upsert_vectors(
        self,
        chunks: List[ChunkData],
        embeddings: List[List[float]],
        user_id: str,
        topic_id: str,
        topic_name: str,
        document_id: str,
        file_name: str,
        file_url: str
    ) -> int:
        """
        Store chunk vectors in Pinecone with metadata.
        
        Args:
            chunks: List of ChunkData objects
            embeddings: Corresponding embedding vectors
            user_id: User's Supabase UUID
            topic_id: Topic UUID
            topic_name: Topic name for reference
            document_id: Document UUID
            file_name: Original filename
            file_url: Supabase Storage URL
            
        Returns:
            Number of vectors upserted
        """
        namespace = self._get_namespace(user_id)
        
        logger.info(
            "Upserting vectors",
            namespace=namespace,
            count=len(chunks),
            topic=topic_name
        )
        
        # Prepare vectors for upsert
        vectors = []
        for chunk, embedding in zip(chunks, embeddings):
            # Limit full_content to prevent metadata size issues (Pinecone 40KB limit)
            full_content = chunk.content
            if len(full_content) > 8000:
                full_content = full_content[:8000] + "..."
            
            metadata = {
                "user_id": user_id,
                "topic_id": topic_id,
                "topic_name": topic_name,
                "document_id": document_id,
                "file_name": file_name,
                "file_url": file_url,
                "section_title": chunk.section_title or "",
                "chunk_index": chunk.chunk_index,
                "chunk_type": chunk.chunk_type,  # "text" or "image"
                "has_image": chunk.has_image,
                "content_preview": chunk.content[:500],
                "full_content": full_content,
            }
            
            # Add image_b64 for image chunks (if small enough)
            # Pinecone has 40KB metadata limit, so we limit b64 to ~30KB
            if chunk.chunk_type == "image" and chunk.image_b64:
                if len(chunk.image_b64) < 30000:
                    metadata["image_b64"] = chunk.image_b64
                else:
                    logger.warning(f"Skipping image_b64 (too large: {len(chunk.image_b64)} bytes)")
                    metadata["image_too_large"] = True
            
            vector = {
                "id": chunk.id,
                "values": embedding,
                "metadata": metadata
            }
            vectors.append(vector)
        
        # Upsert in batches of 100
        batch_size = 100
        total_upserted = 0
        
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch, namespace=namespace)
            total_upserted += len(batch)
            
            logger.info(
                "Batch upserted",
                batch_num=i // batch_size + 1,
                count=len(batch)
            )
        
        logger.info(
            "Vectors upserted successfully",
            total=total_upserted,
            namespace=namespace
        )
        
        return total_upserted
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def query(
        self,
        query_embedding: List[float],
        user_id: str,
        topic_id: str,
        top_k: int = 5
    ) -> List[ChunkResult]:
        """
        Query vectors with topic filtering.
        
        Args:
            query_embedding: Query vector
            user_id: User's Supabase UUID
            topic_id: Topic UUID to filter by
            top_k: Number of results to return
            
        Returns:
            List of ChunkResult objects
        """
        namespace = self._get_namespace(user_id)
        
        logger.info(
            "Querying vectors",
            namespace=namespace,
            topic_id=topic_id,
            top_k=top_k
        )
        
        results = self.index.query(
            namespace=namespace,
            vector=query_embedding,
            filter={"topic_id": {"$eq": topic_id}},
            top_k=top_k,
            include_metadata=True
        )
        
        chunk_results = []
        for match in results.matches:
            metadata = match.metadata or {}
            chunk_results.append(ChunkResult(
                content=metadata.get("full_content", metadata.get("content_preview", "")),
                score=match.score,
                document_id=metadata.get("document_id", ""),
                file_name=metadata.get("file_name", ""),
                section_title=metadata.get("section_title"),
                chunk_index=metadata.get("chunk_index", 0),
                has_image=metadata.get("has_image", False)
            ))
        
        logger.info("Query complete", results=len(chunk_results))
        return chunk_results
    
    async def delete_document_vectors(
        self,
        user_id: str,
        document_id: str
    ) -> bool:
        """
        Delete all vectors for a specific document.
        
        Args:
            user_id: User's Supabase UUID
            document_id: Document UUID to delete
            
        Returns:
            True if successful
        """
        namespace = self._get_namespace(user_id)
        
        logger.info(
            "Deleting document vectors",
            namespace=namespace,
            document_id=document_id
        )
        
        # Delete by metadata filter
        self.index.delete(
            namespace=namespace,
            filter={"document_id": {"$eq": document_id}}
        )
        
        logger.info("Document vectors deleted")
        return True
    
    async def delete_topic_vectors(
        self,
        user_id: str,
        topic_id: str
    ) -> bool:
        """
        Delete all vectors for a specific topic.
        
        Args:
            user_id: User's Supabase UUID
            topic_id: Topic UUID to delete
            
        Returns:
            True if successful
        """
        namespace = self._get_namespace(user_id)
        
        logger.info(
            "Deleting topic vectors",
            namespace=namespace,
            topic_id=topic_id
        )
        
        self.index.delete(
            namespace=namespace,
            filter={"topic_id": {"$eq": topic_id}}
        )
        
        logger.info("Topic vectors deleted")
        return True
    
    async def delete_user_namespace(self, user_id: str) -> bool:
        """
        Delete entire namespace for a user (GDPR deletion).
        
        Args:
            user_id: User's Supabase UUID
            
        Returns:
            True if successful
        """
        namespace = self._get_namespace(user_id)
        
        logger.info("Deleting user namespace", namespace=namespace)
        
        self.index.delete(namespace=namespace, delete_all=True)
        
        logger.info("User namespace deleted")
        return True
    
    # Alias methods for cleaner API
    async def delete_by_document(self, user_id: str, document_id: str) -> bool:
        """Alias for delete_document_vectors."""
        return await self.delete_document_vectors(user_id, document_id)
    
    async def delete_by_topic(self, user_id: str, topic_id: str) -> bool:
        """Alias for delete_topic_vectors."""
        return await self.delete_topic_vectors(user_id, topic_id)
    
    async def get_stats(self, user_id: str) -> Dict[str, Any]:
        """
        Get vector stats for a user's namespace.
        
        Args:
            user_id: User's Supabase UUID
            
        Returns:
            Stats dictionary
        """
        namespace = self._get_namespace(user_id)
        stats = self.index.describe_index_stats()
        
        namespace_stats = stats.namespaces.get(namespace, {})
        return {
            "namespace": namespace,
            "vector_count": namespace_stats.get("vector_count", 0),
            "dimension": stats.dimension
        }


# Singleton instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get singleton vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
