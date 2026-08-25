import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from interviewer import gemini_session
from interviewer.config import load_config
from interviewer.gemini_session import HostSessionManager
from interviewer.http_api import create_app
from interviewer.problem_analysis import (
    GroundedProblemAnalysis,
    GroundedSource,
    IntendedSolution,
    InterviewHint,
    ProblemDossier,
)
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
        self.system_instruction = kwargs["system_instruction"]
        self.voice = kwargs["config"].gemini_voice
        self.tool_handler = kwargs["tool_handler"]
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


def fake_problem_analysis():
    return GroundedProblemAnalysis(
        dossier=ProblemDossier(
            verified_problem_title="Two Sum",
            problem_identity_matches=True,
            verification_summary="Two independent sources match the supplied problem and constraints.",
            sources_agree=True,
            source_consensus="Both sources identify the same optimal hash-map solution and complexity.",
            intended_solution=IntendedSolution(
                algorithm="single-pass hash map",
                summary="Store each prior value and look up the complement while scanning once.",
                key_invariant="Before each item, the map contains exactly the previously seen values.",
                correctness_reasoning="A matching complement is found exactly when the corresponding pair has both been visited.",
                time_complexity="O(n)",
                space_complexity="O(n)",
            ),
            interviewer_checkpoints=["states complement", "avoids reuse", "analyzes complexity"],
            common_wrong_turns=["uses the same element twice", "returns values instead of indices"],
            hint_ladder=[
                InterviewHint(
                    order=index,
                    diagnostic_target=f"checkpoint {index}",
                    when_to_use=f"candidate is stuck at stage {index}",
                    socratic_question=f"What information from earlier elements would help at stage {index}?",
                )
                for index in range(1, 6)
            ],
        ),
        sources=(
            GroundedSource("LeetCode", "https://leetcode.com/problems/two-sum/"),
            GroundedSource("Independent", "https://example.com/two-sum"),
        ),
    )


class FakeProblemAnalyzer:
    def __init__(self):
        self.calls = []

    async def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return fake_problem_analysis()


class SlowProblemAnalyzer:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, **kwargs):
        del kwargs
        self.started.set()
        await self.release.wait()
        return fake_problem_analysis()


class FailingProblemAnalyzer:
    async def analyze(self, **kwargs):
        del kwargs
        await asyncio.sleep(0)
        raise RuntimeError("grounded analysis unavailable")


@pytest.mark.asyncio
async def test_live_starts_while_problem_analysis_remains_in_background(tmp_path, monkeypatch):
    FakeLiveSession.instances.clear()
    monkeypatch.setattr(gemini_session, "GeminiLiveSession", FakeLiveSession)
    config = make_config(tmp_path)
    analyzer = SlowProblemAnalyzer()
    manager = HostSessionManager(
        config=config,
        prompt_path=tmp_path / "prompt.txt",
        problem_analyzer=analyzer,
    )
    (tmp_path / "prompt.txt").write_text("interviewer behavior", encoding="utf-8")
    payload = start_payload()
    state = InterviewState()
    state.begin(
        page_url=payload["pageUrl"],
        problem_slug=payload["problemSlug"],
        problem_title=payload["problemTitle"],
        problem_text=payload["problemText"],
        language=payload["language"],
        code=payload["code"],
        code_version=payload["codeVersion"],
    )

    try:
        await manager.start(payload, state)
        await asyncio.wait_for(analyzer.started.wait(), timeout=1)
        assert FakeLiveSession.instances[0].started is True
        assert state.gemini_connected is True
        assert state.problem_analysis_status == "pending"

        pending = await FakeLiveSession.instances[0].tool_handler(
            "get_current_interview_state", {}
        )
        assert pending["problemAnalysis"] == {"status": "pending"}

        analyzer.release.set()
        for _ in range(20):
            if state.problem_analysis_status == "ready":
                break
            await asyncio.sleep(0)
        assert state.problem_analysis_status == "ready"
        ready = await FakeLiveSession.instances[0].tool_handler(
            "get_current_interview_state", {}
        )
        assert ready["problemAnalysis"]["status"] == "ready"
        assert "verifiedProblemDossier" in ready["problemAnalysis"]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_selected_voice_is_used_for_live_session(tmp_path, monkeypatch):
    FakeLiveSession.instances.clear()
    monkeypatch.setattr(gemini_session, "GeminiLiveSession", FakeLiveSession)
    config = make_config(tmp_path)
    manager = HostSessionManager(
        config=config,
        prompt_path=tmp_path / "prompt.txt",
        problem_analyzer=FakeProblemAnalyzer(),
    )
    (tmp_path / "prompt.txt").write_text("interviewer behavior", encoding="utf-8")
    payload = start_payload()
    payload["voice"] = "Aoede"
    state = InterviewState()
    state.begin(
        page_url=payload["pageUrl"],
        problem_slug=payload["problemSlug"],
        problem_title=payload["problemTitle"],
        problem_text=payload["problemText"],
        language=payload["language"],
        code=payload["code"],
        code_version=payload["codeVersion"],
    )

    try:
        await manager.start(payload, state)
        assert FakeLiveSession.instances[0].voice == "Aoede"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_problem_analysis_failure_does_not_stop_live_interview(tmp_path, monkeypatch):
    FakeLiveSession.instances.clear()
    monkeypatch.setattr(gemini_session, "GeminiLiveSession", FakeLiveSession)
    config = make_config(tmp_path)
    manager = HostSessionManager(
        config=config,
        prompt_path=tmp_path / "prompt.txt",
        problem_analyzer=FailingProblemAnalyzer(),
    )
    (tmp_path / "prompt.txt").write_text("interviewer behavior", encoding="utf-8")
    payload = start_payload()
    state = InterviewState()
    state.begin(
        page_url=payload["pageUrl"],
        problem_slug=payload["problemSlug"],
        problem_title=payload["problemTitle"],
        problem_text=payload["problemText"],
        language=payload["language"],
        code=payload["code"],
        code_version=payload["codeVersion"],
    )

    try:
        await manager.start(payload, state)
        for _ in range(20):
            if state.problem_analysis_status == "error":
                break
            await asyncio.sleep(0)
        assert FakeLiveSession.instances[0].started is True
        assert state.gemini_connected is True
        assert state.problem_analysis_status == "error"
        assert "grounded analysis unavailable" in state.problem_analysis_error
        tool_state = await FakeLiveSession.instances[0].tool_handler(
            "get_current_interview_state", {}
        )
        assert tool_state["problemAnalysis"]["status"] == "error"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_http_manager_lifecycle_updates_authoritative_state(tmp_path, monkeypatch):
    FakeLiveSession.instances.clear()
    monkeypatch.setattr(gemini_session, "GeminiLiveSession", FakeLiveSession)
    config = make_config(tmp_path)
    state = InterviewState()
    analyzer = FakeProblemAnalyzer()
    manager = HostSessionManager(
        config=config,
        prompt_path=tmp_path / "prompt.txt",
        problem_analyzer=analyzer,
    )
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
        assert len(analyzer.calls) == 1
        assert "PRIVATE VERIFIED INTERVIEWER DOSSIER" in FakeLiveSession.instances[0].system_instruction
        assert "still being prepared in the background" in FakeLiveSession.instances[0].system_instruction
        assert "single-pass hash map" not in FakeLiveSession.instances[0].system_instruction
        tool_state = await FakeLiveSession.instances[0].tool_handler(
            "get_current_interview_state", {}
        )
        assert tool_state["problemAnalysis"]["status"] == "ready"
        assert (
            tool_state["problemAnalysis"]["verifiedProblemDossier"]["intended_solution"]["algorithm"]
            == "single-pass hash map"
        )
        assert state.problem_analysis_status == "ready"

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
        assert len(analyzer.calls) == 2
        stopped_again = await client.post("/session/stop")
        assert stopped_again.status == 200
        assert state.status.value == "stopped"
    finally:
        await client.close()
        await manager.stop()
