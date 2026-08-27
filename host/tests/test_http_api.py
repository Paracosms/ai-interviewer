import socket

import pytest
from aiohttp.test_utils import TestClient, TestServer

from interviewer.__main__ import _serve_config
from interviewer.config import load_config
from interviewer.http_api import create_app


def make_config(tmp_path):
    return load_config(
        tmp_path / ".env",
        environ={"GEMINI_API_KEY": "test-key", "LOCAL_PORT": "8765"},
    )


def start_payload(*, code="class Solution: pass", version=1):
    return {
        "protocolVersion": 1,
        "pageUrl": "https://leetcode.com/problems/two-sum/",
        "problemSlug": "two-sum",
        "problemTitle": "Two Sum",
        "problemText": "Find two numbers that add to a target. " * 20,
        "language": "python3",
        "code": code,
        "codeVersion": version,
    }


class FakeController:
    def __init__(self, starter=None):
        self.starter = starter
        self.volume = 1.0

    async def start(self, payload, state):
        if self.starter is not None:
            await self.starter(payload, state)

    async def stop(self):
        return None

    def log_code_update(self, result, state, **kwargs):
        del result, state, kwargs

    def log_interaction_mode(self, source, state):
        pass

    def get_volume(self):
        return self.volume

    def set_volume(self, value):
        self.volume = value


def make_app(config, starter=None):
    return create_app(config, controller=FakeController(starter))


@pytest.mark.asyncio
async def test_health_and_status_endpoints(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        health = await client.get("/health")
        assert health.status == 200
        assert await health.json() == {
            "ok": True,
            "protocolVersion": 1,
            "hostVersion": "0.1.1",
            "sessionStatus": "stopped",
            "port": 8765,
        }

        status = await client.get("/session/status")
        status_body = await status.json()
        assert status.status == 200
        assert status_body["status"] == "stopped"
        assert status_body["running"] is False
        assert status_body["model"] == "gemini-3.1-flash-live-preview"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_audio_volume_endpoint_round_trips_volume(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        initial = await client.get("/audio/volume")
        assert initial.status == 200
        assert (await initial.json())["volume"] == 1.0

        updated = await client.post("/audio/volume", json={"volume": 0.35})
        assert updated.status == 200
        assert (await updated.json())["volume"] == 0.35

        invalid = await client.post("/audio/volume", json={"volume": 1.1})
        assert invalid.status == 400
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_malformed_json_is_rejected(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        response = await client.post(
            "/session/code",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400
        assert "Malformed JSON" in (await response.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_extension_cors_preflight_is_allowed(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        response = await client.options(
            "/session/not-a-route",
            headers={"Origin": "moz-extension://test-extension"},
        )
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == "moz-extension://test-extension"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_second_simultaneous_session_is_rejected(tmp_path):
    async def fake_starter(payload, state):
        return None

    client = TestClient(
        TestServer(make_app(make_config(tmp_path), fake_starter))
    )
    await client.start_server()
    try:
        first = await client.post("/session/start", json=start_payload())
        second = await client.post("/session/start", json=start_payload(version=2))
        assert first.status == 200
        assert second.status == 409
        assert "already running" in (await second.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_startup_failure_is_not_overwritten_as_running(tmp_path):
    async def fake_starter(payload, state):
        del payload
        state.mark_error("Gemini free-tier quota is unavailable or exhausted. No paid fallback was attempted.")

    client = TestClient(
        TestServer(make_app(make_config(tmp_path), fake_starter))
    )
    await client.start_server()
    try:
        response = await client.post("/session/start", json=start_payload())
        body = await response.json()
        assert response.status == 502
        assert body["ok"] is False
        assert "free-tier quota" in body["error"]

        status = await client.get("/session/status")
        status_body = await status.json()
        assert status_body["status"] == "error"
        assert status_body["running"] is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stop_is_idempotent(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        first = await client.post("/session/stop")
        second = await client.post("/session/stop")
        assert first.status == 200
        assert second.status == 200
        assert (await second.json())["status"] == "stopped"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_problem_change_is_visible_in_host_status(tmp_path):
    async def fake_starter(payload, state):
        del payload, state

    client = TestClient(
        TestServer(make_app(make_config(tmp_path), fake_starter))
    )
    await client.start_server()
    try:
        started = await client.post("/session/start", json=start_payload())
        assert started.status == 200
        changed = await client.post(
            "/session/code",
            json={
                "protocolVersion": 1,
                "pageUrl": "https://leetcode.com/problems/valid-parentheses/",
                "language": "python3",
                "code": "pass",
                "codeVersion": 2,
            },
        )
        assert changed.status == 409
        assert "active LeetCode problem changed" in (await changed.json())["error"]

        status = await client.get("/session/status")
        status_body = await status.json()
        assert "active LeetCode problem changed" in status_body["lastError"]
        assert status_body["status"] == "running"
    finally:
        await client.post("/session/stop")
        await client.close()


@pytest.mark.asyncio
async def test_interaction_mode_endpoint_updates_public_status(tmp_path):
    async def fake_starter(payload, state):
        del payload, state

    client = TestClient(TestServer(make_app(make_config(tmp_path), fake_starter)))
    await client.start_server()
    try:
        await client.post("/session/start", json=start_payload())
        changed = await client.post(
            "/session/mode",
            json={"protocolVersion": 1, "mode": "focus"},
        )
        assert changed.status == 200
        assert (await changed.json())["interactionMode"] == "focus"
        status = await client.get("/session/status")
        assert (await status.json())["interactionMode"] == "focus"
        invalid = await client.post(
            "/session/mode",
            json={"protocolVersion": 1, "mode": "quiet"},
        )
        assert invalid.status == 400
    finally:
        await client.post("/session/stop")
        await client.close()


@pytest.mark.asyncio
async def test_ordinary_browser_origin_is_rejected(tmp_path):
    client = TestClient(TestServer(make_app(make_config(tmp_path))))
    await client.start_server()
    try:
        response = await client.get(
            "/health", headers={"Origin": "https://example.com"}
        )
        assert response.status == 403
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_occupied_port_has_actionable_startup_error(tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    config = load_config(
        tmp_path / ".env",
        environ={"GEMINI_API_KEY": "test-key", "LOCAL_PORT": str(port)},
    )
    try:
        with pytest.raises(RuntimeError, match="because the port is already in use"):
            await _serve_config(config, make_app(config))
    finally:
        blocker.close()
