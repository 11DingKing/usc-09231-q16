from __future__ import annotations

import enum


class CursorMode(enum.Enum):
    """Who draws the pointer.

    SERVER lets the server paint it into the framebuffer as it always did.
    LOCAL composites it client-side from PseudoCursor / PointerPosition
    updates.  OMIT asks the server to hide it and discards the cursor.
    """

    SERVER = "server"
    LOCAL = "local"
    OMIT = "omit"
