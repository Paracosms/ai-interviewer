import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from interviewer import gemini_session
from interviewer.config import load_config
from interviewer.gemini_session import HostSessionManager
from interviewer.http_api import create_app
from interviewer.state import InterviewState


def make_config(tmp_path):
    return load_config(
        tmp_path / ".env",
        environ={"GEMINI_API_KEY": "test-key"},
    )


def start_payload():
    return {
        "protocolVersion": 1,
        "pageUrl": "https://leetcode.com/problems/two-sum/",
        "problemSlug": "two-sum",
        "problemTitle": "Two Sum",
        "problemText": "Find two numbers that add to a target. " * 20,
        "language": "python3",
        "code": "class Solution: pass",
        "codeVersion": 1,
    }


class FakeLiveSession:
    instances = []

    def __init__(self, *, on_ready=None, on_usage=None, on_reconnecting=None, **kwargs):
        del kwargs
        self.on_ready = on_ready
        self.on_usage = on_usage
        self.on_reconnecting = on_reconnecting
        self.stopped = asyncio.Event()
        self.started = False
        self.__class__.instances.append(self)

    async def run(self):
        self.started = True
        if self.on_ready:
            self.on_ready()
        await self.stopped.wait()

    async def wait_ready(self, timeout=20.0):
        del timeout
        while not self.started:
            await asyncio.sleep(0)

    async def stop(self):
        self.stopped.set()


@pytest.mark.asyncio
async def test_http_manager_lifecycle_updates_authoritative_state(tmp_path, monkeypatch):
    FakeLiveSession.instances.clear()
    monkeypatch.setattr(gemini_session, "GeminiLiveSession", FakeLiveSession)
    config = make_config(tmp_path)
    state = InterviewState()
    manager = HostSessionManager(config=config, prompt_path=tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("interviewer behavior", encoding="utf-8")
    app = create_app(
        config,
        state=state,
        session_starter=manager.start,
        session_stopper=manager.stop,
        code_update_logger=manager.log_code_update,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        started = await client.post("/session/start", json=start_payload())
        assert started.status == 200
        assert (await started.json())["status"] == "running"
        assert state.status.value == "running"
        assert state.gemini_connected is True
        assert len(FakeLiveSession.instances) == 1

        updated = await client.post(
            "/session/code",
            json={
                "protocolVersion": 1,
                "pageUrl": start_payload()["pageUrl"],
                "language": "python3",
                "code": "class Solution:\n    pass",
                "codeVersion": 2,
            },
        )
        assert updated.status == 200
        assert state.code_version == 2

        stopped = await client.post("/session/stop")
        assert stopped.status == 200
        assert state.status.value == "stopped"
        assert state.code is None

        restarted = await client.post("/session/start", json=start_payload())
        assert restarted.status == 200
        assert (await restarted.json())["status"] == "running"
        assert len(FakeLiveSession.instances) == 2
        stopped_again = await client.post("/session/stop")
        assert stopped_again.status == 200
        assert state.status.value == "stopped"
    finally:
        await client.close()
        await manager.stop()
