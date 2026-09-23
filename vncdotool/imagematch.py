from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter


def matches(
    image: Image.Image,
    expected: Image.Image,
    fuzz: int = 0,
    blur: int = 0,
) -> bool:
    """Whether ``image`` shows ``expected``, within ``fuzz`` per channel.

    Blurring both frames first lets a match survive a lossy encoding.
    """
    if image.size != expected.size:
        return False

    image = image.convert("RGB")
    expected = expected.convert("RGB")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
        expected = expected.filter(ImageFilter.GaussianBlur(blur))

    difference = ImageChops.difference(image, expected)
    if fuzz <= 0:
        return difference.getbbox() is None

    # Everything fuzz or less away maps to black; any remaining bbox is a
    # pixel further from its target than fuzz permits.
    too_far = difference.point(lambda value: 255 if value > fuzz else 0)
    return too_far.getbbox() is None


def fuzz_for_format(pixel_format: object) -> int:
    from .pixelformat import fuzz_for_format as _fuzz_for_format

    return _fuzz_for_format(pixel_format)  # type: ignore[arg-type]
