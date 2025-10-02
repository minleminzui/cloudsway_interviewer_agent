from __future__ import annotations

import math
import struct
from typing import Iterable

SAMPLE_RATE = 16000


def _generate_wave(samples: Iterable[float]) -> bytes:
    frames = bytearray()
    for sample in samples:
        clipped = max(-1.0, min(1.0, sample))
        frames.extend(struct.pack('<h', int(clipped * 32767)))
    return bytes(frames)


def synthesize(text: str) -> bytes:
    """Generate a simple sine wave payload to stand in for TTS audio."""
    duration_seconds = max(1.0, min(3.0, len(text) / 12))
    total_samples = int(SAMPLE_RATE * duration_seconds)
    frequency = 440 + (len(text) % 5) * 110
    samples = (
        math.sin(2 * math.pi * frequency * (i / SAMPLE_RATE)) * 0.3
        for i in range(total_samples)
    )
    return _generate_wave(samples)
