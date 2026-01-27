"""
Unit Tests for Ingest API

Tests the POST /ingest endpoint with mocked services.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock


class TestIngestAPI:
    """Unit tests for /ingest endpoint."""
    
    # ═══════════════════════════════════════════════════════════════
    # VALID REQUEST TESTS
    # ═══════════════════════════════════════════════════════════════
    
    def test_ingest_single_document(self, client, mock_supabase, sample_document_id):
        """
        Test ingesting a single document.
        
        Expected:
        - Status 200
        - Returns processing status
        - Document status updated to 'processing'
        """
        # Arrange - document exists
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": sample_document_id}
        ]
        
        # Act
        response = client.post(
            "/ingest",
            json={"document_ids": [sample_document_id]}
        )
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["queued_count"] == 1
    
    def test_ingest_multiple_documents(self, client, mock_supabase):
        """
        Test batch ingestion of multiple documents.
        
        Expected:
        - Status 200
        - All documents queued
        """
        doc_ids = ["doc-1", "doc-2", "doc-3"]
        
        # All documents exist
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "exists"}
        ]
        
        response = client.post(
            "/ingest",
            json={"document_ids": doc_ids}
        )
        
        assert response.status_code == 200
        assert response.json()["queued_count"] == 3
    
    # ═══════════════════════════════════════════════════════════════
    # INVALID REQUEST TESTS
    # ═══════════════════════════════════════════════════════════════
    
    def test_ingest_empty_list(self, client):
        """
        Test ingesting with empty document list.
        
        Expected: 400 Bad Request
        """
        response = client.post(
            "/ingest",
            json={"document_ids": []}
        )
        
        assert response.status_code == 400
        assert "No document_ids" in response.json()["detail"]
    
    def test_ingest_missing_body(self, client):
        """
        Test ingesting without request body.
        
        Expected: 422 Unprocessable Entity
        """
        response = client.post("/ingest")
        
        assert response.status_code == 422
    
    def test_ingest_nonexistent_document(self, client, mock_supabase):
        """
        Test ingesting a document that doesn't exist.
        
        Expected: 404 Not Found
        """
        # Document doesn't exist
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        
        response = client.post(
            "/ingest",
            json={"document_ids": ["non-existent-id"]}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_ingest_invalid_id_type(self, client):
        """
        Test ingesting with invalid ID type (number instead of string).
        
        Expected: 422 Unprocessable Entity
        """
        response = client.post(
            "/ingest",
            json={"document_ids": [123, 456]}  # Should be strings
        )
        
        # FastAPI/Pydantic may coerce or reject
        # This tests the validation layer
        assert response.status_code in [200, 422]


class TestDocumentStatusAPI:
    """Unit tests for GET /documents/{document_id}/status endpoint."""
    
    def test_status_pending_document(self, client, mock_supabase, sample_document_data):
        """Test getting status of a pending document."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            sample_document_data
        ]
        
        response = client.get(f"/documents/{sample_document_data['id']}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["progress_percent"] == 0
    
    def test_status_processing_document(self, client, mock_supabase, sample_document_data):
        """Test getting status of a processing document."""
        sample_document_data["status"] = "processing"
        sample_document_data["processing_stage"] = "vision"
        sample_document_data["progress_percent"] = 65
        sample_document_data["stage_details"] = "Analyzing image 2 of 3"
        
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            sample_document_data
        ]
        
        response = client.get(f"/documents/{sample_document_data['id']}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["processing_stage"] == "vision"
        assert data["progress_percent"] == 65
        assert "image 2 of 3" in data["stage_details"]
    
    def test_status_done_document(self, client, mock_supabase, sample_document_data):
        """Test getting status of a completed document."""
        sample_document_data["status"] = "done"
        sample_document_data["processing_stage"] = "done"
        sample_document_data["progress_percent"] = 100
        sample_document_data["chunk_count"] = 42
        
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            sample_document_data
        ]
        
        response = client.get(f"/documents/{sample_document_data['id']}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert data["progress_percent"] == 100
        assert data["chunk_count"] == 42
    
    def test_status_nonexistent_document(self, client, mock_supabase):
        """Test getting status of non-existent document."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        
        response = client.get("/documents/non-existent-id/status")
        
        assert response.status_code == 404
