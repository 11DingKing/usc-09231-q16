from __future__ import annotations

import io
import unittest
from unittest import mock

from PIL import Image, ImageChops

from vncdotool.client import _PointerOrdering
from vncdotool.const import Encoding
from vncdotool.cursor import CursorMode

from tests.unit.utils import (
    _pixel,
    framebuffer_update,
    handshake,
    make_client,
    rect,
)

POINTER_POS = rect(150, 120, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")
MOVED_POINTER_POS = rect(10, 20, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")
BLACK_PIXEL_AT_ORIGIN = rect(0, 0, 1, 1, Encoding.RAW, _pixel(0, 0, 0))

IMAGE_2X2 = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
MASK_2X2 = bytes([0b11000000, 0b11000000])


def pointer_pos(x: int, y: int) -> bytes:
    return rect(x, y, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")


def cursor_rect(hotspot_x: int = 0, hotspot_y: int = 0) -> bytes:
    body = b"".join(_pixel(*p) for p in IMAGE_2X2) + MASK_2X2
    return rect(hotspot_x, hotspot_y, 2, 2, Encoding.PSEUDO_CURSOR, body)


class TestPointerPos(unittest.TestCase):
    def setUp(self) -> None:
        self.client = make_client()

    def test_position_is_recorded(self) -> None:
        handshake(self.client, 400, 400)

        self.client.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual((self.client.x, self.client.y), (150, 120))

    def test_rectangle_consumes_no_payload(self) -> None:
        """A following rectangle in the same update still decodes."""
        handshake(self.client, 400, 400)
        self.client.factory.cursor = CursorMode.LOCAL

        self.client.dataReceived(framebuffer_update([POINTER_POS, cursor_rect(1, 1)]))

        self.assertEqual((self.client.x, self.client.y), (150, 120))
        self.assertEqual(self.client.cfocus, (1, 1))

    def test_position_is_not_a_screen_change(self) -> None:
        """Nothing was painted, so the rectangle must not satisfy a refresh."""
        handshake(self.client, 400, 400)

        self.client.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.client.rectanglePos, [])

    def test_a_move_by_the_script_supersedes_the_server(self) -> None:
        handshake(self.client, 400, 400)
        self.client.dataReceived(framebuffer_update([POINTER_POS]))

        self.client.mouseMove(10, 20)

        self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_the_shape_is_drawn_where_the_server_says(self) -> None:
        """--localcursor composites at the server's position, not the script's."""
        handshake(self.client, 400, 400)
        self.client.factory.cursor = CursorMode.LOCAL
        self.client.screen = Image.new("RGB", (400, 400))
        self.client.mouseMove(10, 20)
        self.client.dataReceived(framebuffer_update([cursor_rect()]))
        # The server confirms the scripted move before a later, genuine
        # desktop-side move can be reported; on one ordered connection that
        # echo always arrives first.
        self.client.dataReceived(framebuffer_update([MOVED_POINTER_POS]))

        self.client.dataReceived(framebuffer_update([POINTER_POS]))

        self.assertEqual(self.client.renderScreen().getpixel((150, 120)), IMAGE_2X2[0])
        self.assertNotEqual(self.client.screen.getpixel((150, 120)), IMAGE_2X2[0])

    def test_the_shape_is_absent_without_localcursor(self) -> None:
        handshake(self.client, 400, 400)
        self.client.screen = Image.new("RGB", (400, 400))
        self.client.dataReceived(framebuffer_update([cursor_rect(), POINTER_POS]))

        self.assertIsNone(
            ImageChops.difference(
                self.client.renderScreen(), Image.new("RGB", (400, 400))
            ).getbbox()
        )

    def test_an_incremental_capture_holds_one_cursor(self) -> None:
        """A move leaves nothing behind for a later capture to pick up."""
        handshake(self.client, 400, 400)
        self.client.factory.cursor = CursorMode.LOCAL
        self.client.screen = Image.new("RGB", (400, 400))
        self.client.dataReceived(framebuffer_update([cursor_rect(), POINTER_POS]))

        fp = io.BytesIO()
        self.client.captureScreen(fp, incremental=True, format="PNG")
        # One update moving the pointer and repainting a rectangle that does
        # not cover where it was.
        self.client.dataReceived(
            framebuffer_update([MOVED_POINTER_POS, BLACK_PIXEL_AT_ORIGIN])
        )

        expected = Image.new("RGB", (400, 400))
        for i, pixel in enumerate(IMAGE_2X2):
            expected.putpixel((10 + i % 2, 20 + i // 2), pixel)
        with Image.open(fp) as capture:
            difference = ImageChops.difference(capture.convert("RGB"), expected)
        self.assertIsNone(difference.getbbox(), "capture holds a stale cursor")

    def test_a_click_goes_where_the_pointer_is(self) -> None:
        """A pointer the desktop moved takes the next click with it, as a
        real mouse does; clicking where the script last aimed would put it
        somewhere the pointer is not.
        """
        handshake(self.client, 400, 400)
        self.client.mouseMove(10, 20)
        # The scripted move's echo arrives and opens the gate before the
        # server can report that the desktop moved the pointer elsewhere.
        self.client.dataReceived(framebuffer_update([MOVED_POINTER_POS]))
        self.client.dataReceived(framebuffer_update([POINTER_POS]))
        self.client.pointerEvent = mock.Mock()

        self.client.mouseDown(1)

        self.client.pointerEvent.assert_called_once_with(150, 120, buttonmask=1)


class TestPointerEventSequence(unittest.TestCase):
    """Event-ordering scenarios driven through the real RFB byte stream.

    These prove an old PointerPosition left in flight by a local move cannot
    overwrite the newer state, across the equal-position, reorder and
    connection-reset cases.
    """

    def setUp(self) -> None:
        self.client = make_client()
        handshake(self.client, 400, 400)

    def _server_moves(self, x: int, y: int) -> None:
        self.client.dataReceived(framebuffer_update([pointer_pos(x, y)]))

    def test_stale_event_after_local_move_cannot_jump_cursor_back(self) -> None:
        # The pointer sits where the desktop last put it.
        self._server_moves(150, 120)
        self.assertEqual((self.client.x, self.client.y), (150, 120))

        # The script moves it; an old (150, 120) event still in the network
        # then arrives late -- the cursor must not jump back.
        self.client.mouseMove(10, 20)
        self._server_moves(150, 120)

        self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_repeated_stale_events_are_all_dropped(self) -> None:
        self.client.mouseMove(10, 20)

        # Any number of stale, differently-positioned events arrive before
        # the echo; none of them may take.
        for stale in ((150, 120), (5, 5), (399, 399), (150, 120)):
            self._server_moves(*stale)
            self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_echo_opens_the_gate_for_later_genuine_moves(self) -> None:
        self.client.mouseMove(10, 20)
        # Stale event before the echo is dropped.
        self._server_moves(150, 120)
        self.assertEqual((self.client.x, self.client.y), (10, 20))

        # Echo (equal coordinates) confirms the move.
        self._server_moves(10, 20)
        self.assertEqual((self.client.x, self.client.y), (10, 20))
        self.assertFalse(self.client._pointer.awaiting_echo)

        # A later, genuinely newer desktop move now applies.
        self._server_moves(150, 120)
        self.assertEqual((self.client.x, self.client.y), (150, 120))

    def test_two_local_moves_only_the_latest_echo_confirms(self) -> None:
        # Two script moves go out before any echo returns (fast moves).
        self.client.mouseMove(10, 20)
        self.client.mouseMove(30, 40)

        # A late echo of the first (now superseded) move is a stale event.
        self._server_moves(10, 20)
        self.assertEqual((self.client.x, self.client.y), (30, 40))
        self.assertTrue(self.client._pointer.awaiting_echo)

        # The echo of the latest move opens the gate.
        self._server_moves(30, 40)
        self.assertEqual((self.client.x, self.client.y), (30, 40))
        self.assertFalse(self.client._pointer.awaiting_echo)

    def test_move_back_to_known_position_without_echo_stays_open(self) -> None:
        self._server_moves(150, 120)
        self.client.mouseMove(10, 20)
        self._server_moves(10, 20)
        # Move to where the pointer already was before the server echoed the
        # outbound move; a server that suppresses no-op updates must not wedge
        # the gate, so a subsequent genuine move must still apply.
        self.client.mouseMove(10, 20)
        self.assertFalse(self.client._pointer.awaiting_echo)

        self._server_moves(150, 120)
        self.assertEqual((self.client.x, self.client.y), (150, 120))

    def test_connection_reset_clears_the_unconfirmed_move(self) -> None:
        self.client.mouseMove(10, 20)
        self.assertTrue(self.client._pointer.awaiting_echo)
        epoch_before = self.client._pointer.epoch

        # The transport dies before the echo and a fresh one connects.
        self.client.connectionMade()

        self.assertEqual(self.client._pointer.epoch, epoch_before + 1)
        self.assertFalse(self.client._pointer.awaiting_echo)
        # The old connection's missing echo no longer blocks anything: the
        # first position the new server reports is accepted.
        self._server_moves(150, 120)
        self.assertEqual((self.client.x, self.client.y), (150, 120))

    def test_reordered_events_in_one_update_keep_the_latest_state(self) -> None:
        # Within a single dataReceived chunk the bytes are parsed in stream
        # order; the gate must reject whichever stale position interleaves
        # ahead of the pending move's confirmation.
        self.client.mouseMove(10, 20)
        self.client.dataReceived(
            framebuffer_update(
                [pointer_pos(150, 120), pointer_pos(10, 20), pointer_pos(30, 40)]
            )
        )
        # (150, 120) stale -> dropped; (10, 20) echo -> opens gate;
        # (30, 40) genuine newer move -> applied.
        self.assertEqual((self.client.x, self.client.y), (30, 40))


class TestPointerOrdering(unittest.TestCase):
    """Table-driven checks of the staleness primitive itself."""

    def setUp(self) -> None:
        self.ordering = _PointerOrdering()

    def test_server_moves_apply_with_no_local_move(self) -> None:
        self.assertTrue(self.ordering.server_moves(1, 1))
        self.assertTrue(self.ordering.server_moves(2, 2))

    def test_stale_position_rejected_until_echo(self) -> None:
        self.ordering.local_move(10, 20)
        self.assertTrue(self.ordering.awaiting_echo)
        self.assertFalse(self.ordering.server_moves(150, 120))
        self.assertTrue(self.ordering.awaiting_echo)

    def test_equal_position_is_the_echo_and_opens_gate(self) -> None:
        tick = self.ordering.local_move(10, 20)
        # The echo is not "applied" (state already equals it) but confirms.
        self.assertFalse(self.ordering.server_moves(10, 20))
        self.assertFalse(self.ordering.awaiting_echo)
        self.assertEqual(self.ordering.confirmed_tick, tick)
        self.assertTrue(self.ordering.server_moves(150, 120))

    def test_superseded_move_echo_is_stale(self) -> None:
        self.ordering.local_move(10, 20)
        self.ordering.local_move(30, 40)

        self.assertFalse(self.ordering.server_moves(10, 20))
        self.assertTrue(self.ordering.awaiting_echo)
        self.assertFalse(self.ordering.server_moves(30, 40))
        self.assertFalse(self.ordering.awaiting_echo)

    def test_reset_advances_epoch_and_clears_state(self) -> None:
        self.ordering.local_move(10, 20)
        self.ordering.reset()

        self.assertEqual(self.ordering.epoch, 1)
        self.assertFalse(self.ordering.awaiting_echo)
        self.assertEqual(self.ordering.confirmed_tick, 0)
        # The gate is open on the new epoch, and the logical clock has
        # restarted, so the old connection's ticks cannot dominate.
        self.assertTrue(self.ordering.server_moves(9, 9))
        self.assertEqual(self.ordering.local_move(1, 1), 1)
        self.assertFalse(self.ordering.server_moves(9, 9))
        self.assertTrue(self.ordering.awaiting_echo)


if __name__ == "__main__":
    unittest.main()
