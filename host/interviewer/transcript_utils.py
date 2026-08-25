"""Create readable interview transcripts from JSON Lines session logs."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping


class TranscriptError(ValueError):
    """Raised when a session log cannot be converted into a transcript."""


_LOG_NAME_PATTERN = re.compile(
    r"^interview-(?P<date>\d{8})T(?P<time>\d{6})(?:Z|[+-]\d{4})-[^.]+\.jsonl$"
)


@dataclass(slots=True)
class _TranscriptTurn:
    speaker: str
    timestamp: str
    text: str


def transcript_filename(log_path: str | Path) -> str:
    """Return the requested transcript name derived from a log filename.

    The timestamp is intentionally read from the log filename rather than
    converted through the machine's timezone. This keeps the hour and minute
    identical to the log title, as required by the transcript naming scheme.
    """

    name = Path(log_path).name
    match = _LOG_NAME_PATTERN.fullmatch(name)
    if match is None:
        raise TranscriptError(
            f"Log filename does not match the interview log format: {name}"
        )
    try:
        started_at = datetime.strptime(
            f"{match.group('date')}{match.group('time')}",
            "%Y%m%d%H%M%S",
        )
    except ValueError as exc:
        raise TranscriptError(f"Log filename contains an invalid timestamp: {name}") from exc
    return f"{started_at.strftime('%m-%d-%Y---%H:%M')}.txt"


def _actual_filename(requested_name: str) -> str:
    """Make the requested name usable on Windows filesystems.

    Windows reserves ``:`` for drive letters and alternate data streams, so a
    normal file cannot use the requested colon between hour and minute. The
    logical name remains available through :func:`transcript_filename`; the
    on-disk fallback uses a hyphen only on Windows.
    """

    if os.name == "nt":
        return requested_name.replace(":", "-")
    return requested_name


def _format_record_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TranscriptError("A transcript record is missing its timestamp.")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TranscriptError(f"Invalid transcript record timestamp: {value}") from exc
    # The transcript uses the timestamp's original clock value. Do not convert
    # it to UTC or local time, because the log already records the intended time.
    return f"{timestamp.hour}:{timestamp.minute:02d}:{timestamp.second:02d}"


def _normalise_fragment(text: str) -> str:
    """Keep token spacing while ensuring one speaker turn stays on one line."""

    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _transcript_entries(log_path: Path) -> Iterator[tuple[str, str, str]]:
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TranscriptError(f"Could not read session log: {log_path}") from exc

    speaker_by_event = {
        "input_transcript": "Andrew",
        "output_transcript": "Interviewer",
    }
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptError(
                f"Invalid JSON in session log line {line_number}: {log_path.name}"
            ) from exc
        if not isinstance(record, Mapping):
            continue
        speaker = speaker_by_event.get(record.get("event"))
        if speaker is None:
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        yield speaker, _format_record_timestamp(record.get("timestamp")), _normalise_fragment(text)


def render_transcript(log_path: str | Path) -> str:
    """Render a JSONL session log as a readable, speaker-labelled transcript."""

    path = Path(log_path)
    turns: list[_TranscriptTurn] = []
    for speaker, timestamp, fragment in _transcript_entries(path):
        if turns and turns[-1].speaker == speaker:
            turns[-1].text += fragment
        else:
            turns.append(_TranscriptTurn(speaker, timestamp, fragment))

    blocks = [f"{turn.speaker} - {turn.timestamp}\n\n{turn.text.strip()}" for turn in turns]
    header = f"This transcript is based off the log: {path.name}"
    if not blocks:
        return f"{header}\n"
    return header + "\n\n" + "\n\n".join(blocks) + "\n"


def generate_transcript(
    log_path: str | Path,
    transcripts_dir: str | Path,
) -> Path:
    """Write and return the transcript generated from one session log."""

    log = Path(log_path)
    requested_name = transcript_filename(log)
    output_dir = Path(transcripts_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _actual_filename(requested_name)
    output_path.write_text(render_transcript(log), encoding="utf-8", newline="\n")
    return output_path
