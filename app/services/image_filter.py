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
    MIN_FILE_SIZE = 3 * 1024         # 3KB (skip only truly tiny icons)
    MIN_DIMENSION = 80               # 80px minimum (some table crops are small)
    MIN_ASPECT_RATIO = 0.2           # Skip very thin images (lines)
    MAX_ASPECT_RATIO = 8.0           # Skip extremely wide images
    MIN_ENTROPY = 1.5                # Lower: only skip solid colors/simple logos
    MIN_EDGE_DENSITY = 0.05          # Skip simple shapes (optional)
    LOGO_MAX_DIMENSION = 250         # Max dimension for logo heuristic
    LOGO_MAX_COLORS = 16             # Max unique colors for logo detection
    
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
            "logo": 0,
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
            logger.debug(
                f"Image skipped (too_small_bytes): {os.path.basename(image_path)} "
                f"size={file_size} bytes, min={self.min_file_size} bytes"
            )
            return "too_small_bytes"
        
        try:
            from PIL import Image as PILImage
            
            with PILImage.open(image_path) as img:
                width, height = img.size
                
                # 2. Check dimensions
                if width < self.min_dimension or height < self.min_dimension:
                    logger.debug(
                        f"Image skipped (too_small_dims): {os.path.basename(image_path)} "
                        f"{width}x{height}px, min={self.min_dimension}px"
                    )
                    return "too_small_dims"
                
                # 3. Check aspect ratio
                aspect = width / height if height > 0 else 0
                if aspect < self.MIN_ASPECT_RATIO or aspect > self.MAX_ASPECT_RATIO:
                    logger.debug(
                        f"Image skipped (bad_aspect_ratio): {os.path.basename(image_path)} "
                        f"aspect={aspect:.2f}, range=[{self.MIN_ASPECT_RATIO}, {self.MAX_ASPECT_RATIO}]"
                    )
                    return "bad_aspect_ratio"
                
                # 4. Logo detection — small, square, very few colors
                if self._is_likely_logo(img, width, height):
                    logger.debug(
                        f"Image skipped (logo): {os.path.basename(image_path)} "
                        f"{width}x{height}px, detected as likely logo/icon"
                    )
                    return "logo"
                
                # 5. Check entropy (image complexity)
                entropy = self._calculate_entropy(img)
                if entropy < self.min_entropy:
                    logger.debug(
                        f"Image skipped (low_entropy): {os.path.basename(image_path)} "
                        f"entropy={entropy:.2f}, min={self.min_entropy}"
                    )
                    return "low_entropy"
                
                # 5. Check for duplicates
                if self.enable_dedup and self._imagehash_available:
                    if self._is_duplicate(img):
                        return "duplicate"
                
                logger.debug(
                    f"Image KEPT: {os.path.basename(image_path)} "
                    f"{width}x{height}px, {file_size} bytes, entropy={entropy:.2f}"
                )
        
        except ImportError:
            # PIL not available, allow image through
            logger.warning("PIL not installed — skipping image analysis, allowing image through")
        except Exception as e:
            # Can't read image, allow it through to be safe
            logger.debug(f"Could not analyze image {image_path}: {e}")
        
        return None  # Keep the image
    
    def _is_likely_logo(self, img, width: int, height: int) -> bool:
        """
        Detect if image is likely a logo or icon.
        
        Logos are typically: small, roughly square, and use very few colors.
        Tables/charts/diagrams use many colors and are usually larger.
        
        Args:
            img: PIL Image object
            width: Image width
            height: Image height
            
        Returns:
            True if image is likely a logo/icon
        """
        # Only consider small images as potential logos
        if width > self.LOGO_MAX_DIMENSION and height > self.LOGO_MAX_DIMENSION:
            return False
        
        # Logos tend to be roughly square (aspect ratio between 0.5 and 2.0)
        aspect = width / height if height > 0 else 0
        if aspect < 0.5 or aspect > 2.0:
            return False  # Not square-ish, probably not a logo
        
        # Count unique colors — logos use very few
        try:
            # Quantize to reduce noise, then count colors
            small = img.resize((64, 64)).convert("RGB")
            colors = small.getcolors(maxcolors=1000)
            if colors is not None:
                unique_colors = len(colors)
                if unique_colors <= self.LOGO_MAX_COLORS:
                    logger.debug(
                        f"Logo detected: {width}x{height}px, {unique_colors} unique colors"
                    )
                    return True
        except Exception:
            pass
        
        return False
    
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
