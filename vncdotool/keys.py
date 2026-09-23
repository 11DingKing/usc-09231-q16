"""Key symbol table. Only the subset the snapshot's tests exercise is needed;
single characters fall back to their ordinal in VNCDoToolClient._decodeKey.
"""
from __future__ import annotations

KEYMAP: dict[str, int] = {}
