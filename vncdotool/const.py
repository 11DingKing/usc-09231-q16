"""RFB encoding numbers shared by the protocol layer and its clients."""
from __future__ import annotations

from enum import IntEnum


class Encoding(IntEnum):
    RAW = 0
    COPY_RECT = 1

    PSEUDO_CURSOR = -239
    PSEUDO_DESKTOP_SIZE = -223
    PSEUDO_LAST_RECT = -224
    PSEUDO_POINTER_POS = -257
    PSEUDO_QEMU_EXTENDED_KEY_EVENT = -258
    PSEUDO_FENCE = -312


# JPEG quality level 0 (worst) .. 9 (best) maps onto the quality pseudo
# encodings -32 .. -23.
JPEG_QUALITY_ENCODINGS: dict[int, int] = {
    quality: -32 + quality for quality in range(10)
}
