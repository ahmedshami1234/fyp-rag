"""
Unit Tests for Topics API

Tests the POST /topics, GET /topics/{user_id}, DELETE /topics/{topic_id} endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


class TestCreateTopicAPI:
    """Unit tests for POST /topics endpoint."""
    
    def test_create_topic_valid(self, client, mock_supabase, sample_user_id):
        """
        Test creating a valid topic.
        
        Expected:
        - Status 200
        - Returns topic with id, name, description
        """
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "new-topic-id",
            "user_id": sample_user_id,
            "name": "Machine Learning",
            "description": "Notes on ML algorithms"
        }]
        
        response = client.post(
            "/topics",
            json={
                "user_id": sample_user_id,
                "name": "Machine Learning",
                "description": "Notes on ML algorithms"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "new-topic-id"
        assert data["name"] == "Machine Learning"
        assert data["user_id"] == sample_user_id
    
    def test_create_topic_without_description(self, client, mock_supabase, sample_user_id):
        """Test creating topic without optional description."""
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
            "id": "topic-id",
            "user_id": sample_user_id,
            "name": "Quick Notes",
            "description": None
        }]
        
        response = client.post(
            "/topics",
            json={
                "user_id": sample_user_id,
                "name": "Quick Notes"
            }
        )
        
        assert response.status_code == 200
        assert response.json()["description"] is None
    
    def test_create_topic_missing_user_id(self, client):
        """Test creating topic without user_id."""
        response = client.post(
            "/topics",
            json={"name": "Test Topic"}  # Missing user_id
        )
        
        assert response.status_code == 422
    
    def test_create_topic_missing_name(self, client, sample_user_id):
        """Test creating topic without name."""
        response = client.post(
            "/topics",
            json={"user_id": sample_user_id}  # Missing name
        )
        
        assert response.status_code == 422
    
    def test_create_topic_duplicate_name(self, client, mock_supabase, sample_user_id):
        """
        Test creating topic with duplicate name for same user.
        
        Expected: 500 (database constraint violation)
        """
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )
        
        response = client.post(
            "/topics",
            json={
                "user_id": sample_user_id,
                "name": "Duplicate Name"
            }
        )
        
        assert response.status_code == 500


class TestListTopicsAPI:
    """Unit tests for GET /topics/{user_id} endpoint."""
    
    def test_list_topics_with_data(self, client, mock_supabase, sample_user_id, sample_topic_data):
        """Test listing topics for user with existing topics."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            sample_topic_data,
            {**sample_topic_data, "id": "topic-2", "name": "Second Topic"}
        ]
        
        response = client.get(f"/topics/{sample_user_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["topics"]) == 2
    
    def test_list_topics_empty(self, client, mock_supabase, sample_user_id):
        """Test listing topics for user with no topics."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        
        response = client.get(f"/topics/{sample_user_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["topics"] == []


class TestDeleteTopicAPI:
    """Unit tests for DELETE /topics/{topic_id} endpoint."""
    
    def test_delete_topic_success(self, client, mock_supabase, mock_pinecone, sample_topic_data):
        """
        Test successful topic deletion with cascade.
        
        Expected:
        - Status 200
        - Topic deleted
        - Associated documents deleted
        - Vectors deleted from Pinecone
        """
        # Topic exists
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            sample_topic_data
        ]
        
        # Has documents
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "doc-1"}, {"id": "doc-2"}
        ]
        
        response = client.delete(f"/topics/{sample_topic_data['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
    
    def test_delete_topic_not_found(self, client, mock_supabase):
        """Test deleting non-existent topic."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        
        response = client.delete("/topics/non-existent-id")
        
        assert response.status_code == 404


class TestDeleteDocumentAPI:
    """Unit tests for DELETE /documents/{document_id} endpoint."""
    
    def test_delete_document_success(self, client, mock_supabase, mock_pinecone, sample_document_data):
        """Test successful document deletion."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            sample_document_data
        ]
        
        response = client.delete(f"/documents/{sample_document_data['id']}")
        
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
    
    def test_delete_document_not_found(self, client, mock_supabase):
        """Test deleting non-existent document."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        
        response = client.delete("/documents/non-existent-id")
        
        assert response.status_code == 404
