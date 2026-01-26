"""
RAG Ingestion Pipeline API
6 Clean Endpoints: Upload, Ingest, Topics CRUD, Documents CRUD
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import structlog
import uuid
import os
import asyncio

from app.config import get_settings
from app.services.file_handler import get_file_handler
from app.services.document_parser import get_document_parser
from app.services.chunking_service import get_chunking_service
from app.services.vision_service import get_vision_service
from app.services.embedding_service import get_embedding_service
from app.services.vector_store import get_vector_store

# Configure logging for terminal readability
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()
settings = get_settings()

# Initialize Supabase client
from supabase import create_client
supabase = create_client(settings.supabase_url, settings.supabase_service_key)

# Create FastAPI app
app = FastAPI(
    title="RAG Ingestion Pipeline",
    description="6 Clean APIs: Upload, Ingest, Topics CRUD, Documents CRUD",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════

class UploadResponse(BaseModel):
    document_id: str
    file_path: str
    file_name: str
    user_id: str
    topic_id: str
    status: str
    message: str


class IngestRequest(BaseModel):
    document_ids: List[str]  # Supports 1 or many


class IngestResponse(BaseModel):
    status: str              # "queued"
    queued_count: int
    message: str


class TopicCreate(BaseModel):
    user_id: str
    name: str
    description: Optional[str] = None


class TopicResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]


# ═══════════════════════════════════════════════════════════════
# API 1: UPLOAD FILE
# ═══════════════════════════════════════════════════════════════

@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    user_id: str,
    topic_id: str,
    file: UploadFile = File(...)
):
    """
    Upload a file to Supabase Storage and create a document record.
    
    Returns a document_id to use with /ingest.
    """
    try:
        logger.info(f"📤 Uploading: {file.filename}")
        
        # Generate unique storage path
        file_ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{file_ext}"
        storage_path = f"{user_id}/{topic_id}/{unique_name}"
        
        # Read and upload
        content = await file.read()
        file_type = file_ext.lstrip('.').lower() if file_ext else "unknown"
        
        supabase.storage.from_(settings.supabase_storage_bucket).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": file.content_type}
        )
        
        logger.info(f"✅ Stored in Supabase: {storage_path}")
        
        # Create document record
        doc_result = supabase.table("documents").insert({
            "user_id": user_id,
            "topic_id": topic_id,
            "file_name": file.filename,
            "file_path": storage_path,
            "file_type": file_type,
            "status": "pending"
        }).execute()
        
        document = doc_result.data[0]
        logger.info(f"📝 Document created: {document['id']}")
        
        return UploadResponse(
            document_id=document["id"],
            file_path=storage_path,
            file_name=file.filename,
            user_id=user_id,
            topic_id=topic_id,
            status="pending",
            message="File uploaded. Use /ingest to process."
        )
        
    except Exception as e:
        logger.error(f"❌ Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# API 2: INGEST (Unified Async - Single or Batch)
# ═══════════════════════════════════════════════════════════════

@app.post("/ingest", response_model=IngestResponse)
async def ingest_documents(request: IngestRequest, background_tasks: BackgroundTasks):
    """
    Queue document(s) for background ingestion.
    
    - Accepts 1 or many document_ids
    - Returns immediately with "queued" status
    - Processes files asynchronously in parallel
    - Check /documents/{topic_id} for status updates
    """
    document_ids = request.document_ids
    
    if not document_ids:
        raise HTTPException(status_code=400, detail="No document_ids provided")
    
    logger.info(f"📥 Queueing {len(document_ids)} document(s) for ingestion")
    
    # Verify all documents exist and update status
    for doc_id in document_ids:
        doc_result = supabase.table("documents").select("id").eq("id", doc_id).execute()
        if not doc_result.data:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
        
        # Update status to processing (background worker starts immediately)
        supabase.table("documents").update({
            "status": "processing"
        }).eq("id", doc_id).execute()
        
        # Schedule background worker for each document
        background_tasks.add_task(run_ingestion_worker, doc_id)
    
    return IngestResponse(
        status="processing",
        queued_count=len(document_ids),
        message=f"Processing {len(document_ids)} document(s). Check /documents/{{topic_id}} for status."
    )


async def run_ingestion_worker(document_id: str):
    """
    Background worker that processes a single document.
    Called by FastAPI BackgroundTasks for concurrent processing.
    """
    try:
        logger.info(f"🔄 Worker started: {document_id}")
        
        # Get document info
        doc_result = supabase.table("documents").select("*").eq("id", document_id).execute()
        if not doc_result.data:
            logger.error(f"Document not found: {document_id}")
            return
        
        document = doc_result.data[0]
        user_id = document["user_id"]
        topic_id = document["topic_id"]
        file_path = document["file_path"]
        file_name = document["file_name"]
        
        # Update status to processing
        supabase.table("documents").update({
            "status": "processing"
        }).eq("id", document_id).execute()
        
        # Get topic name
        topic_result = supabase.table("topics").select("name").eq("id", topic_id).execute()
        topic_name = topic_result.data[0]["name"] if topic_result.data else "Unknown"
        
        # Get signed URL
        signed_url_response = supabase.storage.from_(settings.supabase_storage_bucket).create_signed_url(
            path=file_path,
            expires_in=3600
        )
        file_url = signed_url_response.get("signedURL") or signed_url_response.get("signedUrl")
        if not file_url:
            raise ValueError(f"Failed to create signed URL: {signed_url_response}")
        
        # Run the pipeline
        chunk_count = await run_pipeline(
            user_id=user_id,
            topic_id=topic_id,
            topic_name=topic_name,
            document_id=document_id,
            file_url=file_url,
            file_name=file_name
        )
        
        # Update document status to done
        supabase.table("documents").update({
            "status": "done",
            "chunk_count": chunk_count
        }).eq("id", document_id).execute()
        
        logger.info(f"✅ Worker complete: {document_id} ({chunk_count} chunks)")
        
    except Exception as e:
        logger.error(f"❌ Worker failed: {document_id} - {str(e)}")
        
        supabase.table("documents").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", document_id).execute()


# ═══════════════════════════════════════════════════════════════
# API 3: CREATE TOPIC
# ═══════════════════════════════════════════════════════════════

@app.post("/topics", response_model=TopicResponse)
async def create_topic(request: TopicCreate):
    """
    Create a new topic for a user.
    """
    try:
        result = supabase.table("topics").insert({
            "user_id": request.user_id,
            "name": request.name,
            "description": request.description
        }).execute()
        
        topic = result.data[0]
        logger.info(f"📁 Topic created: {topic['name']} (ID: {topic['id']})")
        
        return TopicResponse(
            id=topic["id"],
            user_id=topic["user_id"],
            name=topic["name"],
            description=topic.get("description")
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to create topic: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# API 4: LIST TOPICS BY USER
# ═══════════════════════════════════════════════════════════════

@app.get("/topics/{user_id}")
async def list_topics(user_id: str):
    """
    List all topics for a user.
    """
    result = supabase.table("topics").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return {"topics": result.data, "count": len(result.data)}


# ═══════════════════════════════════════════════════════════════
# API 5: DELETE TOPIC (Cascade)
# ═══════════════════════════════════════════════════════════════

@app.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str):
    """
    Delete a topic and ALL associated data:
    - All documents in the topic
    - All vectors in Pinecone for those documents
    - The topic itself
    """
    try:
        # Get topic info
        topic_result = supabase.table("topics").select("*").eq("id", topic_id).execute()
        if not topic_result.data:
            raise HTTPException(status_code=404, detail="Topic not found")
        
        topic = topic_result.data[0]
        user_id = topic["user_id"]
        
        logger.info(f"🗑️ Deleting topic: {topic['name']} (ID: {topic_id})")
        
        # Get all documents in this topic
        docs_result = supabase.table("documents").select("id").eq("topic_id", topic_id).execute()
        document_ids = [doc["id"] for doc in docs_result.data]
        
        # Delete vectors from Pinecone for each document
        vector_store = get_vector_store()
        for doc_id in document_ids:
            await vector_store.delete_by_document(user_id=user_id, document_id=doc_id)
        
        # Delete all documents in this topic
        supabase.table("documents").delete().eq("topic_id", topic_id).execute()
        
        # Delete the topic
        supabase.table("topics").delete().eq("id", topic_id).execute()
        
        logger.info(f"✅ Deleted topic + {len(document_ids)} documents + vectors")
        
        return {
            "status": "deleted",
            "topic_id": topic_id,
            "documents_deleted": len(document_ids),
            "message": "Topic and all associated data deleted"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete topic: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# API 6: DELETE DOCUMENT
# ═══════════════════════════════════════════════════════════════

@app.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """
    Delete a single document and its vectors from Pinecone.
    """
    try:
        # Get document info
        doc_result = supabase.table("documents").select("*").eq("id", document_id).execute()
        if not doc_result.data:
            raise HTTPException(status_code=404, detail="Document not found")
        
        document = doc_result.data[0]
        user_id = document["user_id"]
        file_path = document["file_path"]
        
        logger.info(f"🗑️ Deleting document: {document['file_name']} (ID: {document_id})")
        
        # Delete vectors from Pinecone
        vector_store = get_vector_store()
        await vector_store.delete_by_document(user_id=user_id, document_id=document_id)
        
        # Delete file from Supabase Storage
        try:
            supabase.storage.from_(settings.supabase_storage_bucket).remove([file_path])
        except Exception as storage_error:
            logger.warning(f"Could not delete file from storage: {storage_error}")
        
        # Delete document record
        supabase.table("documents").delete().eq("id", document_id).execute()
        
        logger.info(f"✅ Deleted document + vectors")
        
        return {
            "status": "deleted",
            "document_id": document_id,
            "message": "Document and vectors deleted"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# HELPER: LIST DOCUMENTS BY TOPIC
# ═══════════════════════════════════════════════════════════════

@app.get("/documents/{topic_id}")
async def list_documents(topic_id: str):
    """
    List all documents in a topic with their processing status.
    """
    result = supabase.table("documents").select("*").eq("topic_id", topic_id).order("created_at", desc=True).execute()
    return {"documents": result.data, "count": len(result.data)}


# ═══════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# ═══════════════════════════════════════════════════════════════
# INGESTION PIPELINE
# ═══════════════════════════════════════════════════════════════

async def run_pipeline(
    user_id: str,
    topic_id: str,
    topic_name: str,
    document_id: str,
    file_url: str,
    file_name: str
) -> int:
    """
    Execute the RAG ingestion pipeline.
    
    Steps:
    1. Download file from storage
    2. Detect file type
    3. Parse document (Unstructured.io)
    4. Chunk by title (separate text and images)
    5. Process images with Vision LLM (GPT-4o)
    6. Generate embeddings for all chunks
    7. Store in Pinecone with image b64 in metadata
    """
    file_handler = get_file_handler()
    document_parser = get_document_parser()
    chunking_service = get_chunking_service()
    vision_service = get_vision_service()
    embedding_service = get_embedding_service()
    vector_store = get_vector_store()
    
    local_path = None
    
    try:
        # Step 1: Download
        logger.info("📥 Stage: Downloading file...")
        local_path = await file_handler.download_file(file_url, file_name)
        
        # Step 2: Detect type
        _, file_type = file_handler.detect_file_type(local_path)
        
        # Step 3: Parse
        logger.info(f"📄 Stage: Parsing document - Type: {file_type}")
        elements = await document_parser.parse(
            file_path=local_path,
            file_type=file_type,
            image_output_dir=file_handler._temp_dir
        )
        
        # Step 4: Chunk (returns separate text and image chunks)
        logger.info("✂️ Stage: Chunking into semantic sections...")
        text_chunks, image_chunks = await chunking_service.chunk_elements(elements)
        
        logger.info(f"   📝 Text chunks: {len(text_chunks)}")
        logger.info(f"   🖼️ Image chunks: {len(image_chunks)}")
        
        # Step 5: Process images with Vision LLM
        if image_chunks:
            logger.info(f"👁️ Stage: Processing {len(image_chunks)} images with GPT-4o Vision...")
            image_chunks = await vision_service.process_image_chunks(
                image_chunks=image_chunks,
                text_chunks=text_chunks,
                chunking_service=chunking_service
            )
        
        # Combine all chunks
        all_chunks = text_chunks + image_chunks
        
        if not all_chunks:
            raise ValueError("No chunks extracted from document")
        
        # Step 6: Generate embeddings
        logger.info(f"🔢 Stage: Generating embeddings for {len(all_chunks)} chunks...")
        embeddings = await embedding_service.embed_chunks(all_chunks)
        
        # Step 7: Store in Pinecone
        logger.info("💾 Stage: Storing vectors in Pinecone...")
        await vector_store.upsert_vectors(
            chunks=all_chunks,
            embeddings=embeddings,
            user_id=user_id,
            topic_id=topic_id,
            topic_name=topic_name,
            document_id=document_id,
            file_name=file_name,
            file_url=file_url
        )
        
        logger.info(f"🎉 Stage: Complete! {len(all_chunks)} chunks stored ({len(text_chunks)} text, {len(image_chunks)} images)")
        return len(all_chunks)
        
    finally:
        if local_path:
            file_handler.cleanup(local_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
