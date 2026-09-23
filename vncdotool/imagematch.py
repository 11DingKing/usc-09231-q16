"""Whole-screen image comparison helpers.

The snapshot only needs the API surface :class:`VNCDoToolClient` calls; the
comparison is a simple per-channel maximum difference.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter

from .rfb import PixelFormat


def matches(
    actual: Image.Image, expected: Image.Image, fuzz: int, blur: int = 0
) -> bool:
    """Whether every channel of ``actual`` sits within ``fuzz`` of
    ``expected``; a Gaussian ``blur`` is applied to both first when given."""
    if actual.size != expected.size:
        return False
    difference = ImageChops.difference(actual.convert("RGB"), expected.convert("RGB"))
    if blur:
        difference = difference.filter(ImageFilter.GaussianBlur(blur))
    return max(channel_max for _, channel_max in difference.getextrema()) <= fuzz


def fuzz_for_format(pixel_format: PixelFormat) -> int:
    """The distance one colour step spans in an 8-bit channel, which
    exact pixel values may miss by."""
    smallest_max = min(pixel_format.red_max, pixel_format.green_max, pixel_format.blue_max)
    if smallest_max >= 255:
        return 0
    return max(1, 255 // (smallest_max + 1))
