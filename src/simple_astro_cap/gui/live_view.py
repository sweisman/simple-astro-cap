"""Live camera view widget with scroll support."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QScrollArea, QWidget

from simple_astro_cap.camera.abc import Frame


def compute_zoom_steps(
    image_w: int, image_h: int, viewport_w: int, viewport_h: int, steps: int = 5,
) -> list[tuple[str, float | None]]:
    """Compute zoom levels from fit-to-viewport up to 100%.

    Returns a list of (label, scale) tuples.  The first entry is always
    ("Fit", None).  Subsequent entries are evenly spaced percentages
    between the fit scale and 100%.  If the fit scale is already >= 100%,
    only Fit and 100% are returned.
    """
    if image_w <= 0 or image_h <= 0 or viewport_w <= 0 or viewport_h <= 0:
        return [("Fit", None), ("100%", 1.0)]

    fit_scale = min(viewport_w / image_w, viewport_h / image_h)

    if fit_scale >= 1.0:
        # Image fits at native size — only offer Fit and 100%
        return [("Fit", None), ("100%", 1.0)]

    result: list[tuple[str, float | None]] = [("Fit", None)]

    # Evenly spaced from just above fit_scale to 1.0 (inclusive), `steps` levels
    seen_pcts: set[int] = set()
    for i in range(1, steps + 1):
        scale = fit_scale + (1.0 - fit_scale) * i / steps
        pct = round(scale * 100)
        if pct not in seen_pcts:
            seen_pcts.add(pct)
            result.append((f"{pct}%", scale))

    return result


class _ImageWidget(QWidget):
    """Inner widget that renders the pixmap at a given scale."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._scale: float | None = None  # None = fit to parent
        self.setStyleSheet("background-color: black;")

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._update_size()
        self.update()

    def set_scale(self, scale: float | None) -> None:
        self._scale = scale
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        if self._pixmap is None or self._scale is None:
            return
        w = int(self._pixmap.width() * self._scale)
        h = int(self._pixmap.height() * self._scale)
        self.setFixedSize(w, h)

    def paintEvent(self, event: object) -> None:
        if self._pixmap is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pm = self._pixmap

        if self._scale is None:
            scaled = pm.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            scaled = pm.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)

        painter.end()


class LiveViewWidget(QScrollArea):
    """Scrollable live camera view with zoom support.

    In Fit mode, the image scales to the viewport (no scroll bars).
    In fixed zoom modes, the image may exceed the viewport and scroll bars appear.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._image_widget = _ImageWidget()
        self._scale: float | None = None  # None = fit

        self.setWidget(self._image_widget)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setStyleSheet("QScrollArea { background-color: black; border: none; }")

    @property
    def zoom_scale(self) -> float | None:
        return self._scale

    @zoom_scale.setter
    def zoom_scale(self, scale: float | None) -> None:
        self._scale = scale
        if scale is None:
            self.setWidgetResizable(False)
            self._image_widget.setFixedSize(self.viewport().size())
        else:
            self.setWidgetResizable(False)
        self._image_widget.set_scale(scale)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if self._scale is None:
            self._image_widget.setFixedSize(self.viewport().size())

    def update_frame(self, frame: Frame) -> None:
        """Convert a Frame to QPixmap and schedule repaint."""
        data = frame.data

        if frame.bit_depth > 8:
            mn, mx = int(data.min()), int(data.max())
            if mx > mn:
                data = ((data.astype(np.float32) - mn) / (mx - mn) * 255).astype(np.uint8)
            else:
                data = np.zeros_like(data, dtype=np.uint8)

        h, w = data.shape
        data = np.ascontiguousarray(data)
        qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        self._image_widget.set_pixmap(QPixmap.fromImage(qimg.copy()))
