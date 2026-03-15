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
            kwargs = {
                "filename": file_path,
                "strategy": "auto", 
                "include_page_breaks": True,
            }
            
            # For PDFs, use hi_res to ensure image extraction works
            if file_type == "pdf":
                kwargs["strategy"] = "hi_res"
                kwargs["extract_images_in_pdf"] = True
                kwargs["infer_table_structure"] = True
                if image_output_dir:
                    kwargs["image_output_dir_path"] = image_output_dir
            
            # For images, high resolution is also required
            if file_type in ["png", "jpg", "jpeg", "webp"]:
                kwargs["strategy"] = "hi_res"
            
            # Run partition with fallback
            strategy_used = kwargs.get("strategy", "auto")
            try:
                logger.info(f"Parsing with strategy='{strategy_used}'", path=file_path)
                elements = partition(**kwargs)
            except Exception as parse_error:
                logger.warning(
                    f"⚠️ Strategy '{strategy_used}' failed, falling back to 'fast'. "
                    f"Images will NOT be extracted in fast mode.",
                    error=str(parse_error),
                    path=file_path
                )
                # Fallback to 'fast' strategy which is text-only but very robust
                kwargs["strategy"] = "fast"
                strategy_used = "fast"
                # Remove visual extraction flags for fast strategy
                kwargs.pop("extract_images_in_pdf", None)
                kwargs.pop("infer_table_structure", None)
                elements = partition(**kwargs)
            
            element_types = self._count_element_types(elements)
            logger.info(
                f"Document parsed successfully (strategy='{strategy_used}')",
                element_count=len(elements),
                element_types=element_types
            )
            
            # Warn if no images were found with hi_res strategy
            if strategy_used == "hi_res" and element_types.get("Image", 0) == 0:
                logger.warning(
                    "⚠️ hi_res strategy found 0 images. "
                    "Ensure 'unstructured[all-docs]' is installed for full image extraction."
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
