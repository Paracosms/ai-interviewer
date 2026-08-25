"""Environment-backed configuration for the local interviewer host."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from . import HOST_VERSION

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_LOCAL_PORT = 8765
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_GEMINI_VOICE = "Kore"
SUPPORTED_GEMINI_VOICES = frozenset(
    {
        "Zephyr",
        "Puck",
        "Charon",
        "Kore",
        "Fenrir",
        "Leda",
        "Orus",
        "Aoede",
        "Callirrhoe",
        "Autonoe",
        "Enceladus",
        "Iapetus",
        "Umbriel",
        "Algieba",
        "Despina",
        "Erinome",
        "Algenib",
        "Rasalgethi",
        "Laomedeia",
        "Achernar",
        "Alnilam",
        "Schedar",
        "Gacrux",
        "Pulcherrima",
        "Achird",
        "Zubenelgenubi",
        "Vindemiatrix",
        "Sadachbia",
        "Sadaltager",
        "Sulafat",
    }
)
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_THINKING_LEVELS = {"minimal", "low", "medium", "high"}


class ConfigurationError(ValueError):
    """Raised when the host cannot safely start with the supplied settings."""


@dataclass(frozen=True, slots=True)
class HostConfig:
    """Validated settings used by the host and its localhost API."""

    gemini_api_key: str
    gemini_model: str
    gemini_voice: str
    gemini_thinking_level: str
    local_host: str
    local_port: int
    audio_input_device: str | None
    audio_output_device: str | None
    log_level: str
    env_file: Path
    logs_dir: Path
    transcripts_dir: Path
    host_version: str = HOST_VERSION


def parse_local_port(raw_value: object, *, variable_name: str = "LOCAL_PORT") -> int:
    """Parse and validate a TCP port without silently selecting a replacement."""

    if raw_value is None:
        return DEFAULT_LOCAL_PORT

    text = str(raw_value).strip()
    if not text:
        raise ConfigurationError(
            f"{variable_name} must be an integer between 1 and 65535."
        )

    try:
        port = int(text, 10)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{variable_name} must be an integer between 1 and 65535."
        ) from exc

    if not 1 <= port <= 65535:
        raise ConfigurationError(
            f"{variable_name} must be an integer between 1 and 65535."
        )
    return port


def _read_environment_file(path: Path) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in dotenv_values(path).items()
        if value is not None
    }


def _optional_text(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_config(
    env_file: str | Path | None = None,
    *,
    environ: Mapping[str, object] | None = None,
) -> HostConfig:
    """Load and validate host configuration.

    Values from the process environment override values in ``host/.env``.
    """

    resolved_env_file = (
        Path(env_file).expanduser().resolve()
        if env_file is not None
        else Path(__file__).resolve().parents[1] / ".env"
    )
    values: dict[str, object] = _read_environment_file(resolved_env_file)
    values.update(dict(os.environ if environ is None else environ))

    api_key = str(values.get("GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        raise ConfigurationError("GEMINI_API_KEY is missing from host/.env.")

    local_host = str(values.get("LOCAL_HOST", DEFAULT_LOCAL_HOST) or "").strip()
    if local_host != DEFAULT_LOCAL_HOST:
        raise ConfigurationError(
            "LOCAL_HOST must remain 127.0.0.1 in the MVP."
        )

    local_port = parse_local_port(values.get("LOCAL_PORT", DEFAULT_LOCAL_PORT))

    base_dir = resolved_env_file.parent
    log_level = (str(values.get("LOG_LEVEL", "INFO") or "INFO").strip() or "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(VALID_LOG_LEVELS))
        raise ConfigurationError(f"LOG_LEVEL must be one of: {allowed}.")

    thinking_level = (
        str(values.get("GEMINI_THINKING_LEVEL", "low") or "low").strip().lower()
    )
    if thinking_level not in VALID_THINKING_LEVELS:
        allowed = ", ".join(sorted(VALID_THINKING_LEVELS))
        raise ConfigurationError(f"GEMINI_THINKING_LEVEL must be one of: {allowed}.")

    gemini_voice = (
        str(values.get("GEMINI_VOICE", DEFAULT_GEMINI_VOICE) or "").strip()
        or DEFAULT_GEMINI_VOICE
    )
    if gemini_voice not in SUPPORTED_GEMINI_VOICES:
        allowed = ", ".join(sorted(SUPPORTED_GEMINI_VOICES))
        raise ConfigurationError(f"GEMINI_VOICE must be one of: {allowed}.")

    return HostConfig(
        gemini_api_key=api_key,
        gemini_model=(
            str(values.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or "").strip()
            or DEFAULT_GEMINI_MODEL
        ),
        gemini_voice=gemini_voice,
        gemini_thinking_level=thinking_level,
        local_host=local_host,
        local_port=local_port,
        audio_input_device=_optional_text(values, "AUDIO_INPUT_DEVICE"),
        audio_output_device=_optional_text(values, "AUDIO_OUTPUT_DEVICE"),
        log_level=log_level,
        env_file=resolved_env_file,
        logs_dir=base_dir / "logs",
        transcripts_dir=base_dir / "transcripts",
    )
