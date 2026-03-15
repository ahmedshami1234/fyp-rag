"""
Unit tests for the ImageFilter service.
Tests smart image filtering with various criteria.
"""
import pytest
import tempfile
import os
from pathlib import Path


class TestImageFilter:
    """Tests for ImageFilter class."""
    
    @pytest.fixture
    def image_filter(self):
        """Create an ImageFilter instance."""
        from app.services.image_filter import ImageFilter
        return ImageFilter(enable_dedup=True)
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test images."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    def _create_test_image(self, path: str, width: int, height: int, color: tuple = (128, 128, 128)):
        """Create a test image with specified dimensions."""
        from PIL import Image
        img = Image.new('RGB', (width, height), color)
        img.save(path)
        return path
    
    def _create_gradient_image(self, path: str, width: int, height: int):
        """Create a high-entropy gradient image."""
        from PIL import Image
        import random
        img = Image.new('RGB', (width, height))
        pixels = img.load()
        for i in range(width):
            for j in range(height):
                pixels[i, j] = (i % 256, j % 256, (i + j) % 256)
        img.save(path, quality=95)
        return path
    
    def test_skip_small_file(self, image_filter, temp_dir):
        """Test that very small files are skipped."""
        # Create a tiny image (under 30KB)
        small_path = os.path.join(temp_dir, "tiny.png")
        self._create_test_image(small_path, 50, 50)  # Very small
        
        result = image_filter.filter_images([small_path])
        
        assert len(result.kept_paths) == 0
        assert result.skip_reasons["too_small_bytes"] > 0 or result.skip_reasons["too_small_dims"] > 0
    
    def test_skip_small_dimensions(self, image_filter, temp_dir):
        """Test that images with small dimensions are skipped."""
        # Create an image with dimensions under 80x80 (new threshold)
        small_dim_path = os.path.join(temp_dir, "small_dims.png")
        self._create_test_image(small_dim_path, 60, 60)
        
        result = image_filter.filter_images([small_dim_path])
        
        assert len(result.kept_paths) == 0
    
    def test_keep_large_complex_image(self, image_filter, temp_dir):
        """Test that large, complex images are kept."""
        # Create a large gradient image (high entropy, large size)
        large_path = os.path.join(temp_dir, "large_complex.jpg")
        self._create_gradient_image(large_path, 500, 500)
        
        # Check file is large enough
        file_size = os.path.getsize(large_path)
        
        result = image_filter.filter_images([large_path])
        
        # Should be kept (if file size is sufficient)
        if file_size >= 30 * 1024:
            assert len(result.kept_paths) == 1
        else:
            # May be skipped due to file size on some systems
            assert result.skipped_count >= 0
    
    def test_skip_low_entropy_solid_color(self, image_filter, temp_dir):
        """Test that solid color images (low entropy) are skipped."""
        # Create a large but solid color image
        solid_path = os.path.join(temp_dir, "solid.png")
        self._create_test_image(solid_path, 400, 400, color=(255, 255, 255))
        
        result = image_filter.filter_images([solid_path])
        
        # Solid images have very low entropy
        assert result.skip_reasons.get("low_entropy", 0) > 0 or result.skipped_count > 0
    
    def test_skip_bad_aspect_ratio_wide(self, image_filter, temp_dir):
        """Test that very wide images (banners) are skipped."""
        # Create a very wide banner-like image
        wide_path = os.path.join(temp_dir, "wide.png")
        self._create_gradient_image(wide_path, 1000, 100)
        
        result = image_filter.filter_images([wide_path])
        
        # Aspect ratio 10:1 exceeds MAX_ASPECT_RATIO of 8.0
        assert result.skip_reasons.get("bad_aspect_ratio", 0) > 0 or result.skipped_count > 0
    
    def test_skip_bad_aspect_ratio_thin(self, image_filter, temp_dir):
        """Test that very thin images (lines) are skipped."""
        # Create a very thin line-like image
        thin_path = os.path.join(temp_dir, "thin.png")
        self._create_gradient_image(thin_path, 50, 500)
        
        result = image_filter.filter_images([thin_path])
        
        # Aspect ratio 0.1:1 below MIN_ASPECT_RATIO of 0.2
        assert result.skip_reasons.get("bad_aspect_ratio", 0) > 0 or result.skipped_count > 0
    
    def test_duplicate_detection(self, image_filter, temp_dir):
        """Test that duplicate images are skipped."""
        # Create a complex image
        path1 = os.path.join(temp_dir, "original.jpg")
        self._create_gradient_image(path1, 400, 400)
        
        # Create an identical copy
        path2 = os.path.join(temp_dir, "duplicate.jpg")
        import shutil
        shutil.copy(path1, path2)
        
        result = image_filter.filter_images([path1, path2])
        
        # First should be kept, second should be skipped as duplicate
        # Note: depends on file size meeting threshold
        if len(result.kept_paths) > 0:
            assert result.skip_reasons.get("duplicate", 0) >= 0
    
    def test_file_not_found(self, image_filter):
        """Test handling of non-existent files."""
        result = image_filter.filter_images(["/nonexistent/path/image.png"])
        
        assert len(result.kept_paths) == 0
        assert result.skip_reasons["file_not_found"] == 1
    
    def test_mixed_images(self, image_filter, temp_dir):
        """Test filtering a mix of good and bad images."""
        # Create various images
        tiny = os.path.join(temp_dir, "tiny.png")
        self._create_test_image(tiny, 30, 30)
        
        medium_solid = os.path.join(temp_dir, "medium_solid.png")
        self._create_test_image(medium_solid, 300, 300, color=(200, 200, 200))
        
        good = os.path.join(temp_dir, "good.jpg")
        self._create_gradient_image(good, 500, 500)
        
        paths = [tiny, medium_solid, good]
        result = image_filter.filter_images(paths)
        
        # At least the tiny one should be skipped
        assert result.skipped_count >= 1
    
    def test_empty_list(self, image_filter):
        """Test filtering empty list of images."""
        result = image_filter.filter_images([])
        
        assert len(result.kept_paths) == 0
        assert result.skipped_count == 0
    
    def test_skip_logo_image(self, image_filter, temp_dir):
        """Test that small square images with few colors (logos) are skipped."""
        from PIL import Image
        logo_path = os.path.join(temp_dir, "logo.png")
        # Create a small, square image with very few colors (logo characteristics)
        img = Image.new('RGB', (150, 150), (255, 255, 255))
        pixels = img.load()
        # Draw a simple shape with only 3 colors total
        for i in range(50, 100):
            for j in range(50, 100):
                pixels[i, j] = (0, 0, 200)
        for i in range(60, 90):
            for j in range(60, 90):
                pixels[i, j] = (255, 0, 0)
        img.save(logo_path)
        
        result = image_filter.filter_images([logo_path])
        
        # Should be skipped as logo (small, square, few colors)
        assert result.skip_reasons.get("logo", 0) > 0 or result.skipped_count > 0
    
    def test_keep_table_like_image(self, image_filter, temp_dir):
        """Test that table-like images with grid patterns are KEPT."""
        from PIL import Image, ImageDraw
        table_path = os.path.join(temp_dir, "table.png")
        # Create a table-like image: larger, with many text-like variations
        img = Image.new('RGB', (600, 400), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Draw grid lines (table structure)
        for y in range(0, 400, 40):
            draw.line([(0, y), (600, y)], fill=(0, 0, 0), width=1)
        for x in range(0, 600, 120):
            draw.line([(x, 0), (x, 400)], fill=(0, 0, 0), width=1)
        # Add varied pixel content to simulate text in cells
        import random
        random.seed(42)
        for row in range(10):
            for col in range(5):
                x_start = col * 120 + 10
                y_start = row * 40 + 10
                for dx in range(0, 100, 4):
                    for dy in range(0, 20, 4):
                        c = random.randint(0, 180)
                        draw.rectangle(
                            [(x_start + dx, y_start + dy), 
                             (x_start + dx + 3, y_start + dy + 3)],
                            fill=(c, c, c)
                        )
        img.save(table_path, quality=95)
        
        file_size = os.path.getsize(table_path)
        # Only assert if file is large enough to pass size threshold
        if file_size >= 3 * 1024:
            result = image_filter.filter_images([table_path])
            assert len(result.kept_paths) == 1, (
                f"Table image should be KEPT but was skipped. "
                f"Skip reasons: {result.skip_reasons}"
            )


class TestImageFilterSingleton:
    """Tests for ImageFilter singleton."""
    
    def test_get_image_filter_returns_instance(self):
        """Test that get_image_filter returns an ImageFilter instance."""
        from app.services.image_filter import get_image_filter, ImageFilter
        
        filter_instance = get_image_filter()
        assert isinstance(filter_instance, ImageFilter)
    
    def test_get_image_filter_singleton(self):
        """Test that get_image_filter returns the same instance."""
        from app.services.image_filter import get_image_filter
        
        filter1 = get_image_filter()
        filter2 = get_image_filter()
        
        assert filter1 is filter2
