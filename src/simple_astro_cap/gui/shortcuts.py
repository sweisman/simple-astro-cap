"""Keyboard shortcut definitions and registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    key: str
    description: str


# Navigation
FOCUS_EXPOSURE = Shortcut("X", "Focus exposure")
FOCUS_GAIN = Shortcut("G", "Focus gain")
FOCUS_ZOOM = Shortcut("Z", "Focus zoom")
FOCUS_BRIGHTNESS = Shortcut("B", "Focus brightness")
FOCUS_CONTRAST = Shortcut("C", "Focus contrast")
NAV_UP = Shortcut("Up", "Previous control")
NAV_DOWN = Shortcut("Down", "Next control")
ADJUST_LEFT = Shortcut("Left", "Decrease / previous")
ADJUST_RIGHT = Shortcut("Right", "Increase / next")

# Actions
CAPTURE_SINGLE = Shortcut("Space", "Capture single frame")
TOGGLE_RECORDING = Shortcut("R", "Start/stop recording")

# Modifiers
TOGGLE_AUTO_EXPOSURE = Shortcut("Ctrl+X", "Toggle auto-exposure")
TOGGLE_AUTO_GAIN = Shortcut("Ctrl+G", "Toggle auto-gain")
QUIT = Shortcut("Ctrl+Q", "Quit")
