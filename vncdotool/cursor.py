"""Where the pointer sprite comes from."""
from __future__ import annotations

from enum import Enum


class CursorMode(Enum):
    # The server draws the pointer into the framebuffer.
    SERVER = "server"
    # The client composites the latest cursor sprite locally.
    LOCAL = "local"
    # No pointer is drawn at all.
    OMIT = "omit"
