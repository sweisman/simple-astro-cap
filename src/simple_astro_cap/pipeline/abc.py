"""Pipeline abstract interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod

from simple_astro_cap.camera.abc import Frame


class FrameConsumer(ABC):
    """Receives frames from the pipeline."""

    @abstractmethod
    def on_frame(self, frame: Frame) -> None: ...


class FrameProducer(ABC):
    """Produces frames from a camera into the pipeline."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def add_consumer(self, consumer: FrameConsumer) -> None: ...

    @abstractmethod
    def remove_consumer(self, consumer: FrameConsumer) -> None: ...
