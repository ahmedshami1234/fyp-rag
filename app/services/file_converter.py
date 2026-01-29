"""
File Converter Service
Converts DOCX, PPTX, and other formats to PDF using LibreOffice CLI.
"""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path          
from typing import Optional, Tuple
import structlog

logger = structlog.get_logger()


class FileConverter:
    """
    Converts office documents to PDF using LibreOffice.
    hb
    Supported formats:
    - DOCX, DOC → PDF
    - PPTX, PPT → PDF
    - ODT, ODS, ODP → PDF
    - TXT, RTF → PDF
    """
    
    # Formats that need conversion to PDF
    CONVERTIBLE_FORMATS = {
        'docx', 'doc', 'odt', 'rtf', 'txt',
        'pptx', 'ppt', 'odp',
        'xlsx', 'xls', 'ods'
    }
    
    # Formats that are already PDF or don't need conversion
    NATIVE_FORMATS = {'pdf'}
    
    def __init__(self):
        self.soffice_path = self._find_libreoffice()
        if self.soffice_path:
            logger.info(f"LibreOffice found at: {self.soffice_path}")
        else:
            logger.warning("LibreOffice not found - conversion will fail for non-PDF files")
    
    def _find_libreoffice(self) -> Optional[str]:
        """Find LibreOffice CLI executable."""
        # Common paths for LibreOffice
        possible_paths = [
            # Mac
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',
            # Linux
            '/usr/bin/soffice',
            '/usr/bin/libreoffice',
            '/usr/local/bin/soffice',
            # Alternative Mac paths
            '/opt/homebrew/bin/soffice',
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Try to find using 'which'
        try:
            result = subprocess.run(['which', 'soffice'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        
        return None
    
    def needs_conversion(self, file_type: str) -> bool:
        """Check if file type needs conversion to PDF."""
        return file_type.lower() in self.CONVERTIBLE_FORMATS
    
    def is_supported(self, file_type: str) -> bool:
        """Check if file type is supported (either native or convertible)."""
        ft = file_type.lower()
        return ft in self.NATIVE_FORMATS or ft in self.CONVERTIBLE_FORMATS
    
    async def convert_to_pdf(
        self, 
        input_path: str, 
        file_type: str
    ) -> Tuple[str, bool]:
        """
        Convert a file to PDF if needed.
        
        Args:
            input_path: Path to the input file
            file_type: File extension (docx, pptx, etc.)
            
        Returns:
            Tuple of (output_path, was_converted)
            - If already PDF: returns (input_path, False)
            - If converted: returns (new_pdf_path, True)
        """
        ft = file_type.lower()
        
        # Already PDF, no conversion needed
        if ft in self.NATIVE_FORMATS:
            logger.info(f"File is already PDF, no conversion needed")
            return input_path, False
        
        # Check if conversion is supported
        if ft not in self.CONVERTIBLE_FORMATS:
            raise ValueError(f"Unsupported file format: {file_type}")
        
        # Check if LibreOffice is available
        if not self.soffice_path:
            raise RuntimeError(
                "LibreOffice is not installed. "
                "Please install it: brew install --cask libreoffice"
            )
        
        # Create output directory
        output_dir = tempfile.mkdtemp(prefix="pdf_convert_")
        
        try:
            logger.info(f"Converting {file_type.upper()} to PDF...")
            
            # Run LibreOffice conversion
            result = subprocess.run(
                [
                    self.soffice_path,
                    '--headless',  # No GUI
                    '--convert-to', 'pdf',
                    '--outdir', output_dir,
                    input_path
                ],
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            if result.returncode != 0:
                logger.error(f"Conversion failed: {result.stderr}")
                raise RuntimeError(f"PDF conversion failed: {result.stderr}")
            
            # Find the output PDF
            input_name = Path(input_path).stem
            output_pdf = os.path.join(output_dir, f"{input_name}.pdf")
            
            if not os.path.exists(output_pdf):
                raise RuntimeError("Conversion completed but PDF file not found")
            
            logger.info(f"✅ Conversion successful: {output_pdf}")
            return output_pdf, True
            
        except subprocess.TimeoutExpired:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise RuntimeError("PDF conversion timed out")
        except Exception as e:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise
    
    def get_supported_extensions(self) -> list:
        """Get list of all supported file extensions."""
        return sorted(list(self.NATIVE_FORMATS | self.CONVERTIBLE_FORMATS))


# Singleton instance
_file_converter = None

def get_file_converter() -> FileConverter:
    """Get or create the file converter instance."""
    global _file_converter
    if _file_converter is None:
        _file_converter = FileConverter()
    return _file_converter
