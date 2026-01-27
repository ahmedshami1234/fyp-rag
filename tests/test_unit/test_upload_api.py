"""
Unit Tests for Upload API

Tests the POST /upload endpoint with mocked Supabase.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from io import BytesIO


class TestUploadAPI:
    """Unit tests for /upload endpoint."""
    
    # ═══════════════════════════════════════════════════════════════
    # VALID REQUEST TESTS
    # ═══════════════════════════════════════════════════════════════
    
    def test_upload_valid_pdf(self, client, mock_supabase, sample_user_id, sample_topic_id, sample_pdf_bytes):
        """
        Test successful PDF upload.
        
        Expected:
        - Status 200
        - Returns document_id
        - File stored in Supabase
        - Document record created
        """
        # Arrange
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "new-doc-id",
            "user_id": sample_user_id,
            "topic_id": sample_topic_id,
            "file_name": "test.pdf",
            "file_path": f"{sample_user_id}/{sample_topic_id}/test.pdf",
            "file_type": "pdf",
            "status": "pending"
        }]
        
        # Act
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id, "topic_id": sample_topic_id},
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
        )
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["status"] == "pending"
        assert data["message"] == "File uploaded. Use /ingest to process."
        
        # Verify Supabase was called
        mock_supabase.storage.from_.assert_called()
        mock_supabase.table.assert_called_with("documents")
    
    def test_upload_docx_file(self, client, mock_supabase, sample_user_id, sample_topic_id):
        """Test uploading a DOCX file."""
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "docx-doc-id",
            "file_type": "docx",
            "status": "pending"
        }]
        
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id, "topic_id": sample_topic_id},
            files={"file": ("document.docx", BytesIO(b"fake docx content"), "application/vnd.openxmlformats")}
        )
        
        assert response.status_code == 200
        assert response.json()["document_id"] == "docx-doc-id"
    
    # ═══════════════════════════════════════════════════════════════
    # INVALID REQUEST TESTS
    # ═══════════════════════════════════════════════════════════════
    
    def test_upload_missing_file(self, client, sample_user_id, sample_topic_id):
        """
        Test upload without file.
        
        Expected: 422 Unprocessable Entity
        """
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id, "topic_id": sample_topic_id}
            # No file attached
        )
        
        assert response.status_code == 422  # FastAPI validation error
    
    def test_upload_missing_user_id(self, client, sample_topic_id, sample_pdf_bytes):
        """
        Test upload without user_id.
        
        Expected: 422 Unprocessable Entity
        """
        response = client.post(
            "/upload",
            params={"topic_id": sample_topic_id},  # Missing user_id
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
        )
        
        assert response.status_code == 422
    
    def test_upload_missing_topic_id(self, client, sample_user_id, sample_pdf_bytes):
        """
        Test upload without topic_id.
        
        Expected: 422 Unprocessable Entity
        """
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id},  # Missing topic_id
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
        )
        
        assert response.status_code == 422
    
    # ═══════════════════════════════════════════════════════════════
    # ERROR HANDLING TESTS
    # ═══════════════════════════════════════════════════════════════
    
    def test_upload_storage_failure(self, client, mock_supabase, sample_user_id, sample_topic_id, sample_pdf_bytes):
        """
        Test handling of Supabase storage failure.
        
        Expected: 500 Internal Server Error
        """
        # Simulate storage failure
        mock_supabase.storage.from_.return_value.upload.side_effect = Exception("Storage unavailable")
        
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id, "topic_id": sample_topic_id},
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
        )
        
        assert response.status_code == 500
        assert "Upload failed" in response.json()["detail"]
    
    def test_upload_database_failure(self, client, mock_supabase, sample_user_id, sample_topic_id, sample_pdf_bytes):
        """
        Test handling of database insert failure.
        
        Expected: 500 Internal Server Error
        """
        # Storage succeeds, but database fails
        mock_supabase.storage.from_.return_value.upload.return_value = {"path": "test/path"}
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = Exception("Database error")
        
        response = client.post(
            "/upload",
            params={"user_id": sample_user_id, "topic_id": sample_topic_id},
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")}
        )
        
        assert response.status_code == 500
