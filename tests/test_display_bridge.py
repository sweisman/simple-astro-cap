from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from simple_astro_cap.gui.display_bridge import DisplayBridge  # noqa: E402

from .conftest import make_frame  # noqa: E402


def test_mailbox_signals_once_and_keeps_only_newest():
    bridge = DisplayBridge()
    signals: list[int] = []
    bridge.frame_ready.connect(lambda: signals.append(1))  # direct (same thread)

    for seq in range(1, 51):  # GUI "busy": nobody calls take()
        bridge.on_frame(make_frame(seq))
    assert len(signals) == 1
    assert bridge.take().sequence == 50
    assert bridge.take() is None

    bridge.on_frame(make_frame(51))
    assert len(signals) == 2


def test_snapshot_is_next_frame_after_request():
    bridge = DisplayBridge()
    snaps = []
    bridge.snapshot_ready.connect(snaps.append)
    bridge.on_frame(make_frame(1))
    bridge.request_snapshot()
    bridge.on_frame(make_frame(2))
    bridge.on_frame(make_frame(3))
    assert [f.sequence for f in snaps] == [2]
