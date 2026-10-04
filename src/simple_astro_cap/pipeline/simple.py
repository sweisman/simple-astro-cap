"""Frame harness — capture thread, bounded record queue, writer thread."""

from __future__ import annotations

import collections
import logging
import threading
import time

from simple_astro_cap.camera.abc import CameraBase, Frame

from .abc import FrameConsumer, FrameProducer

log = logging.getLogger(__name__)

DEFAULT_QUEUE_BYTES = 1024 * 1024 * 1024  # 1 GiB of frames in flight to disk

_JOIN_WARN_S = 3.0
_JOIN_GIVE_UP_S = 10.0


class SimpleHarness(FrameProducer):
    """Polls the camera on a capture thread and fans frames out.

    The capture thread does as little as possible: get a frame from the
    SDK (the backend copies it out and stamps capture time), run the
    *inline* consumers, and append it to the record queue. Inline
    consumers must be cheap and non-blocking (the display mailbox, the
    throttled soft auto-exposure).

    *Queued* consumers (recorders) are fed from a bounded queue by a
    separate writer thread, so disk stalls never stop camera polling. The
    queue is bounded by bytes; when full, the newest frame is discarded
    and counted in ``queue_overflows`` — loss is explicit, never silent.
    Backends already copy every frame out of the SDK buffer, so the queue
    simply holds references; no preallocated ring is needed.
    """

    def __init__(self, camera: CameraBase, queue_bytes: int = DEFAULT_QUEUE_BYTES):
        self._camera = camera
        self._inline: list[FrameConsumer] = []
        self._queued: list[FrameConsumer] = []
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._capture: threading.Thread | None = None
        self._writer: threading.Thread | None = None

        self._queue: collections.deque[Frame] = collections.deque()
        self._queue_cv = threading.Condition()
        self._queue_bytes = 0
        self._queue_limit = queue_bytes
        self._enqueued_total = 0    # frames ever queued (for drain())
        self._dispatched_total = 0  # frames the writer has finished with
        self.queue_overflows = 0
        self.queue_peak_bytes = 0
        self.error: BaseException | None = None

    @property
    def camera(self) -> CameraBase:
        return self._camera

    def add_consumer(self, consumer: FrameConsumer, *, queued: bool = False) -> None:
        """Register a consumer. ``queued=True`` for anything that does I/O."""
        with self._lock:
            target = self._queued if queued else self._inline
            if consumer not in target:
                target.append(consumer)

    def remove_consumer(self, consumer: FrameConsumer) -> None:
        with self._lock:
            for lst in (self._inline, self._queued):
                if consumer in lst:
                    lst.remove(consumer)

    def start(self) -> None:
        if self._running.is_set():
            return
        self.error = None
        self._camera.start_live()
        self._running.set()
        self._capture = threading.Thread(target=self._run_capture, name="frame-capture", daemon=True)
        self._writer = threading.Thread(target=self._run_writer, name="frame-writer", daemon=True)
        self._writer.start()
        self._capture.start()
        log.info("Harness started")

    def stop(self) -> None:
        if self._capture is None and self._writer is None:
            return
        self._running.clear()
        with self._queue_cv:
            self._queue_cv.notify_all()
        capture_alive = self._join(self._capture)
        # Writer finishes the queue before exiting; give it the same budget.
        self._join(self._writer)
        self._capture = self._writer = None
        if capture_alive:
            # Stopping the SDK under a thread still inside an SDK call can
            # crash the vendor library; leave it live and report instead.
            self.error = self.error or RuntimeError(
                "Capture thread did not exit; camera left running — reconnect required")
            log.error("Capture thread still alive after %.0fs; not calling stop_live()",
                      _JOIN_GIVE_UP_S)
            return
        self._camera.stop_live()
        log.info("Harness stopped")

    @staticmethod
    def _join(thread: threading.Thread | None) -> bool:
        """Join, warning after a few seconds; return True if it is still alive."""
        if thread is None:
            return False
        thread.join(timeout=_JOIN_WARN_S)
        if thread.is_alive():
            log.warning("%s still running after %.0fs; waiting", thread.name, _JOIN_WARN_S)
            thread.join(timeout=_JOIN_GIVE_UP_S - _JOIN_WARN_S)
        return thread.is_alive()

    def is_running(self) -> bool:
        return self._running.is_set()

    def queue_fill_bytes(self) -> int:
        return self._queue_bytes

    def drain(self, timeout: float = 30.0) -> int:
        """Block until every frame queued *before this call* is dispatched.

        Call before stopping a recorder so frames captured before the stop
        request still reach it. Frames captured afterwards are not waited
        for, so this terminates even while the queue is overflowing.
        Returns how many of those earlier frames were still undelivered
        when it gave up (0 on success).
        """
        deadline = time.monotonic() + timeout
        with self._queue_cv:
            target = self._enqueued_total
            while self._dispatched_total < target:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._writer is None or not self._writer.is_alive():
                    break
                self._queue_cv.wait(remaining)
            return max(0, target - self._dispatched_total)

    def _run_capture(self) -> None:
        try:
            while self._running.is_set():
                frame = self._camera.get_live_frame(timeout_ms=500)
                if frame is None:
                    continue
                with self._lock:
                    inline = list(self._inline)
                    has_queued = bool(self._queued)
                for consumer in inline:
                    try:
                        consumer.on_frame(frame)
                    except Exception:
                        log.exception("Consumer %s failed on frame %d", consumer, frame.sequence)
                if has_queued:
                    self._enqueue(frame)
        except Exception as exc:
            log.exception("Frame capture thread crashed")
            self.error = exc
        finally:
            self._running.clear()
            with self._queue_cv:
                self._queue_cv.notify_all()

    def _enqueue(self, frame: Frame) -> None:
        nbytes = frame.data.nbytes
        with self._queue_cv:
            if self._queue_bytes + nbytes > self._queue_limit:
                self.queue_overflows += 1
                if self.queue_overflows == 1 or self.queue_overflows % 100 == 0:
                    log.warning("Record queue full (%d MB); dropped frame %d (%d total)",
                                self._queue_bytes // (1024 * 1024), frame.sequence,
                                self.queue_overflows)
                return
            self._queue.append(frame)
            self._queue_bytes += nbytes
            self._enqueued_total += 1
            self.queue_peak_bytes = max(self.queue_peak_bytes, self._queue_bytes)
            self._queue_cv.notify_all()

    def _run_writer(self) -> None:
        while True:
            with self._queue_cv:
                while not self._queue and self._running.is_set():
                    self._queue_cv.wait()
                if not self._queue:
                    self._queue_cv.notify_all()
                    return  # stopped and drained
                frame = self._queue.popleft()
                self._queue_bytes -= frame.data.nbytes
            try:
                with self._lock:
                    queued = list(self._queued)
                for consumer in queued:
                    try:
                        consumer.on_frame(frame)
                    except Exception:
                        log.exception("Consumer %s failed on frame %d", consumer, frame.sequence)
            finally:
                with self._queue_cv:
                    self._dispatched_total += 1
                    self._queue_cv.notify_all()
