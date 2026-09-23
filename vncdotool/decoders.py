"""Encoding preference list offered to the server when the caller does not
name one of its own.
"""
from __future__ import annotations

from .const import Encoding

# Ordered best-first. Every entry here is one the RFBClient decoder can
# parse; the server picks the first it supports.
DEFAULT_ENCODINGS: list[Encoding] = [
    Encoding.RAW,
    Encoding.COPY_RECTANGLE,
    Encoding.HEXTILE,
    Encoding.ZRLE,
]
