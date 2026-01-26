"""
Document Parser Service
Parses documents using unstructured.io based on file type.
"""
from typing import List, Optional
import structlog

from unstructured.partition.auto import partition
from unstructured.documents.elements import (
    Element,
    Title,
    NarrativeText,
    ListItem,
    Table,
    Image,
    FigureCaption,
)

logger = structlog.get_logger()


class DocumentParser:
    """Parses documents using unstructured.io."""
    
    def __init__(self):
        pass
    
    async def parse(
        self,
        file_path: str,
        file_type: Optional[str] = None,
        image_output_dir: Optional[str] = None
    ) -> List[Element]:
        """
        Parse a document and extract structured elements.
        
        Args:
            file_path: Path to the document
            file_type: Optional file type hint (pdf, docx, etc.)
            image_output_dir: Directory to save extracted images
            
        Returns:
            List of unstructured Element objects
        """
        logger.info("Parsing document", path=file_path, file_type=file_type)
        
        try:
            # Configure partition based on file type
            # Use 'auto' instead of 'hi_res' by default for better stability
            # 'auto' will use 'hi_res' if models are available, otherwise 'fast'
            kwargs = {
                "filename": file_path,
                "strategy": "auto", 
                "include_page_breaks": True,
            }
            
            # For PDFs, attempt to extract visual info if strategy is likely to support it
            if file_type == "pdf":
                kwargs["extract_images_in_pdf"] = True
                kwargs["infer_table_structure"] = True
                if image_output_dir:
                    kwargs["image_output_dir_path"] = image_output_dir
            
            # For images, high resolution is usually required
            if file_type in ["png", "jpg", "jpeg", "webp"]:
                kwargs["strategy"] = "hi_res"
            
            # Run partition with fallback
            try:
                elements = partition(**kwargs)
            except Exception as parse_error:
                logger.warning(
                    "Primary parsing strategy failed, falling back to 'fast'",
                    error=str(parse_error),
                    path=file_path
                )
                # Fallback to 'fast' strategy which is text-only but very robust
                kwargs["strategy"] = "fast"
                # Remove visual extraction flags for fast strategy
                kwargs.pop("extract_images_in_pdf", None)
                kwargs.pop("infer_table_structure", None)
                elements = partition(**kwargs)
            
            logger.info(
                "Document parsed successfully",
                element_count=len(elements),
                element_types=self._count_element_types(elements)
            )
            
            return elements
            
        except Exception as e:
            logger.error("Failed to parse document after fallback", error=str(e), path=file_path)
            raise
    
    def _count_element_types(self, elements: List[Element]) -> dict:
        """Count elements by type for logging."""
        counts = {}
        for el in elements:
            el_type = type(el).__name__
            counts[el_type] = counts.get(el_type, 0) + 1
        return counts
    
    def extract_images(self, elements: List[Element]) -> List[Element]:
        """
        Extract image elements from parsed document.
        
        Args:
            elements: List of all elements
            
        Returns:
            List of Image elements only
        """
        image_elements = [
            el for el in elements 
            if isinstance(el, (Image, FigureCaption))
        ]
        logger.info("Extracted images", count=len(image_elements))
        return image_elements
    
    def extract_tables(self, elements: List[Element]) -> List[Element]:
        """
        Extract table elements from parsed document.
        
        Args:
            elements: List of all elements
            
        Returns:
            List of Table elements only
        """
        table_elements = [el for el in elements if isinstance(el, Table)]
        logger.info("Extracted tables", count=len(table_elements))
        return table_elements
    
    def get_element_text(self, element: Element) -> str:
        """
        Get text content from an element.
        
        Args:
            element: An unstructured Element
            
        Returns:
            Text content as string
        """
        if hasattr(element, 'text'):
            return str(element.text)
        return str(element)
    
    def is_title_element(self, element: Element) -> bool:
        """Check if element is a title/heading."""
        return isinstance(element, Title)
    
    def is_visual_element(self, element: Element) -> bool:
        """Check if element contains visual content (image/table)."""
        return isinstance(element, (Image, Table, FigureCaption))


# Singleton instance
_document_parser: Optional[DocumentParser] = None


def get_document_parser() -> DocumentParser:
    """Get singleton document parser instance."""
    global _document_parser
    if _document_parser is None:
        _document_parser = DocumentParser()
    return _document_parser
