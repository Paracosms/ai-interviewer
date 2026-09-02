"""Loopback-only HTTP API for the Firefox extension."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from aiohttp import web

from . import HOST_VERSION, PROTOCOL_VERSION
from .config import DEFAULT_GEMINI_VOICE, HostConfig, SUPPORTED_GEMINI_VOICES
from .hint_gate import HintGate
from .state import (
    InterviewState,
    InterviewStatus,
    ProblemChangedError,
    StateError,
)

MAXIMUMS = {
    "pageUrl": 2_000,
    "problemSlug": 200,
    "problemTitle": 500,
    "problemText": 100_000,
    "language": 100,
    "code": 50_000,
}

ALLOWED_EXTENSION_ORIGIN_PREFIX = "moz-extension://"


class ApiError(Exception):
    """An expected client-facing API error."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(slots=True)
class HostRuntime:
    """Shared state and session controller used by HTTP handlers."""

    config: HostConfig
    state: InterviewState
    hint_gate: HintGate
    controller: "SessionController"


class SessionController(Protocol):
    async def start(self, payload: dict[str, Any], state: InterviewState) -> None: ...
    async def stop(self) -> None: ...
    def log_code_update(self, result: str, state: InterviewState) -> None: ...
    def log_interaction_mode(self, source: str, state: InterviewState) -> None: ...
    def get_volume(self) -> float: ...
    def set_volume(self, value: float) -> None: ...


RUNTIME_KEY = web.AppKey("runtime", HostRuntime)


def _json_response(payload: Mapping[str, Any], *, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, headers={"Cache-Control": "no-store"})


def _origin_is_allowed(origin: str | None) -> bool:
    return origin is None or origin.startswith(ALLOWED_EXTENSION_ORIGIN_PREFIX)


@web.middleware
async def _security_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    origin = request.headers.get("Origin")
    if not _origin_is_allowed(origin):
        return _json_response(
            {"ok": False, "error": "Browser origins are not allowed for this loopback API."},
            status=403,
        )
    if request.method == "OPTIONS":
        headers = {"Cache-Control": "no-store"}
        if origin:
            headers.update(
                {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Vary": "Origin",
                }
            )
        return web.Response(status=204, headers=headers)
    response = await handler(request)
    if origin and origin.startswith(ALLOWED_EXTENSION_ORIGIN_PREFIX):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"
    return response


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        raw = await request.read()
        if not raw:
            raise ApiError("Malformed JSON request body.")
        value = json.loads(raw.decode("utf-8"))
    except web.HTTPRequestEntityTooLarge as exc:
        raise ApiError("Request body is too large.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError("Malformed JSON request body.") from exc
    if not isinstance(value, dict):
        raise ApiError("JSON request body must be an object.")
    return value


def _require_protocol(payload: Mapping[str, Any]) -> None:
    if payload.get("protocolVersion") != PROTOCOL_VERSION:
        raise ApiError(f"Unsupported protocol version. Expected {PROTOCOL_VERSION}.")


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _bounded_text(payload, key)
    if not value.strip():
        raise ApiError(f"{key} must be a nonempty string.")
    return value


def _bounded_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ApiError(f"{key} must be a string.")
    if len(value) > MAXIMUMS[key]:
        raise ApiError(f"{key} exceeds the maximum length of {MAXIMUMS[key]} characters.")
    return value


def _required_code_version(payload: Mapping[str, Any]) -> int:
    value = payload.get("codeVersion")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError("codeVersion must be a nonnegative integer.")
    return value


def _optional_code_source_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("codeSourceId")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ApiError("codeSourceId must be a nonempty string of at most 200 characters.")
    return value


def validate_volume_payload(payload: Mapping[str, Any]) -> float:
    value = payload.get("volume")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ApiError("volume must be a finite number between 0 and 1.")
    if not 0 <= value <= 1:
        raise ApiError("volume must be between 0 and 1.")
    return float(value)


def validate_start_payload(
    payload: Mapping[str, Any],
    *,
    default_voice: str = DEFAULT_GEMINI_VOICE,
) -> dict[str, Any]:
    _require_protocol(payload)
    page_url = _required_text(payload, "pageUrl")
    if not page_url.startswith("https://leetcode.com/problems/"):
        raise ApiError("pageUrl must be an HTTPS LeetCode problem URL.")
    problem_text = _required_text(payload, "problemText")
    if len(problem_text.strip()) < 200:
        raise ApiError("problemText must contain at least 200 characters.")
    voice = payload.get("voice", default_voice)
    if not isinstance(voice, str) or voice not in SUPPORTED_GEMINI_VOICES:
        raise ApiError("voice must be one of the supported Gemini voices.")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "pageUrl": page_url,
        "problemSlug": _required_text(payload, "problemSlug"),
        "problemTitle": _required_text(payload, "problemTitle"),
        "problemText": problem_text,
        "language": _required_text(payload, "language"),
        "code": _bounded_text(payload, "code"),
        "codeVersion": _required_code_version(payload),
        "codeSourceId": _optional_code_source_id(payload),
        "voice": voice,
    }


def validate_code_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _require_protocol(payload)
    page_url = _required_text(payload, "pageUrl")
    if not page_url.startswith("https://leetcode.com/problems/"):
        raise ApiError("pageUrl must be an HTTPS LeetCode problem URL.")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "pageUrl": page_url,
        "language": _required_text(payload, "language"),
        "code": _bounded_text(payload, "code"),
        "codeVersion": _required_code_version(payload),
        "codeSourceId": _optional_code_source_id(payload),
    }


def validate_mode_payload(payload: Mapping[str, Any]) -> str:
    _require_protocol(payload)
    mode = payload.get("mode")
    if mode not in {"conversation", "focus"}:
        raise ApiError("mode must be conversation or focus.")
    return str(mode)


def _runtime(request: web.Request) -> HostRuntime:
    return request.app[RUNTIME_KEY]


def validate_activity_payload(payload: Mapping[str, Any]) -> str:
    _require_protocol(payload)
    activity = payload.get("activity")
    if not isinstance(activity, str) or activity != "typing":
        raise ApiError("activity must be 'typing'.")
    return activity


async def health(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    status = runtime.state.status.value
    return _json_response(
        {
            "ok": True,
            "protocolVersion": PROTOCOL_VERSION,
            "hostVersion": HOST_VERSION,
            "sessionStatus": status,
            "port": runtime.config.local_port,
        },
    )


async def session_status(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    payload = runtime.state.public_snapshot(
        model=runtime.config.gemini_model,
        hint_gate=runtime.hint_gate,
    )
    return _json_response(payload)


async def session_start(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        payload = validate_start_payload(
            await _read_json(request),
            default_voice=runtime.config.gemini_voice,
        )
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status)

    if runtime.state.is_active:
        runtime.state.mark_stopping()
        try:
            await runtime.controller.stop()
        except Exception:  # noqa: BLE001 - cleanly stop previous session before starting new one
            pass
        runtime.state.stop()
    runtime.state.begin(
        page_url=payload["pageUrl"],
        problem_title=payload["problemTitle"],
        language=payload["language"],
        code=payload["code"],
        code_version=payload["codeVersion"],
        code_source_id=payload["codeSourceId"],
    )

    try:
        await runtime.controller.start(payload, runtime.state)
    except Exception as exc:  # noqa: BLE001 - convert startup failures to user-facing errors.
        if runtime.state.status in {InterviewStatus.STOPPED, InterviewStatus.STOPPING}:
            return _json_response(
                {"ok": False, "error": "The interview stopped before it became ready."},
                status=502,
            )
        runtime.state.mark_error(str(exc) or "The interview could not be started.")
        return _json_response(
            {"ok": False, "error": str(exc) or "The interview could not be started."},
            status=502,
        )

    if runtime.state.status == InterviewStatus.ERROR:
        return _json_response(
            {
                "ok": False,
                "error": runtime.state.last_error or "The interview could not be started.",
            },
            status=502,
        )
    if runtime.state.status == InterviewStatus.STARTING:
        runtime.state.mark_running()
    elif runtime.state.status != InterviewStatus.RUNNING:
        return _json_response(
            {"ok": False, "error": "The interview stopped before it became ready."},
            status=502,
        )
    return _json_response({"ok": True, "status": "running"})


async def session_code(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        payload = validate_code_payload(await _read_json(request))
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status)

    try:
        result = runtime.state.update_code(
            page_url=payload["pageUrl"],
            language=payload["language"],
            code=payload["code"],
            code_version=payload["codeVersion"],
            code_source_id=payload["codeSourceId"],
        )
    except ProblemChangedError as exc:
        runtime.state.last_error = str(exc)
        runtime.state.mark_code_sync_disconnected()
        return _json_response({"ok": False, "error": str(exc)}, status=409)
    except StateError as exc:
        return _json_response({"ok": False, "error": str(exc)}, status=409)
    runtime.controller.log_code_update(
        result.value,
        runtime.state,
        incoming_code_version=payload["codeVersion"],
        incoming_code_source_id=payload["codeSourceId"],
        incoming_code=payload["code"],
    )
    return _json_response({"ok": True, "result": result.value})


async def session_activity(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        validate_activity_payload(await _read_json(request))
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status)

    if not runtime.state.is_active:
        return _json_response({"ok": False, "error": "No interview is running."}, status=409)

    runtime.state.mark_typing_activity(time.time())
    return _json_response({"ok": True, "status": "accepted"})


async def session_mode(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        mode = validate_mode_payload(await _read_json(request))
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status)
    try:
        resolved = runtime.state.set_interaction_mode(mode)
    except StateError as exc:
        return _json_response({"ok": False, "error": str(exc)}, status=409)
    runtime.controller.log_interaction_mode("popup", runtime.state)
    return _json_response(
        {"ok": True, "interactionMode": resolved.value},
    )


async def session_stop(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    runtime.state.mark_stopping()
    try:
        await runtime.controller.stop()
    except Exception as exc:  # noqa: BLE001 - stop remains idempotent but reports the failure.
        runtime.state.stop(error=str(exc) or "The interview could not be stopped cleanly.")
        return _json_response(
            {"ok": False, "error": str(exc) or "The interview could not be stopped cleanly."},
            status=502,
        )
    runtime.state.stop()
    return _json_response({"ok": True, "status": "stopped"})


async def audio_volume(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    if request.method == "POST":
        try:
            volume = validate_volume_payload(await _read_json(request))
        except ApiError as exc:
            return _json_response(
                {"ok": False, "error": exc.message},
                status=exc.status,
            )
        try:
            runtime.controller.set_volume(volume)
        except ValueError as exc:
            return _json_response(
                {"ok": False, "error": str(exc)},
                status=400,
            )
    volume = runtime.controller.get_volume()
    return _json_response(
        {"ok": True, "volume": volume},
    )


def create_app(
    config: HostConfig,
    *,
    controller: SessionController,
    state: InterviewState | None = None,
    hint_gate: HintGate | None = None,
) -> web.Application:
    """Create the aiohttp application without binding a socket."""

    runtime = HostRuntime(
        config=config,
        state=state or InterviewState(),
        hint_gate=hint_gate or HintGate(),
        controller=controller,
    )
    app = web.Application(middlewares=[_security_middleware], client_max_size=200_000)
    app[RUNTIME_KEY] = runtime
    app.router.add_get("/health", health)
    app.router.add_get("/session/status", session_status)
    app.router.add_post("/session/start", session_start)
    app.router.add_post("/session/code", session_code)
    app.router.add_post("/session/mode", session_mode)
    app.router.add_post("/session/activity", session_activity)
    app.router.add_post("/session/stop", session_stop)
    app.router.add_get("/audio/volume", audio_volume)
    app.router.add_post("/audio/volume", audio_volume)
    return app
