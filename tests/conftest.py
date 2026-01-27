"""
Shared Test Fixtures for RAG Pipeline Tests

This file contains:
- FastAPI TestClient setup
- Mock fixtures for external services
- Test data generators
- Database cleanup utilities
"""
import pytest
import asyncio
from typing import Generator, AsyncGenerator
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
import os
import sys

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app


# ═══════════════════════════════════════════════════════════════
# EVENT LOOP FIXTURE (for async tests)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ═══════════════════════════════════════════════════════════════
# FASTAPI CLIENT FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Synchronous FastAPI test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous FastAPI test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════
# MOCK FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for unit tests."""
    with patch("app.main.supabase") as mock:
        # Mock table operations
        mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock.table.return_value.insert.return_value.execute.return_value.data = [{"id": "test-uuid"}]
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
        mock.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = []
        
        # Mock storage operations
        mock.storage.from_.return_value.upload.return_value = {"path": "test/path"}
        mock.storage.from_.return_value.create_signed_url.return_value = {"signedURL": "https://test.url"}
        
        yield mock


@pytest.fixture
def mock_openai():
    """Mock OpenAI client for embedding and vision tests."""
    with patch("app.services.embedding_service.AsyncOpenAI") as embed_mock, \
         patch("app.services.vision_service.AsyncOpenAI") as vision_mock:
        
        # Mock embedding response
        embed_mock.return_value.embeddings.create = AsyncMock(
            return_value=Mock(data=[Mock(embedding=[0.1] * 3072)])
        )
        
        # Mock vision response
        vision_mock.return_value.chat.completions.create = AsyncMock(
            return_value=Mock(choices=[Mock(message=Mock(content="Test image description"))])
        )
        
        yield {"embedding": embed_mock, "vision": vision_mock}


@pytest.fixture
def mock_pinecone():
    """Mock Pinecone client for vector store tests."""
    with patch("app.services.vector_store.Pinecone") as mock:
        mock.return_value.Index.return_value.upsert.return_value = {"upserted_count": 10}
        mock.return_value.Index.return_value.delete.return_value = {}
        mock.return_value.Index.return_value.query.return_value = Mock(matches=[])
        yield mock


# ═══════════════════════════════════════════════════════════════
# TEST DATA FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def sample_user_id() -> str:
    """Test user ID."""
    return "test-user-12345"


@pytest.fixture
def sample_topic_id() -> str:
    """Test topic ID."""
    return "test-topic-67890"


@pytest.fixture
def sample_document_id() -> str:
    """Test document ID."""
    return "test-document-abcdef"


@pytest.fixture
def sample_document_data(sample_user_id, sample_topic_id, sample_document_id) -> dict:
    """Sample document record as returned from database."""
    return {
        "id": sample_document_id,
        "user_id": sample_user_id,
        "topic_id": sample_topic_id,
        "file_name": "test_document.pdf",
        "file_path": f"{sample_user_id}/{sample_topic_id}/test.pdf",
        "file_type": "pdf",
        "status": "pending",
        "chunk_count": 0,
        "processing_stage": None,
        "progress_percent": 0,
        "stage_details": None,
        "created_at": "2026-01-28T00:00:00Z"
    }


@pytest.fixture
def sample_topic_data(sample_user_id, sample_topic_id) -> dict:
    """Sample topic record."""
    return {
        "id": sample_topic_id,
        "user_id": sample_user_id,
        "name": "Test Topic",
        "description": "A test topic for unit tests",
        "created_at": "2026-01-28T00:00:00Z"
    }


# ═══════════════════════════════════════════════════════════════
# FILE FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid PDF bytes for testing."""
    # Minimal valid PDF structure
    return b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer << /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""


@pytest.fixture
def corrupted_pdf_bytes() -> bytes:
    """Invalid/corrupted PDF bytes."""
    return b"This is not a valid PDF file content"


# ═══════════════════════════════════════════════════════════════
# CLEANUP UTILITIES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def cleanup_test_data(sample_user_id):
    """
    Cleanup fixture that removes test data after tests.
    Use this for integration tests with real Supabase.
    """
    created_ids = {"topics": [], "documents": []}
    
    yield created_ids
    
    # Cleanup after test (would need real supabase client)
    # This is a placeholder - implement actual cleanup for integration tests
    print(f"Cleanup: Would delete {len(created_ids['topics'])} topics and {len(created_ids['documents'])} documents")
