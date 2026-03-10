"""Simple frame harness — camera worker thread dispatches to consumers."""

from __future__ import annotations

import logging
import threading

from typing import Callable

from simple_astro_cap.camera.abc import CameraBase, Frame

from .abc import FrameConsumer, FrameProducer

log = logging.getLogger(__name__)

FrameTransform = Callable[[Frame], Frame]


class SimpleHarness(FrameProducer):
    """Single-threaded-consumer pipeline for initial development.

    A worker thread polls the camera and dispatches frames to all
    registered consumers. No ring buffer, no zero-copy — just
    straightforward polling with numpy copies (done in the camera backend).
    """

    def __init__(self, camera: CameraBase):
        self._camera = camera
        self._consumers: list[FrameConsumer] = []
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._worker: threading.Thread | None = None
        self._transform: FrameTransform | None = None

    @property
    def frame_transform(self) -> FrameTransform | None:
        return self._transform

    @frame_transform.setter
    def frame_transform(self, fn: FrameTransform | None) -> None:
        self._transform = fn

    @property
    def camera(self) -> CameraBase:
        return self._camera

    def add_consumer(self, consumer: FrameConsumer) -> None:
        with self._lock:
            if consumer not in self._consumers:
                self._consumers.append(consumer)

    def remove_consumer(self, consumer: FrameConsumer) -> None:
        with self._lock:
            try:
                self._consumers.remove(consumer)
            except ValueError:
                pass

    def start(self) -> None:
        if self._running.is_set():
            return
        self._camera.start_live()
        self._running.set()
        self._worker = threading.Thread(target=self._run, name="frame-harness", daemon=True)
        self._worker.start()
        log.info("Simple harness started")

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None
        self._camera.stop_live()
        log.info("Simple harness stopped")

    def is_running(self) -> bool:
        return self._running.is_set()

    def _run(self) -> None:
        try:
            while self._running.is_set():
                frame = self._camera.get_live_frame(timeout_ms=500)
                if frame is None:
                    continue
                if self._transform is not None:
                    frame = self._transform(frame)
                with self._lock:
                    consumers = list(self._consumers)
                for consumer in consumers:
                    try:
                        consumer.on_frame(frame)
                    except Exception:
                        log.exception("Consumer %s failed on frame %d", consumer, frame.sequence)
        except Exception:
            log.exception("Frame worker thread crashed")
