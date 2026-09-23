"""Helpers shared by the unit tests: build a wired-up client and forge the
exact RFB bytes the tests feed to ``dataReceived``.
"""
from __future__ import annotations

from struct import pack
from unittest import mock

from vncdotool.client import VNCDoToolClient, VNCDoToolFactory
from vncdotool.rfb import PixelFormat

# The oldest handshake the parser accepts; the tests jump straight from the
# version banner to ServerInit, as the upstream suite does.
MSG_HANDSHAKE = b"RFB 003.003\n"


def _pixel(red: int, green: int, blue: int) -> bytes:
    """One pixel in the negotiated little-endian RGBX8888 format."""
    return bytes((red, green, blue, 0))


def rect(
    x: int, y: int, width: int, height: int, encoding: int, payload: bytes = b""
) -> bytes:
    """A FramebufferUpdate rectangle: 12-byte header then its payload."""
    return pack("!HHHHi", x, y, width, height, encoding) + payload


def framebuffer_update(rectangles: list[bytes]) -> bytes:
    return pack("!BBH", 0, 0, len(rectangles)) + b"".join(rectangles)


def make_client() -> VNCDoToolClient:
    client = VNCDoToolClient()
    client.transport = mock.Mock()
    client.factory = VNCDoToolFactory()
    return client


def handshake(client: VNCDoToolClient, width: int, height: int) -> VNCDoToolClient:
    """Drive a client through banner/initialisation to the connected state.

    Leaves it expecting the first server-to-client message, so subsequent
    ``dataReceived`` calls are parsed as FramebufferUpdates.
    """
    name_length = 0
    server_init = (
        pack("!HH", width, height)
        + PixelFormat().to_bytes()
        + pack("!I", name_length)
    )
    client._packet = bytearray(MSG_HANDSHAKE)
    client._handleInitial()
    client._handleServerInit(server_init)
    return client
