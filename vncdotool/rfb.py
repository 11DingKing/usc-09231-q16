"""Minimal RFC 6143 (RFB) protocol machinery for the defect-reproduction
snapshot.

Only the handshake and the server-to-client rectangle encodings touched by
the pointer-position tests are implemented:

* RAW rectangles,
* CopyRect,
* the Cursor (-239), PointerPos (-257), DesktopSize (-223) and LastRect
  (-224) pseudo encodings.

Client-to-server messages are written with their on-the-wire packing so a
``StringTransport`` records what the client sent.
"""
from __future__ import annotations

from dataclasses import dataclass
from struct import pack, unpack
from typing import Callable

from twisted.internet.protocol import Factory, Protocol

from .const import Encoding


class MsgS2C:
    FRAMEBUFFER_UPDATE = 0
    SET_COLOUR_MAP_ENTRIES = 1
    BELL = 2
    SERVER_CUT_TEXT = 3


class MsgC2S:
    SET_PIXEL_FORMAT = 0
    SET_ENCODINGS = 2
    FRAMEBUFFER_UPDATE_REQUEST = 3
    KEY_EVENT = 4
    POINTER_EVENT = 5
    CLIENT_CUT_TEXT = 6


@dataclass(frozen=True)
class PixelFormat:
    bpp: int = 32
    depth: int = 24
    big_endian: bool = False
    true_colour: bool = True
    red_max: int = 255
    green_max: int = 255
    blue_max: int = 255
    red_shift: int = 16
    green_shift: int = 8
    blue_shift: int = 0

    @classmethod
    def from_bytes(cls, block: bytes) -> "PixelFormat":
        (
            bpp,
            depth,
            big_endian,
            true_colour,
            red_max,
            green_max,
            blue_max,
            red_shift,
            green_shift,
            blue_shift,
        ) = unpack("!BBBBHHHBBBxxx", block)
        return cls(
            bpp,
            depth,
            bool(big_endian),
            bool(true_colour),
            red_max,
            green_max,
            blue_max,
            red_shift,
            green_shift,
            blue_shift,
        )

    def to_bytes(self) -> bytes:
        return pack(
            "!BBBBHHHBBBxxx",
            self.bpp,
            self.depth,
            self.big_endian,
            self.true_colour,
            self.red_max,
            self.green_max,
            self.blue_max,
            self.red_shift,
            self.green_shift,
            self.blue_shift,
        )


class RFBClient(Protocol):
    def __init__(self) -> None:
        self._buffer = b""
        self._next: tuple[int, Callable[[bytes], None]] = (
            12,
            self._handleServerVersion,
        )
        self.width = 0
        self.height = 0
        self.desktop_name = b""
        self.pixel_format = PixelFormat()
        self.x = 0
        self.y = 0
        self.buttons = 0
        # Positions of content rectangles in the current update; pseudo
        # encodings (pointer motion, cursor shape, desktop resize) do not
        # paint the framebuffer and are intentionally absent.
        self.rectanglePos: list[tuple[int, int, int, int]] = []
        self._fb_remaining = 0
        self._fb_last_rect = False
        self._rect = (0, 0, 0, 0)

    # -- framing ---------------------------------------------------------

    def dataReceived(self, data: bytes) -> None:
        self._buffer += data
        while self._next is not None:
            size, handler = self._next
            if len(self._buffer) < size:
                return
            block, self._buffer = self._buffer[:size], self._buffer[size:]
            self._next = None
            handler(block)

    def _expect(self, size: int, handler: Callable[[bytes], None]) -> None:
        self._next = (size, handler)

    # -- handshake -------------------------------------------------------

    def _handleServerVersion(self, block: bytes) -> None:
        self.server_version = block
        self.transport.write(b"RFB 003.008\n")
        self._expect(1, self._handleSecurityTypeCount)

    def _handleSecurityTypeCount(self, block: bytes) -> None:
        count = block[0]
        if count == 0:
            # Connection failed: u32 reason-length follows.
            self._expect(4, self._handleSecurityFailureLength)
        else:
            self._expect(count, self._handleSecurityTypes)

    def _handleSecurityFailureLength(self, block: bytes) -> None:
        (length,) = unpack("!I", block)
        self._expect(length, self._handleSecurityFailure)

    def _handleSecurityFailure(self, block: bytes) -> None:
        self.vncProtocolError(block.decode("utf-8", "replace"))
        self.transport.loseConnection()

    def _handleSecurityTypes(self, block: bytes) -> None:
        # The tests negotiate security type 1 (None); nothing stronger is
        # implemented in the snapshot.
        if 1 not in block:
            self.vncProtocolError("server offered no supported security type")
            self.transport.loseConnection()
            return
        self.transport.write(bytes((1,)))
        self._expect(4, self._handleSecurityResult)

    def _handleSecurityResult(self, block: bytes) -> None:
        (result,) = unpack("!I", block)
        if result != 0:
            self._expect(4, self._handleSecurityFailureLength)
            return
        # ClientInit: share the desktop.
        self.transport.write(bytes((1,)))
        self._expect(24, self._handleServerInitHeader)

    def _handleServerInitHeader(self, block: bytes) -> None:
        self.width, self.height = unpack("!HH", block[:4])
        self.pixel_format = PixelFormat.from_bytes(block[4:20])
        (name_length,) = unpack("!I", block[20:24])
        self._expect(name_length, self._handleServerInitName)

    def _handleServerInitName(self, block: bytes) -> None:
        self.desktop_name = block
        self._expect(1, self._handleMessageType)
        self.vncConnectionMade()

    # -- server messages -------------------------------------------------

    def _handleMessageType(self, block: bytes) -> None:
        message_type = block[0]
        if message_type == MsgS2C.FRAMEBUFFER_UPDATE:
            self._expect(3, self._handleFramebufferUpdateHeader)
        elif message_type == MsgS2C.BELL:
            self.bell()
            self._expect(1, self._handleMessageType)
        elif message_type == MsgS2C.SERVER_CUT_TEXT:
            self._expect(7, self._handleServerCutTextHeader)
        else:
            self.vncProtocolError(f"unknown message type {message_type}")

    def _handleFramebufferUpdateHeader(self, block: bytes) -> None:
        (number_of_rects,) = unpack("!H", block[1:3])
        self.rectanglePos = []
        self._fb_remaining = number_of_rects
        self._fb_last_rect = False
        self._readRectangleHeader()

    def _readRectangleHeader(self) -> None:
        self._expect(12, self._handleRectangleHeader)

    def _handleRectangleHeader(self, block: bytes) -> None:
        x, y, width, height, encoding = unpack("!HHHHi", block)
        self._rect = (x, y, width, height)

        if encoding == Encoding.PSEUDO_POINTER_POS:
            self._fb_remaining -= 1
            self.updatePointerPos(x, y)
            self._afterRectangle()
        elif encoding == Encoding.PSEUDO_DESKTOP_SIZE:
            self._fb_remaining -= 1
            self.updateDesktopSize(width, height)
            self._afterRectangle()
        elif encoding == Encoding.PSEUDO_LAST_RECT:
            # With LastRect the header count is a placeholder; the marker
            # ends the update itself.
            self._fb_last_rect = True
            self._afterRectangle()
        elif encoding == Encoding.PSEUDO_CURSOR:
            pixels = width * height * (self.pixel_format.bpp // 8)
            mask = ((width + 7) // 8) * height
            self._expect(pixels + mask, self._handleCursorPayload)
        elif encoding == Encoding.RAW:
            length = width * height * (self.pixel_format.bpp // 8)
            self._expect(length, self._handleRawPayload)
        elif encoding == Encoding.COPY_RECT:
            self._expect(4, self._handleCopyRectPayload)
        else:
            self.vncProtocolError(f"unsupported encoding {encoding}")
            self.transport.loseConnection()

    def _handleCursorPayload(self, block: bytes) -> None:
        x, y, width, height = self._rect
        pixels = width * height * (self.pixel_format.bpp // 8)
        self.updateCursor(x, y, width, height, block[:pixels], block[pixels:])
        self._fb_remaining -= 1
        self._afterRectangle()

    def _handleRawPayload(self, block: bytes) -> None:
        x, y, width, height = self._rect
        self.rectanglePos.append((x, y, width, height))
        self.updateRectangle(x, y, width, height, block, self.pixel_format)
        self._fb_remaining -= 1
        self._afterRectangle()

    def _handleCopyRectPayload(self, block: bytes) -> None:
        srcx, srcy = unpack("!HH", block)
        x, y, width, height = self._rect
        self.rectanglePos.append((x, y, width, height))
        self.copyRectangle(srcx, srcy, x, y, width, height)
        self._fb_remaining -= 1
        self._afterRectangle()

    def _afterRectangle(self) -> None:
        if self._fb_last_rect or self._fb_remaining <= 0:
            self._expect(1, self._handleMessageType)
            self.commitUpdate(self.rectanglePos)
        else:
            self._readRectangleHeader()

    def _handleServerCutTextHeader(self, block: bytes) -> None:
        (length,) = unpack("!I", block[3:7])
        self._expect(length, self._handleServerCutText)

    def _handleServerCutText(self, block: bytes) -> None:
        self.copy_text(block.decode("latin-1"))
        self._expect(1, self._handleMessageType)

    # -- hooks -----------------------------------------------------------

    def vncConnectionMade(self) -> None:
        """Override hook: handshake finished."""

    def vncProtocolError(self, reason: str) -> None:
        """Override hook: the server broke the protocol."""
        raise RuntimeError(reason)

    def updateRectangle(self, x, y, width, height, data, pixel_format) -> None:
        pass

    def copyRectangle(self, srcx, srcy, x, y, width, height) -> None:
        pass

    def updateCursor(self, x, y, width, height, image, mask) -> None:
        pass

    def updatePointerPos(self, x: int, y: int) -> None:
        pass

    def updateDesktopSize(self, width: int, height: int) -> None:
        pass

    def commitUpdate(self, rectangles=None) -> None:
        pass

    def bell(self) -> None:
        pass

    def copy_text(self, text: str) -> None:
        pass

    # -- client-to-server messages --------------------------------------

    def setPixelFormat(self, pixel_format: PixelFormat) -> None:
        self.transport.write(
            pack("!BBxxx", MsgC2S.SET_PIXEL_FORMAT, 0) + pixel_format.to_bytes()
        )

    def setEncodings(self, encodings) -> None:
        payload = pack("!BBH", MsgC2S.SET_ENCODINGS, 0, len(encodings))
        for encoding in encodings:
            payload += pack("!i", int(encoding))
        self.transport.write(payload)

    def framebufferUpdateRequest(self, incremental: bool = True, x: int = 0,
                                 y: int = 0, width: int | None = None,
                                 height: int | None = None) -> None:
        self.transport.write(
            pack(
                "!BBHHHH",
                MsgC2S.FRAMEBUFFER_UPDATE_REQUEST,
                1 if incremental else 0,
                x,
                y,
                self.width if width is None else width,
                self.height if height is None else height,
            )
        )

    def keyEvent(self, key: int, down: bool = True) -> None:
        self.transport.write(
            pack("!BBxxI", MsgC2S.KEY_EVENT, 1 if down else 0, key)
        )

    def pointerEvent(self, x: int, y: int, buttonmask: int = 0) -> None:
        self.transport.write(
            pack("!BBHH", MsgC2S.POINTER_EVENT, buttonmask, x, y)
        )

    def clientCutText(self, text: str) -> None:
        payload = text.encode("latin-1")
        self.transport.write(
            pack("!BBxxI", MsgC2S.CLIENT_CUT_TEXT, 0, len(payload)) + payload
        )

    def sendPassword(self, password: str) -> None:  # pragma: no cover
        raise NotImplementedError("authentication is not supported in this snapshot")


class RFBFactory(Factory):
    protocol = RFBClient
