"""Command-line entry point for the local interviewer host."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys

from aiohttp import web

from .audio_io import AudioError, AudioIO, list_audio_devices
from .config import ConfigurationError, load_config
from .gemini_session import (
    GeminiLiveSession,
    GeminiSessionError,
    HostSessionManager,
    build_system_instruction,
)
from .http_api import create_app
from .logging_utils import SessionJsonLogger
from .state import InterviewState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LeetCode AI Interviewer local host")
    parser.add_argument(
        "--env-file",
        help="Path to the host .env file (defaults to host/.env).",
    )
    parser.add_argument(
        "--list-audio-devices",
        action="store_true",
        help="List PortAudio input/output devices and exit.",
    )
    parser.add_argument(
        "--terminal-spike",
        action="store_true",
        help="Run the development audio-only Gemini Live spike with a sample problem.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_audio_devices:
        try:
            print(list_audio_devices())
        except Exception as exc:  # noqa: BLE001 - device enumeration is platform-specific.
            print(f"Could not list audio devices: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        config = load_config(args.env_file)
        logging.basicConfig(
            level=getattr(logging, config.log_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        if args.terminal_spike:
            asyncio.run(_run_terminal_spike(config))
        else:
            state = InterviewState()
            manager = HostSessionManager(config=config)
            app = create_app(
                config,
                state=state,
                session_starter=manager.start,
                session_stopper=manager.stop,
                code_update_logger=manager.log_code_update,
            )
            asyncio.run(_serve_config(config, app, manager))
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (AudioError, GeminiSessionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


async def _run_terminal_spike(config) -> None:
    """Development-only audio check before Firefox integration exists."""

    prompt_path = Path(__file__).resolve().parents[1] / "interviewer_prompt.txt"
    system_instruction = build_system_instruction(
        prompt_path=prompt_path,
        problem_title="Two Sum (audio-only development spike)",
        problem_text=(
            "Given an integer array nums and an integer target, return the indices "
            "of two numbers whose sum is target. Assume exactly one answer exists."
        ),
        language="python3",
        code="class Solution:\n    def twoSum(self, nums, target):\n        pass",
    )
    audio = AudioIO(
        input_device=config.audio_input_device,
        output_device=config.audio_output_device,
    )
    session = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction=system_instruction,
        logger=SessionJsonLogger(config.logs_dir),
    )
    try:
        await session.run()
    finally:
        await session.stop()


async def _serve_config(config, app, session_manager=None) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.local_host, port=config.local_port)
    try:
        await site.start()
    except OSError as exc:
        await runner.cleanup()
        if getattr(exc, "winerror", None) == 10048 or getattr(exc, "errno", None) in {48, 98, 10048}:
            raise RuntimeError(
                f"Could not start localhost server on {config.local_host}:{config.local_port} because the port is already in use.\n\n"
                f"Choose another port in host/.env:\nLOCAL_PORT=8766\n\n"
                "Then set the same Host port in the Firefox extension."
            ) from exc
        raise

    print("LeetCode AI Interviewer host")
    print(f"Listening on http://{config.local_host}:{config.local_port}")
    print(f"Model: {config.gemini_model}")
    print(f"Audio input: {config.audio_input_device or 'Windows default'}")
    print(f"Audio output: {config.audio_output_device or 'Windows default'}")
    print("Status: ready")
    try:
        await asyncio.Event().wait()
    finally:
        if session_manager is not None:
            await session_manager.stop()
        await runner.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
