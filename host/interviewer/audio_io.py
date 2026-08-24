"""Realtime Windows audio plumbing for Gemini Live PCM input and output."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

import sounddevice as sounddevice

INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "int16"
INPUT_BLOCK_MS = 80
INPUT_BLOCK_FRAMES = INPUT_SAMPLE_RATE * INPUT_BLOCK_MS // 1_000
OUTPUT_BLOCK_FRAMES = OUTPUT_SAMPLE_RATE * INPUT_BLOCK_MS // 1_000


class AudioError(RuntimeError):
    """Raised when a configured Windows audio device cannot be opened."""


def _device_value(value: str | None) -> str | int | None:
    """Pass numeric device IDs as integers and named devices as strings."""

    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if text.isdecimal():
        return int(text)
    return text


class PcmPlaybackBuffer:
    """Bounded, non-blocking PCM buffer consumed by PortAudio's callback."""

    def __init__(self, *, max_bytes: int = OUTPUT_SAMPLE_RATE * 2 * 4) -> None:
        self.max_bytes = max(1, int(max_bytes))
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        chunk = bytes(data)
        if len(chunk) > self.max_bytes:
            chunk = chunk[-self.max_bytes :]
        with self._lock:
            while self._chunks and self._size + len(chunk) > self.max_bytes:
                self._size -= len(self._chunks.popleft())
            if self._size + len(chunk) <= self.max_bytes:
                self._chunks.append(chunk)
                self._size += len(chunk)

    def read(self, size: int) -> bytes:
        requested = max(0, int(size))
        if requested == 0:
            return b""
        with self._lock:
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
            return bytes(result)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0

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
        output_buffer_bytes: int = OUTPUT_SAMPLE_RATE * 2 * 4,
    ) -> None:
        self.input_device = _device_value(input_device)
        self.output_device = _device_value(output_device)
        self.input_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=input_queue_size)
        self.output_buffer = PcmPlaybackBuffer(max_bytes=output_buffer_bytes)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._input_stream: Any = None
        self._output_stream: Any = None
        self._accept_input = False

    @property
    def running(self) -> bool:
        return self._input_stream is not None or self._output_stream is not None

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

    def clear_output(self) -> None:
        self.output_buffer.clear()

    def _output_callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        del frames, time_info, status
        output_size = len(outdata)
        outdata[:] = b"\x00" * output_size
        data = self.output_buffer.read(output_size)
        if data:
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
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except asyncio.QueueEmpty:
                break


def list_audio_devices() -> str:
    """Return PortAudio's device listing for the CLI diagnostic command."""

    return str(sounddevice.query_devices())

