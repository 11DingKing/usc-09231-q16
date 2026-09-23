"""Helpers for driving an :class:`VNCDoToolClient` over an in-memory
transport in unit tests.

``handshake`` feeds the bytes of an RFC 6143 handshake with the None
security type; ``framebuffer_update`` and ``rect`` build server-to-client
FramebufferUpdate messages.
"""
from __future__ import annotations

from struct import pack
from typing import Iterable, Sequence

from twisted.internet.testing import StringTransport

from vncdotool import rfb
from vncdotool.client import VNCDoToolClient, VNCDoToolFactory


def make_client() -> VNCDoToolClient:
    """A client on an in-memory transport. Tests then drive the
    handshake with :func:`handshake`."""
    factory = VNCDoToolFactory()
    client = VNCDoToolClient()
    client.factory = factory
    client.makeConnection(StringTransport())
    return client


def handshake(client: VNCDoToolClient, width: int, height: int) -> None:
    """Feed a complete None-security handshake ending in ServerInit
    for a ``width`` x ``height`` framebuffer in XRGB8888."""
    client.dataReceived(b"RFB 003.008\n")
    client.dataReceived(bytes((1, 1)))  # one security type offered: None
    client.dataReceived(pack("!I", 0))  # security result: OK
    name = b"test"
    client.dataReceived(
        pack("!HH", width, height)
        + rfb.PixelFormat().to_bytes()
        + pack("!I", len(name))
        + name
    )


def _pixel(red: int, green: int, blue: int) -> bytes:
    """One XRGB8888 pixel (32 bpp, ignored first byte), the format
    :func:`handshake` negotiates."""
    return pack("!BBBB", 0, red, green, blue)


def rect(
    x: int,
    y: int,
    width: int,
    height: int,
    encoding: int,
    payload: bytes = b"",
) -> bytes:
    """One FramebufferUpdate rectangle header plus its payload."""
    return pack("!HHHHi", x, y, width, height, int(encoding)) + payload


def framebuffer_update(rectangles: Sequence[bytes]) -> bytes:
    """A whole FramebufferUpdate message holding ``rectangles``."""
    header = pack("!BBH", rfb.MsgS2C.FRAMEBUFFER_UPDATE, 0, len(rectangles))
    return header + b"".join(rectangles)
