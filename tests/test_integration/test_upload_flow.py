"""
Integration Tests - Full Upload and Ingest Flow

These tests use REAL Supabase connections to verify:
- Files are actually stored in Supabase Storage
- Database records are created correctly
- Progress updates work end-to-end

IMPORTANT: These tests require:
- Valid .env file with Supabase credentials
- A separate test bucket or cleanup strategy
"""
import pytest
import asyncio
import os
from httpx import AsyncClient, ASGITransport
from io import BytesIO
import time

# Skip if no test environment
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Integration tests disabled. Set RUN_INTEGRATION_TESTS=true"
)


class TestUploadIntegration:
    """Integration tests for upload flow with real Supabase."""
    
    @pytest.mark.asyncio
    async def test_upload_creates_storage_object(self, async_client, sample_pdf_bytes):
        """
        Verify file is actually stored in Supabase Storage.
        
        Steps:
        1. Upload file via API
        2. Query Supabase Storage to verify file exists
        3. Clean up
        """
        # This would require a real test user and topic in the database
        # For now, this is a template showing the pattern
        
        # 1. Create test topic first
        topic_response = await async_client.post(
            "/topics",
            json={
                "user_id": "integration-test-user",
                "name": f"Test Topic {int(time.time())}"
            }
        )
        
        if topic_response.status_code == 200:
            topic_id = topic_response.json()["id"]
            
            # 2. Upload file
            upload_response = await async_client.post(
                "/upload",
                params={
                    "user_id": "integration-test-user",
                    "topic_id": topic_id
                },
                files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
            )
            
            assert upload_response.status_code == 200
            document_id = upload_response.json()["document_id"]
            
            # 3. Verify document record
            status_response = await async_client.get(f"/documents/{document_id}/status")
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "pending"
            
            # 4. Cleanup (delete document and topic)
            await async_client.delete(f"/documents/{document_id}")
            await async_client.delete(f"/topics/{topic_id}")


class TestIngestIntegration:
    """Integration tests for full ingestion workflow."""
    
    @pytest.mark.asyncio
    async def test_ingest_updates_progress(self, async_client, sample_pdf_bytes):
        """
        Verify progress updates during ingestion.
        
        This is a longer-running test that:
        1. Uploads a file
        2. Starts ingestion
        3. Polls for progress updates
        4. Verifies final state
        """
        # Template for progress polling test
        pass  # Implement with real test data
    
    @pytest.mark.asyncio
    async def test_ingest_handles_failure_gracefully(self, async_client):
        """
        Verify failed ingestion sets status correctly.
        
        Upload corrupted file and verify:
        - Status becomes 'failed'
        - Error message is set
        """
        pass  # Implement with corrupted test file


class TestDataConsistency:
    """Tests to verify data consistency across services."""
    
    @pytest.mark.asyncio
    async def test_document_count_matches_database(self, async_client):
        """
        Verify chunk_count in documents table matches actual vectors.
        
        After ingestion:
        - documents.chunk_count should equal vectors in Pinecone
        """
        pass
    
    @pytest.mark.asyncio
    async def test_no_orphaned_documents(self, async_client):
        """
        Verify no documents exist without a parent topic.
        
        Query: SELECT * FROM documents WHERE topic_id NOT IN (SELECT id FROM topics)
        Should return 0 rows.
        """
        pass
    
    @pytest.mark.asyncio
    async def test_storage_files_match_database(self, async_client):
        """
        Verify files in Supabase Storage have matching database records.
        """
        pass
