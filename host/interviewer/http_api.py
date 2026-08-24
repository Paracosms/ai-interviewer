"""Loopback-only HTTP API for the Firefox extension."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from aiohttp import web

from . import HOST_VERSION, PROTOCOL_VERSION
from .config import HostConfig
from .hint_gate import HintGate
from .state import InterviewState, InterviewStatus, ProblemChangedError, StateError

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
    """Shared state and optional session hooks used by HTTP handlers."""

    config: HostConfig
    state: InterviewState
    hint_gate: HintGate
    session_starter: Callable[[dict[str, Any], InterviewState], Awaitable[None]] | None = None
    session_stopper: Callable[[], Awaitable[None]] | None = None
    code_update_logger: Callable[[str, InterviewState], None] | None = None
    lock: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        if self.lock is None:
            self.lock = asyncio.Lock()


RUNTIME_KEY = web.AppKey("runtime", HostRuntime)


def _json_response(payload: Mapping[str, Any], *, status: int = 200, origin: str | None = None) -> web.Response:
    headers = {"Cache-Control": "no-store"}
    if origin and origin.startswith(ALLOWED_EXTENSION_ORIGIN_PREFIX):
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Vary": "Origin",
            }
        )
    return web.json_response(payload, status=status, headers=headers)


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
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{key} must be a nonempty string.")
    if len(value) > MAXIMUMS[key]:
        raise ApiError(f"{key} exceeds the maximum length of {MAXIMUMS[key]} characters.")
    return value


def _required_code_version(payload: Mapping[str, Any]) -> int:
    value = payload.get("codeVersion")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError("codeVersion must be a nonnegative integer.")
    return value


def validate_start_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    _require_protocol(payload)
    page_url = _required_text(payload, "pageUrl")
    if not page_url.startswith("https://leetcode.com/problems/"):
        raise ApiError("pageUrl must be an HTTPS LeetCode problem URL.")
    problem_text = _required_text(payload, "problemText")
    if len(problem_text.strip()) < 200:
        raise ApiError("problemText must contain at least 200 characters.")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "pageUrl": page_url,
        "problemSlug": _required_text(payload, "problemSlug"),
        "problemTitle": _required_text(payload, "problemTitle"),
        "problemText": problem_text,
        "language": _required_text(payload, "language"),
        "code": _required_text(payload, "code"),
        "codeVersion": _required_code_version(payload),
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
        "code": _required_text(payload, "code"),
        "codeVersion": _required_code_version(payload),
    }


def _runtime(request: web.Request) -> HostRuntime:
    return request.app[RUNTIME_KEY]


async def health(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    async with runtime.lock:  # type: ignore[arg-type]
        status = runtime.state.status.value
    return _json_response(
        {
            "ok": True,
            "protocolVersion": PROTOCOL_VERSION,
            "hostVersion": HOST_VERSION,
            "sessionStatus": status,
            "port": runtime.config.local_port,
        },
        origin=request.headers.get("Origin"),
    )


async def session_status(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    async with runtime.lock:  # type: ignore[arg-type]
        payload = runtime.state.public_snapshot(
            model=runtime.config.gemini_model,
            hint_gate=runtime.hint_gate,
        )
    return _json_response(payload, origin=request.headers.get("Origin"))


async def session_start(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        payload = validate_start_payload(await _read_json(request))
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status, origin=request.headers.get("Origin"))

    async with runtime.lock:  # type: ignore[arg-type]
        if runtime.state.is_active:
            return _json_response(
                {"ok": False, "error": "An interview is already running."},
                status=409,
                origin=request.headers.get("Origin"),
            )
        if runtime.session_starter is None:
            return _json_response(
                {"ok": False, "error": "Gemini Live session is unavailable in this host instance."},
                status=503,
                origin=request.headers.get("Origin"),
            )
        runtime.state.begin(
            page_url=payload["pageUrl"],
            problem_slug=payload["problemSlug"],
            problem_title=payload["problemTitle"],
            problem_text=payload["problemText"],
            language=payload["language"],
            code=payload["code"],
            code_version=payload["codeVersion"],
        )

    try:
        await runtime.session_starter(payload, runtime.state)
    except Exception as exc:  # noqa: BLE001 - convert startup failures to user-facing errors.
        async with runtime.lock:  # type: ignore[arg-type]
            runtime.state.mark_error(str(exc) or "The interview could not be started.")
        return _json_response(
            {"ok": False, "error": str(exc) or "The interview could not be started."},
            status=502,
            origin=request.headers.get("Origin"),
        )

    async with runtime.lock:  # type: ignore[arg-type]
        if runtime.state.status == InterviewStatus.ERROR:
            return _json_response(
                {
                    "ok": False,
                    "error": runtime.state.last_error or "The interview could not be started.",
                },
                status=502,
                origin=request.headers.get("Origin"),
            )
        if not runtime.state.is_active:
            return _json_response(
                {"ok": False, "error": "The interview stopped before it became ready."},
                status=502,
                origin=request.headers.get("Origin"),
            )
        runtime.state.mark_running()
    return _json_response({"ok": True, "status": "running"}, origin=request.headers.get("Origin"))


async def session_code(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    try:
        payload = validate_code_payload(await _read_json(request))
    except ApiError as exc:
        return _json_response({"ok": False, "error": exc.message}, status=exc.status, origin=request.headers.get("Origin"))

    async with runtime.lock:  # type: ignore[arg-type]
        try:
            result = runtime.state.update_code(
                page_url=payload["pageUrl"],
                language=payload["language"],
                code=payload["code"],
                code_version=payload["codeVersion"],
            )
        except ProblemChangedError as exc:
            runtime.state.last_error = str(exc)
            return _json_response({"ok": False, "error": str(exc)}, status=409, origin=request.headers.get("Origin"))
        except StateError as exc:
            return _json_response({"ok": False, "error": str(exc)}, status=409, origin=request.headers.get("Origin"))
    if runtime.code_update_logger is not None:
        runtime.code_update_logger(result.value, runtime.state)
    return _json_response({"ok": True, "result": result.value}, origin=request.headers.get("Origin"))


async def session_stop(request: web.Request) -> web.Response:
    runtime = _runtime(request)
    async with runtime.lock:  # type: ignore[arg-type]
        runtime.state.mark_stopping()
    if runtime.session_stopper is not None:
        try:
            await runtime.session_stopper()
        except Exception as exc:  # noqa: BLE001 - stop remains idempotent but reports the failure.
            async with runtime.lock:  # type: ignore[arg-type]
                runtime.state.stop(error=str(exc) or "The interview could not be stopped cleanly.")
            return _json_response(
                {"ok": False, "error": str(exc) or "The interview could not be stopped cleanly."},
                status=502,
                origin=request.headers.get("Origin"),
            )
    async with runtime.lock:  # type: ignore[arg-type]
        runtime.state.stop()
    return _json_response({"ok": True, "status": "stopped"}, origin=request.headers.get("Origin"))


async def _options(request: web.Request) -> web.Response:
    """Fallback OPTIONS route; the middleware supplies the CORS headers."""

    return web.Response(status=204)


def create_app(
    config: HostConfig,
    *,
    state: InterviewState | None = None,
    hint_gate: HintGate | None = None,
    session_starter: Callable[[dict[str, Any], InterviewState], Awaitable[None]] | None = None,
    session_stopper: Callable[[], Awaitable[None]] | None = None,
    code_update_logger: Callable[[str, InterviewState], None] | None = None,
) -> web.Application:
    """Create the aiohttp application without binding a socket."""

    runtime = HostRuntime(
        config=config,
        state=state or InterviewState(),
        hint_gate=hint_gate or HintGate(),
        session_starter=session_starter,
        session_stopper=session_stopper,
        code_update_logger=code_update_logger,
    )
    app = web.Application(middlewares=[_security_middleware], client_max_size=200_000)
    app[RUNTIME_KEY] = runtime
    app.router.add_get("/health", health)
    app.router.add_get("/session/status", session_status)
    app.router.add_post("/session/start", session_start)
    app.router.add_post("/session/code", session_code)
    app.router.add_post("/session/stop", session_stop)
    app.router.add_route("OPTIONS", "/{path:.*}", _options)
    return app
