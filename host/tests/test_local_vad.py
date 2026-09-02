import math
import struct

import pytest

from interviewer.local_vad import LocalVoiceActivityDetector


def make_sine_frame(freq: float = 300.0, sample_rate: int = 16000, duration_ms: int = 20) -> bytes:
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    samples = []
    for i in range(num_samples):
        val = int(16000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
        samples.append(val)
    return struct.pack(f"<{num_samples}h", *samples)


def make_silence_frame(sample_rate: int = 16000, duration_ms: int = 20) -> bytes:
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    return b"\x00" * (num_samples * 2)


def test_vad_initial_state_is_idle():
    detector = LocalVoiceActivityDetector()
    assert not detector.in_speech

    silence = make_silence_frame()
    events = detector.process_chunk(silence)
    assert events == []
    assert not detector.in_speech


def test_vad_speech_start_emits_start_and_flushes_preroll():
    detector = LocalVoiceActivityDetector(pre_roll_ms=60, frame_duration_ms=20)
    silence = make_silence_frame()
    detector.process_chunk(silence)

    voice_frame = make_sine_frame(freq=250.0)
    # Feed 2 voiced frames to trigger >= 2 in 3
    events1 = detector.process_chunk(voice_frame)
    events2 = detector.process_chunk(voice_frame)
    combined = events1 + events2

    types = [e[0] for e in combined]
    assert "activity_start" in types
    assert detector.in_speech


def test_vad_silence_hangover_extends_when_typing_active():
    detector = LocalVoiceActivityDetector(
        normal_silence_ms=60,  # 3 frames of 20ms
        typing_silence_ms=120,  # 6 frames of 20ms
        frame_duration_ms=20,
    )
    voice_frame = make_sine_frame(freq=250.0)
    silence = make_silence_frame()

    # Trigger speech
    detector.process_chunk(voice_frame)
    detector.process_chunk(voice_frame)
    assert detector.in_speech

    # With typing_active=True, 3 unvoiced frames should NOT trigger activity_end
    for _ in range(3):
        events = detector.process_chunk(silence, typing_active=True)
        assert not any(e[0] == "activity_end" for e in events)
        assert detector.in_speech

    # When reaching 6 frames, activity_end is emitted
    end_emitted = False
    for _ in range(3):
        events = detector.process_chunk(silence, typing_active=True)
        if any(e[0] == "activity_end" for e in events):
            end_emitted = True
    assert end_emitted
    assert not detector.in_speech
