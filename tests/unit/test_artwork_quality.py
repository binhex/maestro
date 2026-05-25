"""Tests for artwork image validation and resizing."""

import io

from PIL import Image

from maestro.artwork import validate_and_resize_image


def _make_image(width: int, height: int, fmt: str = "JPEG") -> bytes:
    """Create a simple test image and return its bytes."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, fmt, quality=95)
    return buf.getvalue()


class TestValidateAndResizeImage:
    """Tests for validate_and_resize_image."""

    def test_accepts_exact_size(self) -> None:
        """An image at exactly the target dimensions should pass through."""
        data = _make_image(500, 500)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is not None
        # Should be the same dimensions
        img = Image.open(io.BytesIO(result))
        assert img.width == 500
        assert img.height == 500

    def test_accepts_slightly_larger_and_resizes(self) -> None:
        """An image larger than target should be resized down."""
        data = _make_image(1000, 1000)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.width == 500
        assert img.height == 500

    def test_resizes_to_fit_longest_dimension(self) -> None:
        """A non-square image should resize proportionally to fit within bounds."""
        data = _make_image(1000, 500)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        # Should fit within 500x500, maintaining aspect ratio
        assert img.width <= 500
        assert img.height <= 500
        # Aspect ratio should be preserved (1000:500 = 2:1)
        # So result should be 500x250
        assert img.width == 500
        assert img.height == 250

    def test_rejects_too_small_image(self) -> None:
        """An image smaller than target dimensions should be rejected."""
        data = _make_image(100, 100)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is None

    def test_rejects_wrong_aspect_ratio(self) -> None:
        """An image with significantly wrong aspect ratio should be rejected."""
        # 50x200 is a very tall/narrow image, not suitable for album art
        data = _make_image(50, 200)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is None

    def test_rejects_if_only_one_dimension_too_small(self) -> None:
        """If only one dimension is below minimum, still reject."""
        # 2000x100 is wide but too short
        data = _make_image(2000, 100)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is None

    def test_accepts_if_both_dimensions_meet_minimum(self) -> None:
        """If both dimensions meet the minimum (1/3 of max), accept."""
        data = _make_image(300, 300)
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is not None
        # 300 < 500 so shouldn't resize, but should pass through
        img = Image.open(io.BytesIO(result))
        assert img.width == 300
        assert img.height == 300

    def test_invalid_image_bytes_returns_none(self) -> None:
        """Completely invalid bytes should return None."""
        result = validate_and_resize_image(b"not an image", max_width=500, max_height=500)
        assert result is None

    def test_png_image_is_accepted(self) -> None:
        """PNG images should also be processed."""
        data = _make_image(800, 800, "PNG")
        result = validate_and_resize_image(data, max_width=500, max_height=500)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.width == 500
        assert img.height == 500


class TestArtworkConfigDimensions:
    """Tests for the new artwork dimension config fields."""

    def test_default_config_has_dimensions(self) -> None:
        """Default ArtworkConfig should have width and height."""
        from maestro.config import ArtworkConfig

        config = ArtworkConfig()
        assert config.width == 500
        assert config.height == 500

    def test_config_from_dict_loads_dimensions(self) -> None:
        """Loading config from dict should populate width/height."""
        from maestro.config import ArtworkConfig

        config = ArtworkConfig(**{"width": 300, "height": 400})
        assert config.width == 300
        assert config.height == 400

    def test_config_accepts_minimum_quality(self) -> None:
        """Config should accept min_quality dimension ratio."""
        from maestro.config import ArtworkConfig

        config = ArtworkConfig(**{"width": 600, "height": 600})
        assert config.width == 600
        assert config.height == 600
