"""Minimal websocket connection support.

Only plain TCP / UNIX sockets are exercised by the test suite; the websocket
path is kept here so ``factory_connect`` can still dispatch on it.  A real
deployment supplies the websocket client endpoint through
``AutobahnEndpoint``-style wrappers, which this snapshot does not bundle.
"""
from __future__ import annotations

import socket
from typing import Any

# A socket.AF_* family (int) or the WEBSOCKET sentinel below.
WEBSOCKET = "websocket"
AddressFamily = int | str


def connect(reactor: Any, factory: Any, url: str) -> Any:  # pragma: no cover
    raise NotImplementedError(
        "websocket connections require a websocket endpoint, unavailable in "
        "this snapshot; connect over TCP or a UNIX socket"
    )


# Re-exported so callers can `from .websocket import AF_UNIX` style checks
# alongside WEBSOCKET.
AF_UNIX = getattr(socket, "AF_UNIX", -1)
AF_INET = socket.AF_INET
AF_INET6 = socket.AF_INET6
AF_UNSPEC = socket.AF_UNSPEC
