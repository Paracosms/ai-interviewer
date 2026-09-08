"""Local voice activity detector using webrtcvad with typing-aware hangover extension."""

from __future__ import annotations

from collections import deque
from typing import Literal

import webrtcvad

VadEventType = Literal["activity_start", "audio", "activity_end"]
VadEvent = tuple[VadEventType, bytes | None]


class LocalVoiceActivityDetector:
    """Classify 16kHz PCM audio frames and manage speech endpoint events."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        frame_duration_ms: int = 20,
        vad_mode: int = 2,
        pre_roll_ms: int = 300,
        normal_silence_ms: int = 1200,
        typing_silence_ms: int = 2500,
    ) -> None:
        if frame_duration_ms not in (10, 20, 30):
            raise ValueError("frame_duration_ms must be 10, 20, or 30.")
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.bytes_per_frame = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
        self.vad_mode = vad_mode
        self._vad = webrtcvad.Vad(vad_mode)

        self.pre_roll_frames = max(1, pre_roll_ms // frame_duration_ms)
        self.normal_silence_frames = max(1, normal_silence_ms // frame_duration_ms)
        self.typing_silence_frames = max(1, typing_silence_ms // frame_duration_ms)

        self._pre_roll: deque[bytes] = deque(maxlen=self.pre_roll_frames)
        self._recent_window: deque[bool] = deque(maxlen=3)
        self._in_speech = False
        self._consecutive_unvoiced = 0
        self._consecutive_voiced = 0
        self._speech_frames = 0
        self._remainder = b""

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        """Clear all active audio state and buffers."""
        self._in_speech = False
        self._consecutive_unvoiced = 0
        self._consecutive_voiced = 0
        self._speech_frames = 0
        self._pre_roll.clear()
        self._recent_window.clear()
        self._remainder = b""

    def process_chunk(self, chunk: bytes, *, typing_active: bool = False) -> list[VadEvent]:
        """Process incoming PCM audio bytes and return classified speech events."""
        data = self._remainder + chunk
        frame_size = self.bytes_per_frame
        num_frames = len(data) // frame_size
        self._remainder = data[num_frames * frame_size:]

        events: list[VadEvent] = []
        silence_limit = (
            self.typing_silence_frames if typing_active else self.normal_silence_frames
        )

        for i in range(num_frames):
            frame = data[i * frame_size : (i + 1) * frame_size]
            is_voiced = False if not any(frame) else self._vad.is_speech(frame, self.sample_rate)
            self._recent_window.append(is_voiced)

            if not self._in_speech:
                self._pre_roll.append(frame)
                # Trigger speech start on at least 2 voiced frames in a 3-frame window
                if sum(self._recent_window) >= 2:
                    self._in_speech = True
                    self._consecutive_unvoiced = 0
                    self._consecutive_voiced = 2
                    self._speech_frames = 0
                    events.append(("activity_start", None))
                    # Flush pre-roll buffer before current frame
                    pre_roll_bytes = b"".join(self._pre_roll)
                    if pre_roll_bytes:
                        events.append(("audio", pre_roll_bytes))
                    self._pre_roll.clear()
            else:
                events.append(("audio", frame))
                self._speech_frames += 1
                if is_voiced:
                    self._consecutive_voiced += 1
                    if self._consecutive_voiced >= 2:
                        self._consecutive_unvoiced = 0
                else:
                    self._consecutive_voiced = 0
                    self._consecutive_unvoiced += 1
                    max_speech_frames = int(15000 / self.frame_duration_ms)
                    force_end = (
                        self._speech_frames >= max_speech_frames
                        and self._consecutive_unvoiced >= max(1, silence_limit // 2)
                    )
                    if self._consecutive_unvoiced >= silence_limit or force_end:
                        self._in_speech = False
                        self._consecutive_unvoiced = 0
                        self._consecutive_voiced = 0
                        self._speech_frames = 0
                        events.append(("activity_end", None))

        return events
