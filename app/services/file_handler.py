"""
File Handler Service
Downloads files from Supabase Storage and detects file types.
"""
import os
import tempfile
import httpx
import magic
from typing import Tuple, Optional
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = structlog.get_logger()


class FileHandler:
    """Handles file download and type detection."""
    
    # Supported file types and their MIME types
    SUPPORTED_TYPES = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.ms-powerpoint": "ppt",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
        "text/plain": "txt",
        "text/markdown": "md",
        "text/html": "html",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }
    
    def __init__(self):
        self.settings = get_settings()
        self._temp_dir = tempfile.mkdtemp(prefix="rag_pipeline_")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def download_file(self, file_url: str, file_name: str) -> str:
        """
        Download file from URL to local temp directory.
        
        Args:
            file_url: URL of the file in Supabase Storage
            file_name: Original filename
            
        Returns:
            Local path to downloaded file
        """
        logger.info("Downloading file", url=file_url, filename=file_name)
        
        # Create a safe filename
        safe_name = self._sanitize_filename(file_name)
        local_path = os.path.join(self._temp_dir, safe_name)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(file_url)
            response.raise_for_status()
            
            with open(local_path, "wb") as f:
                f.write(response.content)
        
        file_size = os.path.getsize(local_path)
        logger.info("File downloaded", path=local_path, size_bytes=file_size)
        
        return local_path
    
    def detect_file_type(self, file_path: str) -> Tuple[str, str]:
        """
        Detect file type using python-magic.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Tuple of (mime_type, file_extension)
            
        Raises:
            ValueError: If file type is not supported
        """
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(file_path)
        
        logger.info("Detected file type", path=file_path, mime_type=mime_type)
        
        if mime_type not in self.SUPPORTED_TYPES:
            # Try to infer from extension
            ext = os.path.splitext(file_path)[1].lower().lstrip(".")
            for m, e in self.SUPPORTED_TYPES.items():
                if e == ext:
                    logger.warning(
                        "MIME detection failed, using extension",
                        mime_type=mime_type,
                        extension=ext
                    )
                    return m, ext
            
            raise ValueError(
                f"Unsupported file type: {mime_type}. "
                f"Supported types: {list(self.SUPPORTED_TYPES.values())}"
            )
        
        return mime_type, self.SUPPORTED_TYPES[mime_type]
    
    def _sanitize_filename(self, filename: str) -> str:
        """Create a safe filename."""
        # Remove any path components
        filename = os.path.basename(filename)
        # Replace problematic characters
        for char in ['/', '\\', '..', '\x00']:
            filename = filename.replace(char, '_')
        return filename
    
    def cleanup(self, file_path: Optional[str] = None):
        """
        Clean up temporary files.
        
        Args:
            file_path: Specific file to clean up, or None to clean all
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Cleaned up file", path=file_path)
            elif file_path is None:
                import shutil
                if os.path.exists(self._temp_dir):
                    shutil.rmtree(self._temp_dir)
                    logger.info("Cleaned up temp directory", path=self._temp_dir)
        except Exception as e:
            logger.error("Failed to cleanup", error=str(e))


# Singleton instance
_file_handler: Optional[FileHandler] = None


def get_file_handler() -> FileHandler:
    """Get singleton file handler instance."""
    global _file_handler
    if _file_handler is None:
        _file_handler = FileHandler()
    return _file_handler
