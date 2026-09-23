"""WebSocket transport selection.

Only the address-family marker the client imports is needed in the snapshot;
connecting is out of scope for the unit tests.
"""
from __future__ import annotations

import socket

# Sentinel distinct from every :mod:`socket` address-family constant.
WEBSOCKET = object()

AddressFamily = int


def connect(reactor: object, factory: object, url: str) -> object:  # pragma: no cover
    raise NotImplementedError("websocket connections are not supported in this snapshot")
