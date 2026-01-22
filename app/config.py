"""
Application Configuration
Loads environment variables and provides typed configuration.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # OpenAI
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    
    # Pinecone
    pinecone_api_key: str = Field(..., env="PINECONE_API_KEY")
    pinecone_index: str = Field(default="rag-fyp", env="PINECONE_INDEX")
    
    # Supabase
    supabase_url: str = Field(..., env="SUPABASE_URL")
    supabase_service_key: str = Field(..., env="SUPABASE_SERVICE_KEY")
    supabase_storage_bucket: str = Field(default="documents", env="SUPABASE_STORAGE_BUCKET")
    
    # App Settings
    environment: str = Field(default="development", env="ENVIRONMENT")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    max_chunk_size: int = Field(default=1500, env="MAX_CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, env="CHUNK_OVERLAP")
    
    # Embedding Settings
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072
    
    # Vision Settings
    vision_model: str = "gpt-4o"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
