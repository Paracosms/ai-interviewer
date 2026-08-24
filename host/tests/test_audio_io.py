import asyncio

import pytest
import sounddevice

from interviewer.audio_io import AudioError, AudioIO, PcmPlaybackBuffer


def test_playback_buffer_is_bounded_and_reads_fifo() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=4)
    buffer.append(b"1234")
    buffer.append(b"56")
    assert len(buffer) == 2
    assert buffer.read(4) == b"56"
    assert buffer.read(4) == b""


def test_playback_buffer_clear_discards_queued_audio() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=16)
    buffer.append(b"audio")
    buffer.clear()
    assert buffer.read(16) == b""


def test_input_queue_drops_oldest_block_when_full() -> None:
    audio = AudioIO(input_queue_size=1)
    audio._accept_input = True
    audio._enqueue_input(b"old")
    audio._enqueue_input(b"new")
    assert asyncio.run(audio.read_microphone()) == b"new"


def test_output_callback_fills_underflow_with_silence() -> None:
    audio = AudioIO(output_buffer_bytes=32)
    output = bytearray(b"x" * 8)
    audio._output_callback(output, 4, None, None)
    assert output == b"\x00" * 8


def test_output_callback_consumes_model_pcm() -> None:
    audio = AudioIO(output_buffer_bytes=32)
    audio.write_model_audio(b"1234")
    output = bytearray(b"x" * 8)
    audio._output_callback(output, 4, None, None)
    assert output == b"1234\x00\x00\x00\x00"


def test_microphone_failure_is_actionable_and_does_not_leave_audio_running(monkeypatch) -> None:
    def fail_open(**kwargs):
        del kwargs
        raise RuntimeError("no microphone")

    monkeypatch.setattr(sounddevice, "RawInputStream", fail_open)
    audio = AudioIO()

    async def start_audio() -> None:
        audio.start()

    with pytest.raises(AudioError, match="Could not open the configured microphone"):
        asyncio.run(start_audio())
    assert audio.running is False
