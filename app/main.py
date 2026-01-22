"""
Simplified FastAPI Application
Only 2 core APIs: Upload and Ingest
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import structlog
import uuid
import os
import tempfile

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
        structlog.dev.ConsoleRenderer()  # Human-readable format in terminal
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
    title="Document Ingestion Pipeline",
    description="Simplified API: Upload + Ingest",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    document_id: str     # ID of the created document record
    file_path: str       # Storage path
    file_name: str       # Original filename
    user_id: str         # User who uploaded
    topic_id: str        # Topic it belongs to
    status: str          # Document status (pending)
    message: str


class IngestRequest(BaseModel):
    document_id: str     # Document ID from /upload API
    # user_id and topic_id are already stored in the document record


class IngestResponse(BaseModel):
    status: str          # "Done" or "Failed"
    document_id: str
    chunk_count: int
    message: str


class BatchIngestRequest(BaseModel):
    document_ids: List[str]  # Multiple document IDs from /upload


class BatchIngestResponse(BaseModel):
    status: str           # "Done" if ALL succeeded
    results: List[dict]   # Individual file results
    total_chunks: int


# ─────────────────────────────────────────────────────────────
# API 1: Upload File
# ─────────────────────────────────────────────────────────────

@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    user_id: str,
    topic_id: str,
    file: UploadFile = File(...)
):
    """
    Upload a file to Supabase Storage and create document record.
    """
    try:
        logger.info(f"Uploading file '{file.filename}' to Supabase Storage...")
        
        # Generate unique file path with user folder structure
        file_ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{file_ext}"
        storage_path = f"{user_id}/{topic_id}/{unique_name}"
        
        # Read file content
        content = await file.read()
        
        # Detect file type from extension
        file_type = file_ext.lstrip('.').lower() if file_ext else "unknown"
        
        # Upload to Supabase Storage
        supabase.storage.from_(settings.supabase_storage_bucket).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": file.content_type}
        )
        
        logger.info("File saved successfully in Supabase Storage")
        
        # Create document record in database
        doc_result = supabase.table("documents").insert({
            "user_id": user_id,
            "topic_id": topic_id,
            "file_name": file.filename,
            "file_path": storage_path,
            "file_type": file_type,
            "status": "pending"
        }).execute()
        
        document = doc_result.data[0]
        logger.info(f"Document record created: {document['id']}")
        
        return UploadResponse(
            document_id=document["id"],
            file_path=storage_path,
            file_name=file.filename,
            user_id=user_id,
            topic_id=topic_id,
            status="pending",
            message="File uploaded successfully. Use /ingest to process."
        )
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ─────────────────────────────────────────────────────────────
# API 2: Ingest File (Single)
# ─────────────────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse)
async def ingest_file(request: IngestRequest):
    """
    Ingest a single file into the vector database.
    """
    document_id = request.document_id
    
    try:
        # Get document info
        doc_result = supabase.table("documents").select("*").eq("id", document_id).execute()
        if not doc_result.data:
            raise HTTPException(status_code=404, detail="Document not found")
        
        document = doc_result.data[0]
        user_id = document["user_id"]
        topic_id = document["topic_id"]
        file_path = document["file_path"]
        file_name = document["file_name"]
        
        logger.info(f"Stage: Starting ingestion for '{file_name}' (ID: {document_id})")
        
        # Update status to processing
        supabase.table("documents").update({
            "status": "processing"
        }).eq("id", document_id).execute()
        
        # Get topic name
        topic_result = supabase.table("topics").select("name").eq("id", topic_id).execute()
        topic_name = topic_result.data[0]["name"] if topic_result.data else "Unknown"
        
        # Get file URL from Supabase Storage (signed URL for private bucket)
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
        
        logger.info(f"Stage: Ingestion complete! Total chunks stored: {chunk_count}")
        
        return IngestResponse(
            status="Done",
            document_id=document_id,
            chunk_count=chunk_count,
            message=f"Successfully ingested {chunk_count} chunks"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stage: Ingestion failed - {str(e)}")
        
        # Update document status to failed
        supabase.table("documents").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", document_id).execute()
        
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


# ─────────────────────────────────────────────────────────────
# API 2b: Batch Ingest (Multiple Files)
# ─────────────────────────────────────────────────────────────

@app.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(request: BatchIngestRequest):
    """
    Ingest multiple files at once.
    """
    logger.info(f"Stage: Starting batch ingestion for {len(request.document_ids)} files")
    results = []
    total_chunks = 0
    all_success = True
    
    for document_id in request.document_ids:
        try:
            single_request = IngestRequest(document_id=document_id)
            result = await ingest_file(single_request)
            results.append({
                "document_id": document_id,
                "status": "Done",
                "chunk_count": result.chunk_count
            })
            total_chunks += result.chunk_count
            
        except Exception as e:
            all_success = False
            results.append({
                "document_id": document_id,
                "status": "Failed",
                "error": str(e)
            })
    
    status_msg = "Done" if all_success else "Partial"
    logger.info(f"Stage: Batch ingestion finished with status '{status_msg}'")
    
    return BatchIngestResponse(
        status=status_msg,
        results=results,
        total_chunks=total_chunks
    )


# ─────────────────────────────────────────────────────────────
# Pipeline Function
# ─────────────────────────────────────────────────────────────

async def run_pipeline(
    user_id: str,
    topic_id: str,
    topic_name: str,
    document_id: str,
    file_url: str,
    file_name: str
) -> int:
    """
    Execute the ingestion pipeline with detailed stage logging.
    """
    file_handler = get_file_handler()
    document_parser = get_document_parser()
    chunking_service = get_chunking_service()
    vision_service = get_vision_service()
    embedding_service = get_embedding_service()
    vector_store = get_vector_store()
    
    local_path = None
    
    try:
        # Step 1: Download file
        logger.info("Stage: Downloading file from Storage...")
        local_path = await file_handler.download_file(file_url, file_name)
        
        # Step 2: Detect file type
        _, file_type = file_handler.detect_file_type(local_path)
        
        # Step 3: Parse document
        logger.info(f"Stage: Parsing document (using Unstructured.io) - Type: {file_type}")
        elements = await document_parser.parse(local_path, file_type)
        
        # Step 4: Chunk by title
        logger.info("Stage: Chunking document into semantic sections...")
        chunks = await chunking_service.chunk_elements(elements)
        
        if not chunks:
            raise ValueError("No chunks extracted from document")
        
        # Step 5: Process visual content
        visual_chunks = [c for c in chunks if c.has_image]
        if visual_chunks:
            logger.info(f"Stage: Processing {len(visual_chunks)} visual elements using GPT-4o Vision...")
            chunks = await vision_service.process_visual_chunks(chunks)
        
        # Step 6: Generate embeddings
        logger.info(f"Stage: Generating vector embeddings for {len(chunks)} chunks...")
        embeddings = await embedding_service.embed_chunks(chunks)
        
        # Step 7: Store in Pinecone
        logger.info("Stage: Storing vectors in Vector Database (Pinecone)...")
        await vector_store.upsert_vectors(
            chunks=chunks,
            embeddings=embeddings,
            user_id=user_id,
            topic_id=topic_id,
            topic_name=topic_name,
            document_id=document_id,
            file_name=file_name,
            file_url=file_url
        )
        
        return len(chunks)
        
    finally:
        # Cleanup
        if local_path:
            file_handler.cleanup(local_path)


# ─────────────────────────────────────────────────────────────
# Helper Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/topics")
async def create_topic(user_id: str, name: str, description: str = None):
    """Create a new topic."""
    try:
        result = supabase.table("topics").insert({
            "user_id": user_id,
            "name": name,
            "description": description
        }).execute()
        return {"topic_id": result.data[0]["id"], "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/topics/{user_id}")
async def list_topics(user_id: str):
    """List all topics for a user."""
    result = supabase.table("topics").select("*").eq("user_id", user_id).execute()
    return {"topics": result.data}


@app.get("/documents/{topic_id}")
async def list_documents(topic_id: str):
    """List all documents in a topic."""
    result = supabase.table("documents").select("*").eq("topic_id", topic_id).execute()
    return {"documents": result.data}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
