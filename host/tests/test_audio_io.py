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


def test_default_playback_buffer_never_discards_queued_audio() -> None:
    buffer = PcmPlaybackBuffer()
    first = b"a" * (4 * 24_000 * 2)
    second = b"complete-next-word"
    buffer.append(first)
    buffer.append(second)
    assert len(buffer) == len(first) + len(second)
    assert buffer.read(len(first) + len(second)) == first + second


def test_playback_buffer_clear_discards_queued_audio() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=16)
    buffer.append(b"audio")
    buffer.clear()
    assert buffer.read(16) == b""


def test_playback_buffer_prebuffers_to_hide_network_jitter() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=32, prebuffer_bytes=8)
    buffer.append(b"1234")
    assert buffer.read(4) == b""
    buffer.append(b"5678")
    assert buffer.read(4) == b"1234"
    assert buffer.read(4) == b"5678"


def test_playback_buffer_rebuffers_instead_of_playing_a_short_fragment() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=32, prebuffer_bytes=8)
    buffer.append(b"12345678")
    assert buffer.read(4) == b"1234"
    assert buffer.read(8) == b""
    buffer.append(b"90ab")
    assert buffer.read(4) == b"5678"


def test_playback_buffer_drains_short_tail_when_turn_finishes() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=32, prebuffer_bytes=8)
    buffer.append(b"1234")
    buffer.finish_turn()
    assert buffer.read(8) == b"1234"


def test_empty_turn_does_not_disable_prebuffering_for_next_turn() -> None:
    buffer = PcmPlaybackBuffer(max_bytes=32, prebuffer_bytes=8)
    buffer.finish_turn()
    buffer.append(b"1234")
    assert buffer.read(4) == b""


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
    audio.finish_model_turn()
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
