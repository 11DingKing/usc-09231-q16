from __future__ import annotations

import io
import unittest
from unittest import mock

from PIL import Image, ImageChops

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


def pointer_pos(x: int, y: int) -> bytes:
    return rect(x, y, 0, 0, Encoding.PSEUDO_POINTER_POS, b"")


IMAGE_2X2 = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
MASK_2X2 = bytes([0b11000000, 0b11000000])


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
        self.client.dataReceived(framebuffer_update([POINTER_POS]))
        self.client.pointerEvent = mock.Mock()

        self.client.mouseDown(1)

        self.client.pointerEvent.assert_called_once_with(150, 120, buttonmask=1)


class TestPointerPosSequence(unittest.TestCase):
    """Event-ordering cases: an old PointerPos must never overwrite newer
    pointer state, while genuine motion still gets through."""

    def setUp(self) -> None:
        self.client = make_client()
        handshake(self.client, 400, 400)

    def _pos(self, x: int, y: int) -> None:
        self.client.dataReceived(framebuffer_update([pointer_pos(x, y)]))

    def test_a_lagging_old_position_cannot_jump_the_pointer_back(self) -> None:
        """The reported defect: the server had reported (150,120); that
        update is still queued in the network when the script moves to
        (10,20). The stale (150,120) then arrives and must be discarded.
        """
        self._pos(150, 120)
        self.assertEqual((self.client.x, self.client.y), (150, 120))

        self.client.mouseMove(10, 20)
        # Old in-flight update delivered only after the move completed.
        self._pos(150, 120)

        self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_repeated_lagging_updates_keep_being_rejected(self) -> None:
        """A retransmitting server may deliver the pre-move position more
        than once; every duplicate stays dropped."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)

        for _ in range(3):
            self._pos(150, 120)
            self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_the_echo_confirms_then_a_lagging_position_is_still_stale(self) -> None:
        """The move's own echo arrives first; an older queued position must
        not win afterwards either."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self._pos(10, 20)  # echo: move confirmed
        self.assertEqual((self.client.x, self.client.y), (10, 20))

        self._pos(150, 120)  # late state sampled before the move

        self.assertEqual((self.client.x, self.client.y), (10, 20))

    def test_a_genuine_external_move_is_taken_while_a_move_is_pending(self) -> None:
        """Someone (or the desktop itself) moving the pointer to a position
        the server never reported before is real motion, not an echo, even
        while our move is unacknowledged."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)

        self._pos(300, 300)

        self.assertEqual((self.client.x, self.client.y), (300, 300))

    def test_the_late_echo_of_a_superseded_local_move_is_dropped(self) -> None:
        """After an external move takes over, the echo of our own move that
        finally shows up must not drag the pointer back."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self._pos(300, 300)  # external motion wins
        self.assertEqual((self.client.x, self.client.y), (300, 300))

        self._pos(10, 20)  # our move's echo, delivered late

        self.assertEqual((self.client.x, self.client.y), (300, 300))

    def test_repeated_external_position_does_not_unbury_a_late_echo(self) -> None:
        """An external move wins; the server repeating that same position
        is not a new barrier and must not let our superseded echo win when
        it finally arrives."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self._pos(300, 300)  # external motion
        self._pos(300, 300)  # retransmit of the current position
        self._pos(10, 20)    # our echo, late

        self.assertEqual((self.client.x, self.client.y), (300, 300))

    def test_two_rapid_moves_an_older_echo_cannot_stick(self) -> None:
        """Two moves sent back to back: the older echo arriving first must
        not leave the cursor at the intermediate position."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self.client.mouseMove(30, 40)

        self._pos(10, 20)  # first move's echo
        self.assertEqual((self.client.x, self.client.y), (30, 40))
        self._pos(30, 40)  # second move's echo
        self.assertEqual((self.client.x, self.client.y), (30, 40))

    def test_coalesced_moves_the_skipped_echo_cannot_arrive_late(self) -> None:
        """The server may answer both moves with only the newest position;
        an echo of the skipped intermediate position arriving afterwards is
        still stale."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self.client.mouseMove(30, 40)
        self._pos(30, 40)  # only the newest move echoed
        self.assertEqual((self.client.x, self.client.y), (30, 40))

        self._pos(10, 20)  # server finally re-reports the intermediate point

        self.assertEqual((self.client.x, self.client.y), (30, 40))

    def test_life_returns_to_normal_after_an_echo_is_consumed(self) -> None:
        """The fence must not trap the cursor: after a stale echo is
        consumed, the pointer following a later real move is tracked."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self._pos(10, 20)
        self._pos(150, 120)  # consumed as stale once
        self.assertEqual((self.client.x, self.client.y), (10, 20))

        self.client.mouseMove(50, 60)
        self._pos(50, 60)
        self._pos(150, 120)  # genuinely reported again after the new round trip
        self.assertEqual((self.client.x, self.client.y), (150, 120))

    def test_reconnect_clears_the_fence(self) -> None:
        """A reset connection starts a new epoch: a position buried by the
        old connection must be accepted as fresh server state after
        vncConnectionMade runs again."""
        self._pos(150, 120)
        self.client.mouseMove(10, 20)
        self._pos(150, 120)  # stale on this connection
        self.assertEqual((self.client.x, self.client.y), (10, 20))

        # Reconnect: a new RFBClient would be built; vncConnectionMade is
        # what clears the fence for the new transport. Give the factory a
        # fresh Deferred, as a new connection would.
        from twisted.internet.defer import Deferred

        self.client.factory.deferred = Deferred()
        self.client.vncConnectionMade()
        self._pos(150, 120)

        self.assertEqual((self.client.x, self.client.y), (150, 120))


class TestPointerGuard(unittest.TestCase):
    """Timestamp and timeout semantics with a controllable clock."""

    def test_out_of_order_events_are_rejected_by_the_water_mark(self) -> None:
        from vncdotool.client import _PointerGuard

        now = [1000.0]
        guard = _PointerGuard(clock=lambda: now[0])

        self.assertTrue(guard.is_current(1, 1, timestamp=100.0))
        self.assertTrue(guard.is_current(2, 2, timestamp=200.0))
        # An event stamped earlier than what was already applied, delivered
        # late by a re-ordering queue.
        self.assertFalse(guard.is_current(3, 3, timestamp=150.0))

    def test_equal_timestamps_first_writer_wins(self) -> None:
        from vncdotool.client import _PointerGuard

        guard = _PointerGuard(clock=lambda: 1000.0)

        self.assertTrue(guard.is_current(1, 1, timestamp=100.0))
        # A replayed event carrying the identical timestamp and a different
        # position must not overwrite the first.
        self.assertFalse(guard.is_current(9, 9, timestamp=100.0))

    def test_equal_timestamp_still_confirms_the_newest_local_move(self) -> None:
        from vncdotool.client import _PointerGuard

        guard = _PointerGuard(clock=lambda: 1000.0)
        self.assertTrue(guard.is_current(1, 1, timestamp=100.0))
        guard.local_move(5, 5)

        # The confirmation must win despite sharing the water-mark instant.
        self.assertTrue(guard.is_current(5, 5, timestamp=100.0))

    def test_a_move_unacknowledged_past_the_timeout_self_confirms(self) -> None:
        from vncdotool.client import _PointerGuard

        clock = [0.0]
        guard = _PointerGuard(clock=lambda: clock[0])
        guard.local_move(10, 20)

        # Well past ECHO_TIMEOUT with no echo: new server positions are real.
        clock[0] = 31.0
        self.assertTrue(guard.is_current(50, 60))
        # And the move's echo arriving just after the timeout is still
        # dropped the one time.
        self.assertFalse(guard.is_current(10, 20))

    def test_a_buried_position_recovers_after_the_ambiguity_window(self) -> None:
        """The conservative graveyard must not freeze a coordinate forever:
        once GRAVEYARD_TTL passes, a pointer genuinely moved back to the old
        position is accepted again."""
        from vncdotool.client import _PointerGuard

        clock = [0.0]
        guard = _PointerGuard(clock=lambda: clock[0])
        self.assertTrue(guard.is_current(150, 120, timestamp=0.0))
        guard.local_move(10, 20)
        self.assertTrue(guard.is_current(10, 20, timestamp=1.0))  # echo
        self.assertFalse(guard.is_current(150, 120, timestamp=2.0))  # buried

        # A whole ambiguity window later, returning there is real again.
        clock[0] = 33.0
        self.assertTrue(guard.is_current(150, 120, timestamp=33.0))

    def test_reset_forgets_pending_moves_and_graveyard(self) -> None:
        from vncdotool.client import _PointerGuard

        guard = _PointerGuard(clock=lambda: 1000.0)
        self.assertTrue(guard.is_current(150, 120))  # server's last position
        guard.local_move(10, 20)
        self.assertFalse(guard.is_current(150, 120))  # lagging old state
        self.assertTrue(guard.is_current(90, 90))     # someone else moved it
        self.assertFalse(guard.is_current(10, 20))    # our echo, late
        guard.reset()

        # Fresh epoch: both buried positions are new information again.
        self.assertTrue(guard.is_current(150, 120))
        self.assertTrue(guard.is_current(10, 20, timestamp=1001.0))


if __name__ == "__main__":
    unittest.main()
