from __future__ import annotations

import threading
import time

from simple_astro_cap.pipeline.abc import FrameConsumer
from simple_astro_cap.pipeline.simple import SimpleHarness

from .conftest import make_frame


class FakeCamera:
    """Produces numbered frames as fast as polled, up to ``total``."""

    def __init__(self, total: int):
        self.total = total
        self.seq = 0
        self.live = False
        self.polls_done = threading.Event()

    def start_live(self):
        self.live = True

    def stop_live(self):
        self.live = False

    def get_live_frame(self, timeout_ms=500):
        if self.seq >= self.total:
            self.polls_done.set()
            time.sleep(0.005)
            return None
        self.seq += 1
        return make_frame(self.seq, w=64, h=64, bits=16)  # 8 KiB each


class Collect(FrameConsumer):
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.seqs: list[int] = []

    def on_frame(self, frame):
        if self.delay:
            time.sleep(self.delay)
        self.seqs.append(frame.sequence)


def test_slow_recorder_never_stalls_capture_and_overflow_is_counted():
    cam = FakeCamera(total=200)
    harness = SimpleHarness(cam, queue_bytes=10 * 64 * 64 * 2)  # room for 10 frames
    inline, slow = Collect(), Collect(delay=0.02)
    harness.add_consumer(inline)
    harness.add_consumer(slow, queued=True)
    harness.start()
    # 200 frames through a 20 ms/frame writer would take 4 s if capture blocked.
    assert cam.polls_done.wait(1.0), "capture thread was blocked by the recorder"
    assert inline.seqs == list(range(1, 201))  # inline path sees every frame
    assert harness.drain(timeout=5.0)
    harness.stop()
    assert harness.queue_overflows > 0
    # Every frame is either written or counted as overflow — nothing silent.
    assert len(slow.seqs) + harness.queue_overflows == 200
    assert slow.seqs == sorted(slow.seqs)


def test_stop_flushes_queued_frames_to_recorder():
    cam = FakeCamera(total=30)
    harness = SimpleHarness(cam)
    rec = Collect(delay=0.005)
    harness.add_consumer(rec, queued=True)
    harness.start()
    assert cam.polls_done.wait(1.0)
    harness.stop()
    assert rec.seqs == list(range(1, 31))
    assert harness.queue_overflows == 0


def test_capture_crash_clears_running_and_reports_error():
    class Boom(FakeCamera):
        def get_live_frame(self, timeout_ms=500):
            raise RuntimeError("usb gone")

    harness = SimpleHarness(Boom(total=1))
    harness.start()
    deadline = time.monotonic() + 2
    while harness.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not harness.is_running()
    assert isinstance(harness.error, RuntimeError)
    harness.stop()
