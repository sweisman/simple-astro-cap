"""Exposure time unit conversion."""

from __future__ import annotations

from enum import Enum


class ExposureUnit(Enum):
    MICROSECONDS = ("us", 1.0)
    MILLISECONDS = ("ms", 1000.0)
    SECONDS = ("s", 1_000_000.0)

    def __init__(self, label: str, factor: float):
        self.label = label
        self.factor = factor

    def to_us(self, value: float) -> float:
        """Convert from this unit to microseconds."""
        return value * self.factor

    def from_us(self, us: float) -> float:
        """Convert from microseconds to this unit."""
        return us / self.factor

    @classmethod
    def from_label(cls, label: str) -> ExposureUnit:
        for unit in cls:
            if unit.label == label:
                return unit
        raise ValueError(f"Unknown exposure unit: {label}")
