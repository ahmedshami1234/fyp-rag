"""
Smart Image Filter
Reduces Vision API costs by filtering irrelevant images using multiple heuristics.
"""
from typing import List, Optional, Set, Tuple
import os
import structlog
from dataclasses import dataclass

logger = structlog.get_logger()


@dataclass
class FilterResult:
    """Result of image filtering with statistics."""
    kept_paths: List[str]
    skipped_count: int
    skip_reasons: dict  # reason -> count


class ImageFilter:
    """
    Smart image filtering to reduce Vision API costs.
    
    Filters out:
    - Icons and small graphics (size/dimension thresholds)
    - Decorative lines and borders (aspect ratio)
    - Solid colors and simple logos (entropy)
    - Duplicate images across pages (perceptual hash)
    """
    
    # Configurable thresholds
    MIN_FILE_SIZE = 30 * 1024       # 30KB (skip tiny icons)
    MIN_DIMENSION = 200              # 200px minimum width/height
    MIN_ASPECT_RATIO = 0.2           # Skip very thin images (lines)
    MAX_ASPECT_RATIO = 5.0           # Skip very wide images (banners)
    MIN_ENTROPY = 4.0                # Skip low-complexity images
    MIN_EDGE_DENSITY = 0.05          # Skip simple shapes (optional)
    
    def __init__(
        self,
        min_file_size: Optional[int] = None,
        min_dimension: Optional[int] = None,
        min_entropy: Optional[float] = None,
        enable_dedup: bool = True,
    ):
        """
        Initialize the image filter.
        
        Args:
            min_file_size: Minimum file size in bytes (default: 30KB)
            min_dimension: Minimum width/height in pixels (default: 200)
            min_entropy: Minimum entropy threshold (default: 4.0)
            enable_dedup: Enable duplicate detection (default: True)
        """
        self.min_file_size = min_file_size or self.MIN_FILE_SIZE
        self.min_dimension = min_dimension or self.MIN_DIMENSION
        self.min_entropy = min_entropy or self.MIN_ENTROPY
        self.enable_dedup = enable_dedup
        self._seen_hashes: Set[str] = set()
        
        # Check if imagehash is available for dedup
        self._imagehash_available = False
        if enable_dedup:
            try:
                import imagehash
                self._imagehash_available = True
            except ImportError:
                logger.warning("imagehash not installed - duplicate detection disabled")
    
    def filter_images(self, image_paths: List[str]) -> FilterResult:
        """
        Filter a list of image paths, keeping only meaningful images.
        
        Args:
            image_paths: List of paths to extracted images
            
        Returns:
            FilterResult with kept paths and statistics
        """
        kept = []
        skip_reasons = {
            "file_not_found": 0,
            "too_small_bytes": 0,
            "too_small_dims": 0,
            "bad_aspect_ratio": 0,
            "low_entropy": 0,
            "duplicate": 0,
        }
        
        self._seen_hashes.clear()  # Reset for new document
        
        for path in image_paths:
            reason = self._should_skip(path)
            if reason:
                skip_reasons[reason] += 1
                logger.debug(f"Skipping image: {path} ({reason})")
            else:
                kept.append(path)
        
        skipped = sum(skip_reasons.values())
        logger.info(
            f"🖼️ Image filtering complete: {len(kept)} kept, {skipped} skipped",
            kept=len(kept),
            skipped=skipped,
            reasons=skip_reasons
        )
        
        return FilterResult(
            kept_paths=kept,
            skipped_count=skipped,
            skip_reasons=skip_reasons
        )
    
    def _should_skip(self, image_path: str) -> Optional[str]:
        """
        Check if an image should be skipped.
        
        Returns:
            Skip reason string, or None if image should be kept
        """
        if not image_path or not os.path.exists(image_path):
            return "file_not_found"
        
        # 1. Check file size
        file_size = os.path.getsize(image_path)
        if file_size < self.min_file_size:
            return "too_small_bytes"
        
        try:
            from PIL import Image as PILImage
            
            with PILImage.open(image_path) as img:
                width, height = img.size
                
                # 2. Check dimensions
                if width < self.min_dimension or height < self.min_dimension:
                    return "too_small_dims"
                
                # 3. Check aspect ratio
                aspect = width / height if height > 0 else 0
                if aspect < self.MIN_ASPECT_RATIO or aspect > self.MAX_ASPECT_RATIO:
                    return "bad_aspect_ratio"
                
                # 4. Check entropy (image complexity)
                entropy = self._calculate_entropy(img)
                if entropy < self.min_entropy:
                    return "low_entropy"
                
                # 5. Check for duplicates
                if self.enable_dedup and self._imagehash_available:
                    if self._is_duplicate(img):
                        return "duplicate"
        
        except ImportError:
            # PIL not available, allow image through
            pass
        except Exception as e:
            # Can't read image, allow it through to be safe
            logger.debug(f"Could not analyze image {image_path}: {e}")
        
        return None  # Keep the image
    
    def _calculate_entropy(self, img) -> float:
        """
        Calculate Shannon entropy of an image.
        Higher entropy = more complex/detailed image.
        
        Args:
            img: PIL Image object
            
        Returns:
            Entropy value (typically 0-8 for 8-bit images)
        """
        import math
        
        # Convert to grayscale for entropy calculation
        gray = img.convert("L")
        histogram = gray.histogram()
        total_pixels = sum(histogram)
        
        if total_pixels == 0:
            return 0
        
        entropy = 0
        for count in histogram:
            if count > 0:
                probability = count / total_pixels
                entropy -= probability * math.log2(probability)
        
        return entropy
    
    def _is_duplicate(self, img) -> bool:
        """
        Check if image is a duplicate using perceptual hashing.
        
        Args:
            img: PIL Image object
            
        Returns:
            True if duplicate, False otherwise
        """
        try:
            import imagehash
            
            # Use average hash for speed (alternatives: phash, dhash)
            img_hash = str(imagehash.average_hash(img, hash_size=8))
            
            if img_hash in self._seen_hashes:
                return True
            
            self._seen_hashes.add(img_hash)
            return False
            
        except Exception:
            return False
    
    def is_meaningful_image(self, image_path: str) -> bool:
        """
        Quick check if a single image is meaningful.
        
        Args:
            image_path: Path to the image
            
        Returns:
            True if image should be processed, False otherwise
        """
        return self._should_skip(image_path) is None


# Singleton
_image_filter: Optional[ImageFilter] = None


def get_image_filter() -> ImageFilter:
    """Get singleton image filter instance."""
    global _image_filter
    if _image_filter is None:
        _image_filter = ImageFilter()
    return _image_filter
