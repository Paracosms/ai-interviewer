"""Realtime Windows audio plumbing for Gemini Live PCM input and output."""

from __future__ import annotations

import asyncio
import math
import struct
import threading
import time
from collections import deque
from typing import Any

import sounddevice as sounddevice

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "int16"
INPUT_BLOCK_MS = 80
INPUT_BLOCK_FRAMES = INPUT_SAMPLE_RATE * INPUT_BLOCK_MS // 1_000
OUTPUT_BLOCK_MS = 20
OUTPUT_BLOCK_FRAMES = OUTPUT_SAMPLE_RATE * OUTPUT_BLOCK_MS // 1_000
OUTPUT_PREBUFFER_MS = 120
OUTPUT_PREBUFFER_BYTES = OUTPUT_SAMPLE_RATE * 2 * OUTPUT_PREBUFFER_MS // 1_000
PLAYBACK_MICROPHONE_TAIL_SECONDS = 0.3


class AudioError(RuntimeError):
    """Raised when a configured Windows audio device cannot be opened."""


def _validate_volume(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Volume must be a finite number between 0 and 1.")
    if not 0 <= value <= 1:
        raise ValueError("Volume must be between 0 and 1.")
    return float(value)


def _scale_pcm16(data: bytes, volume: float) -> bytes:
    """Apply a linear gain to little-endian signed 16-bit mono PCM."""

    if volume >= 1:
        return data
    if volume <= 0:
        return b"\x00" * len(data)
    sample_bytes = len(data) - (len(data) % 2)
    if not sample_bytes:
        return data
    samples = struct.unpack(f"<{sample_bytes // 2}h", data[:sample_bytes])
    scaled = b"".join(struct.pack("<h", int(sample * volume)) for sample in samples)
    return scaled + data[sample_bytes:]


def _device_value(value: str | None) -> str | int | None:
    """Pass numeric device IDs as integers and named devices as strings."""

    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if text.isdecimal():
        return int(text)
    return text


class PcmPlaybackBuffer:
    """Lossless PCM jitter buffer consumed by PortAudio's callback.

    Live audio can arrive faster than the sound device consumes it. Production
    playback therefore has no size cap: discarding old PCM corrupts speech and
    commonly cuts through a word. A limit remains available to callers that
    explicitly need a bounded buffer.
    """

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        prebuffer_bytes: int = 0,
    ) -> None:
        self.max_bytes = None if max_bytes is None else max(1, int(max_bytes))
        requested_prebuffer = max(0, int(prebuffer_bytes))
        self.prebuffer_bytes = (
            requested_prebuffer
            if self.max_bytes is None
            else min(self.max_bytes, requested_prebuffer)
        )
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._playing = self.prebuffer_bytes == 0
        self._turn_complete = False
        self._held = False
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        chunk = bytes(data)
        if self.max_bytes is not None and len(chunk) > self.max_bytes:
            chunk = chunk[-self.max_bytes :]
        with self._lock:
            if self.max_bytes is not None:
                while self._chunks and self._size + len(chunk) > self.max_bytes:
                    self._size -= len(self._chunks.popleft())
            if self.max_bytes is None or self._size + len(chunk) <= self.max_bytes:
                self._chunks.append(chunk)
                self._size += len(chunk)

    def read(self, size: int) -> bytes:
        requested = max(0, int(size))
        if requested == 0:
            return b""
        with self._lock:
            if self._held:
                return b""
            if not self._playing:
                if self._size >= self.prebuffer_bytes or (
                    self._turn_complete and self._size > 0
                ):
                    self._playing = True
                else:
                    return b""

            # A network gap should pause at a callback boundary and rebuffer,
            # rather than play a tiny fragment followed by audible silence.
            if (
                self.prebuffer_bytes > 0
                and self._size < requested
                and not self._turn_complete
            ):
                self._playing = False
                return b""

            result = bytearray()
            while self._chunks and len(result) < requested:
                chunk = self._chunks.popleft()
                needed = requested - len(result)
                if len(chunk) <= needed:
                    result.extend(chunk)
                    self._size -= len(chunk)
                else:
                    result.extend(chunk[:needed])
                    remainder = chunk[needed:]
                    self._chunks.appendleft(remainder)
                    self._size -= needed
            if self._size == 0 and self._turn_complete:
                self._turn_complete = False
                self._playing = self.prebuffer_bytes == 0
            return bytes(result)

    def finish_turn(self) -> None:
        """Allow a final short tail to drain without waiting for prebuffering."""

        with self._lock:
            self._turn_complete = self._size > 0
            if not self._turn_complete:
                self._playing = self.prebuffer_bytes == 0

    def hold(self) -> None:
        with self._lock:
            self._held = True

    def release(self) -> None:
        with self._lock:
            self._held = False

    @property
    def held(self) -> bool:
        with self._lock:
            return self._held

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0
            self._playing = self.prebuffer_bytes == 0
            self._turn_complete = False
            self._held = False

    def __len__(self) -> int:
        with self._lock:
            return self._size


class AudioIO:
    """Own one raw input stream, one raw output stream, and their queues."""

    def __init__(
        self,
        *,
        input_device: str | None = None,
        output_device: str | None = None,
        input_queue_size: int = 80,
        output_buffer_bytes: int | None = None,
        volume: float = 1.0,
        clock=time.monotonic,
        microphone_tail_seconds: float = PLAYBACK_MICROPHONE_TAIL_SECONDS,
    ) -> None:
        self.input_device = _device_value(input_device)
        self.output_device = _device_value(output_device)
        self.input_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=input_queue_size)
        self.output_buffer = PcmPlaybackBuffer(
            max_bytes=output_buffer_bytes,
            prebuffer_bytes=OUTPUT_PREBUFFER_BYTES,
        )
        self._volume = _validate_volume(volume)
        self._volume_lock = threading.Lock()
        self._clock = clock
        self._microphone_tail_seconds = max(0.0, float(microphone_tail_seconds))
        self._input_suppression_lock = threading.Lock()
        self._suppress_input_until = 0.0
        self._suppressed_input_blocks = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._input_stream: Any = None
        self._output_stream: Any = None
        self._accept_input = False

    @property
    def running(self) -> bool:
        return self._input_stream is not None or self._output_stream is not None

    @property
    def volume(self) -> float:
        with self._volume_lock:
            return self._volume

    def set_volume(self, value: float) -> None:
        with self._volume_lock:
            self._volume = _validate_volume(value)

    @property
    def output_held(self) -> bool:
        return self.output_buffer.held

    @property
    def suppressed_input_blocks(self) -> int:
        with self._input_suppression_lock:
            return self._suppressed_input_blocks

    def hold_model_output(self) -> None:
        self.output_buffer.hold()

    def release_model_output(self) -> None:
        self.output_buffer.release()

    def should_forward_microphone(self) -> bool:
        with self._input_suppression_lock:
            return self._clock() >= self._suppress_input_until

    def _mark_model_playback(self) -> None:
        now = self._clock()
        with self._input_suppression_lock:
            was_suppressed = now < self._suppress_input_until
            self._suppress_input_until = max(
                self._suppress_input_until,
                now + self._microphone_tail_seconds,
            )
        if not was_suppressed and self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._flush_input_queue)

    def _record_suppressed_input(self) -> None:
        with self._input_suppression_lock:
            self._suppressed_input_blocks += 1

    def _flush_input_queue(self) -> None:
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def start(self) -> None:
        """Open both streams, failing before a Gemini session is connected."""

        if self.running:
            return
        self._loop = asyncio.get_running_loop()
        self._accept_input = True
        try:
            self._input_stream = sounddevice.RawInputStream(
                samplerate=INPUT_SAMPLE_RATE,
                blocksize=INPUT_BLOCK_FRAMES,
                channels=AUDIO_CHANNELS,
                dtype=AUDIO_DTYPE,
                device=self.input_device,
                callback=self._input_callback,
            )
            self._input_stream.start()
        except Exception as exc:  # noqa: BLE001 - PortAudio exposes platform-specific errors.
            self.stop()
            raise AudioError(
                "Could not open the configured microphone. Run --list-audio-devices and check Windows microphone permissions."
            ) from exc

        try:
            self._output_stream = sounddevice.RawOutputStream(
                samplerate=OUTPUT_SAMPLE_RATE,
                blocksize=OUTPUT_BLOCK_FRAMES,
                channels=AUDIO_CHANNELS,
                dtype=AUDIO_DTYPE,
                device=self.output_device,
                callback=self._output_callback,
            )
            self._output_stream.start()
        except Exception as exc:  # noqa: BLE001 - PortAudio exposes platform-specific errors.
            self.stop()
            raise AudioError(
                "Could not open the configured speaker. Run --list-audio-devices and check Windows audio permissions."
            ) from exc

    def _input_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        del frames, time_info, status
        if not self._accept_input or self._loop is None:
            return
        if not self.should_forward_microphone():
            self._record_suppressed_input()
            return
        data = bytes(indata)
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._enqueue_input, data)

    def _enqueue_input(self, data: bytes) -> None:
        if not self._accept_input:
            return
        while self.input_queue.full():
            try:
                self.input_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            self.input_queue.put_nowait(data)
        except asyncio.QueueFull:
            # The callback already returned; dropping this block is safer than
            # allowing stale microphone audio to grow without bound.
            return

    async def read_microphone(self) -> bytes:
        return await self.input_queue.get()

    def write_model_audio(self, data: bytes) -> None:
        self.output_buffer.append(data)

    def finish_model_turn(self) -> None:
        self.output_buffer.finish_turn()

    def clear_output(self) -> None:
        self.output_buffer.clear()

    def _output_callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        del frames, time_info, status
        output_size = len(outdata)
        outdata[:] = b"\x00" * output_size
        data = self.output_buffer.read(output_size)
        if data:
            self._mark_model_playback()
            data = _scale_pcm16(data, self.volume)
            outdata[: len(data)] = data

    def stop(self) -> None:
        """Stop and close streams without waiting on network or queue work."""

        self._accept_input = False
        for stream_name in ("_input_stream", "_output_stream"):
            stream = getattr(self, stream_name)
            if stream is None:
                continue
            try:
                stream.stop()
            except Exception:  # noqa: BLE001 - cleanup must continue for both streams.
                pass
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - cleanup must continue for both streams.
                pass
            setattr(self, stream_name, None)
        self.clear_output()
        self._flush_input_queue()


def list_audio_devices() -> str:
    """Return PortAudio's device listing for the CLI diagnostic command."""

    return str(sounddevice.query_devices())
