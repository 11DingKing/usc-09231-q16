"""Framebuffer decoders the client asks for.

Only the encoding list the snapshot's client negotiates is needed here; the
rectangle payloads themselves are dispatched in :mod:`vncdotool.rfb`.
"""
from __future__ import annotations

from .const import Encoding

# RAW is always available; COPY_RECT lets the server move screen regions.
DEFAULT_ENCODINGS: list[Encoding] = [
    Encoding.RAW,
    Encoding.COPY_RECT,
]
