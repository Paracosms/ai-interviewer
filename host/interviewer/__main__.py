"""Command-line entry point for the local interviewer host."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from aiohttp import web

from .audio_io import AudioError, list_audio_devices
from .config import ConfigurationError, load_config
from .gemini_session import (
    GeminiSessionError,
    HostSessionManager,
)
from .http_api import create_app
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
        state = InterviewState()
        manager = HostSessionManager(config=config)
        app = create_app(
            config,
            controller=manager,
            state=state,
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
    print(f"Thinking level: {config.gemini_thinking_level}")
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
