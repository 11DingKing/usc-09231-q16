"""Translation between RFB :class:`PixelFormat` and PIL raw decoder modes."""
from __future__ import annotations

from struct import pack

from .rfb import PixelFormat


class UnsupportedPixelFormat(Exception):
    """No PIL raw mode matches the negotiated pixel format."""


def raw_mode(pixel_format: PixelFormat) -> str:
    """The PIL ``raw`` decoder mode for a server pixel format.

    Only the 32 bits-per-pixel true-colour layout the tests negotiate is
    needed: bytes in memory are ``[ignored, red, green, blue]``, i.e. PIL's
    ``XRGB`` mode.
    """
    if (
        pixel_format.bpp == 32
        and pixel_format.true_colour
        and not pixel_format.big_endian
        and (pixel_format.red_max, pixel_format.green_max, pixel_format.blue_max)
        == (255, 255, 255)
        and (pixel_format.red_shift, pixel_format.green_shift, pixel_format.blue_shift)
        == (16, 8, 0)
    ):
        return "XRGB"
    raise UnsupportedPixelFormat(pixel_format)


def pack_pixel_format(pixel_format: PixelFormat) -> bytes:
    """The 16-byte SetPixelFormat payload (RFC 6143 section 7.4.1.1)."""
    pf = pixel_format
    return pack(
        "!BBBBHHHBBBxxx",
        pf.bpp,
        pf.depth,
        pf.big_endian,
        pf.true_colour,
        pf.red_max,
        pf.green_max,
        pf.blue_max,
        pf.red_shift,
        pf.green_shift,
        pf.blue_shift,
    )
