"""Pixel format handling: turn an RFB PixelFormat into the mode Pillow's
raw decoder expects, and the fuzz a comparison must allow for channels the
server's format cannot express.
"""
from __future__ import annotations

from .rfb import PixelFormat


class UnsupportedPixelFormat(Exception):
    """The negotiated pixel format cannot be unpacked into an RGB image."""


PIXEL_FORMATS: dict[str, PixelFormat] = {
    # 8 bits per channel, little-endian, red in the least significant byte;
    # the format setImageMode asks the server to switch to.
    "rgbx8888": PixelFormat(),
}


def raw_mode(pixel_format: PixelFormat) -> str:
    """The Pillow raw mode for pixels laid out as ``pixel_format`` dictates.

    Raises :class:`UnsupportedPixelFormat` for colour-mapped formats or
    channel layouts Pillow has no raw decoder for.
    """
    if not pixel_format.truecolor:
        raise UnsupportedPixelFormat("colour-mapped pixel formats are not supported")

    bpp = pixel_format.bpp

    if bpp == 16:
        # Pillow reads the 16-bit word little-endian; "BGR;16" is RGB565
        # with blue in the low bits, the RFB little-endian default.
        if (
            not pixel_format.bigendian
            and (pixel_format.redmax, pixel_format.greenmax, pixel_format.bluemax)
            == (31, 63, 31)
            and (pixel_format.redshift, pixel_format.greenshift, pixel_format.blueshift)
            == (11, 5, 0)
        ):
            return "BGR;16"
        raise UnsupportedPixelFormat(f"no raw decoder for {bpp}bpp {pixel_format}")

    if bpp in (24, 32):
        channels = (
            (pixel_format.redmax, pixel_format.redshift, "R"),
            (pixel_format.greenmax, pixel_format.greenshift, "G"),
            (pixel_format.bluemax, pixel_format.blueshift, "B"),
        )
        layout: dict[int, str] = {}
        for maximum, shift, band in channels:
            if maximum != 255:
                raise UnsupportedPixelFormat(f"channel {band} is not 8 bits deep")
            if shift % 8:
                raise UnsupportedPixelFormat(f"channel {band} is not byte aligned")
            if pixel_format.bigendian:
                index = (bpp - 8 - shift) // 8
            else:
                index = shift // 8
            if not 0 <= index < bpp // 8 or index in layout:
                raise UnsupportedPixelFormat(f"channels overlap in {pixel_format}")
            layout[index] = band

        mode = "".join(layout.get(i, "X") for i in range(bpp // 8))
        if not {"R", "G", "B"} <= set(mode):
            raise UnsupportedPixelFormat(str(pixel_format))
        return mode

    raise UnsupportedPixelFormat(f"unsupported {bpp}bpp pixel format")


def fuzz_for_format(pixel_format: PixelFormat) -> int:
    """Half the step between two expressible values, on the coarsest channel.

    A server sending 5-bit red (31 levels) cannot hit most 8-bit targets, so
    an exact comparison would never match whatever it paints.
    """
    return max(
        255 // maximum // 2 + 1
        for maximum in (
            pixel_format.redmax,
            pixel_format.greenmax,
            pixel_format.bluemax,
        )
    )
