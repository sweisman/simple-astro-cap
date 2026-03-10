"""Histogram widget for displaying frame brightness distribution."""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QSizePolicy


class HistogramWidget(QWidget):
    """Minimal histogram widget drawn with QPainter.

    Displays a 256-bin brightness histogram for uint8 or uint16 frames.
    Designed to be called every frame when enabled.
    """

    _BG = QColor(0, 0, 0)
    _FG = QColor(220, 220, 220)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._bins: np.ndarray | None = None

    # ------------------------------------------------------------------
    def update_histogram(self, frame_data: np.ndarray | None) -> None:
        """Compute histogram from a 2-D array and schedule a repaint."""
        if frame_data is None or frame_data.size == 0:
            self._bins = None
            self.update()
            return

        if frame_data.dtype == np.uint8:
            counts = np.bincount(frame_data.ravel(), minlength=256)
        else:
            counts, _ = np.histogram(frame_data.ravel(), bins=256,
                                     range=(0, np.iinfo(frame_data.dtype).max))

        # Skip bin 0 for normalisation so a large black surround doesn't
        # squash the rest of the histogram into invisibility.
        peak = counts[1:].max() if counts[1:].max() > 0 else 1
        self._bins = counts.astype(np.float64) / peak
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self._BG)

        bins = self._bins
        if bins is None:
            p.end()
            return

        w = self.width()
        h = self.height()
        n = len(bins)  # 256

        # Width of each logical bar in pixels (float for precision).
        bar_w = w / n

        p.setPen(Qt.NoPen)
        p.setBrush(self._FG)

        for i in range(n):
            bar_h = bins[i] * h
            if bar_h < 0.5:
                continue
            x = int(i * bar_w)
            x_next = int((i + 1) * bar_w)
            p.drawRect(x, int(h - bar_h), x_next - x, int(bar_h))

        p.end()
