import asyncio
from pathlib import Path

import pytest
from google.genai import types

from interviewer.audio_io import AudioIO
from interviewer.config import ConfigurationError, load_config
from interviewer.gemini_session import (
    GeminiLiveSession,
    build_live_config,
    build_system_instruction,
    classify_gemini_error,
)
from interviewer.logging_utils import SessionJsonLogger
from interviewer.state import InterviewState


class ApiErrorForTest(Exception):
    status_code = 429


class InvalidKeyErrorForTest(Exception):
    code = 400
    message = "API_KEY_INVALID"

    def __str__(self):
        return self.message


class ModelUnavailableErrorForTest(Exception):
    code = 404


def make_config(tmp_path: Path):
    return load_config(
        tmp_path / ".env",
        environ={"GEMINI_API_KEY": "test-key"},
    )


def make_running_state() -> InterviewState:
    state = InterviewState()
    state.begin(
        page_url="https://leetcode.com/problems/two-sum/",
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two numbers.",
        language="python3",
        code="pass",
        code_version=1,
        now=0,
    )
    state.mark_running()
    return state


def test_live_config_enables_required_audio_and_session_features() -> None:
    config = build_live_config(voice="Kore", system_instruction="test")
    dumped = config.model_dump(exclude_none=True, by_alias=True)
    assert dumped["responseModalities"] == [types.Modality.AUDIO]
    assert dumped["inputAudioTranscription"] == {}
    assert dumped["outputAudioTranscription"] == {}
    assert dumped["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 1200
    assert dumped["thinkingConfig"]["thinkingLevel"] == types.ThinkingLevel.LOW
    assert dumped["sessionResumption"] == {}
    assert dumped["contextWindowCompression"] == {"slidingWindow": {}}


def test_thinking_level_is_configurable_and_validated(tmp_path: Path) -> None:
    configured = load_config(
        tmp_path / ".env",
        environ={"GEMINI_API_KEY": "test-key", "GEMINI_THINKING_LEVEL": "medium"},
    )
    assert configured.gemini_thinking_level == "medium"
    with pytest.raises(ConfigurationError, match="GEMINI_THINKING_LEVEL"):
        load_config(
            tmp_path / ".env",
            environ={"GEMINI_API_KEY": "test-key", "GEMINI_THINKING_LEVEL": "extreme"},
        )


def test_runtime_prompt_is_appended_to_editable_prompt(tmp_path: Path) -> None:
    prompt_path = tmp_path / "interviewer_prompt.txt"
    prompt_path.write_text("CUSTOM BEHAVIOR", encoding="utf-8")
    instruction = build_system_instruction(
        prompt_path=prompt_path,
        problem_title="Two Sum",
        problem_text="Problem statement",
        language="python3",
        code="pass",
    )
    assert instruction.startswith("CUSTOM BEHAVIOR")
    assert "RUNTIME RULES" in instruction
    assert "Two Sum" in instruction
    assert "pass" in instruction


def test_common_quota_error_is_user_readable() -> None:
    assert "free-tier quota" in classify_gemini_error(ApiErrorForTest())


def test_auth_and_model_errors_are_not_misreported_as_network_failures() -> None:
    assert "rejected" in classify_gemini_error(InvalidKeyErrorForTest())
    assert "model is unavailable" in classify_gemini_error(ModelUnavailableErrorForTest())


def test_resumption_handle_is_kept_in_memory_and_not_logged(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    logger = SessionJsonLogger(tmp_path / "logs")
    session = GeminiLiveSession(
        config=config,
        audio=AudioIO(),
        system_instruction="test",
        logger=logger,
        client=object(),
    )
    logger.start(now=0)
    session._process_message(
        types.LiveServerMessage(
            session_resumption_update=types.LiveServerSessionResumptionUpdate(
                new_handle="sensitive-handle", resumable=True
            )
        )
    )
    assert session.resumption_handle == "sensitive-handle"
    contents = logger.path.read_text(encoding="utf-8")
    assert "sensitive-handle" not in contents


def test_live_config_uses_a_resumption_handle_without_exposing_it() -> None:
    config = build_live_config(
        voice="Kore",
        system_instruction="test",
        resumption_handle="sensitive-handle",
    )
    assert config.session_resumption.handle == "sensitive-handle"


def test_usage_metadata_log_includes_configured_model(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    logger = SessionJsonLogger(tmp_path / "logs")
    session = GeminiLiveSession(
        config=config,
        audio=AudioIO(),
        system_instruction="test",
        logger=logger,
        client=object(),
    )
    logger.start(now=0)
    session._process_message(
        types.LiveServerMessage(
            usage_metadata=types.UsageMetadata(total_token_count=42)
        )
    )
    contents = logger.path.read_text(encoding="utf-8")
    assert '"event":"usage_metadata"' in contents
    assert '"total_token_count":42' in contents
    assert '"model":"gemini-3.1-flash-live-preview"' in contents


def test_interruption_clears_playback_and_logs_transcriptions(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    audio = AudioIO(output_buffer_bytes=64)
    logger = SessionJsonLogger(tmp_path / "logs")
    session = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction="test",
        logger=logger,
        client=object(),
    )
    logger.start(now=0)
    audio.write_model_audio(b"queued")
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            interrupted=True,
            input_transcription=types.Transcription(text="hello"),
            output_transcription=types.Transcription(text="welcome"),
        )
    )
    session._process_message(message)
    assert len(audio.output_buffer) == 0
    lines = (logger.path).read_text(encoding="utf-8").splitlines()
    assert '"event":"input_transcript"' in "\n".join(lines)
    assert '"event":"output_transcript"' in "\n".join(lines)


def test_interrupted_message_does_not_requeue_stale_audio(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    audio = AudioIO(output_buffer_bytes=64)
    session = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
    )
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            interrupted=True,
            model_turn=types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(data=b"stale", mime_type="audio/pcm;rate=24000")
                    )
                ]
            ),
        )
    )
    session._process_message(message)
    assert len(audio.output_buffer) == 0


def test_turn_complete_marks_buffer_to_drain_short_audio(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    audio = AudioIO(output_buffer_bytes=64)
    session = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
    )
    session._process_message(
        types.LiveServerMessage(
            server_content=types.LiveServerContent(
                model_turn=types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=b"tail", mime_type="audio/pcm;rate=24000"
                            )
                        )
                    ]
                ),
                turn_complete=True,
            )
        )
    )
    assert audio.output_buffer.read(8) == b"tail"


@pytest.mark.asyncio
async def test_ambiguous_transcript_holds_response_until_question_arrives(tmp_path: Path) -> None:
    audio = AudioIO(output_buffer_bytes=64)
    live = GeminiLiveSession(
        config=make_config(tmp_path),
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
        state=make_running_state(),
    )
    live._handle_candidate_transcript("I think the loop should um")
    assert audio.output_held is True
    live._handle_candidate_transcript("Can I assume the input is nonempty?")
    await asyncio.sleep(0)
    assert audio.output_held is False


def test_focus_mode_drops_unsolicited_output_but_allows_a_direct_question(tmp_path: Path) -> None:
    state = make_running_state()
    state.set_interaction_mode("focus")
    audio = AudioIO(output_buffer_bytes=64)
    live = GeminiLiveSession(
        config=make_config(tmp_path),
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
        state=state,
    )
    audio_message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"nope", mime_type="audio/pcm;rate=24000"))])
        )
    )
    live._process_message(audio_message)
    assert len(audio.output_buffer) == 0

    live._process_message(types.LiveServerMessage(
        server_content=types.LiveServerContent(
            input_transcription=types.Transcription(text="What does this constraint mean?")
        )
    ))
    live._process_message(audio_message)
    assert len(audio.output_buffer) == 4


@pytest.mark.asyncio
async def test_failed_run_allows_exactly_one_focus_interjection(tmp_path: Path) -> None:
    state = make_running_state()
    state.set_interaction_mode("focus")
    audio = AudioIO(output_buffer_bytes=64)
    live = GeminiLiveSession(
        config=make_config(tmp_path),
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
        state=state,
    )

    class RealtimeSession:
        def __init__(self):
            self.texts = []

        async def send_realtime_input(self, **kwargs):
            self.texts.append(kwargs.get("text"))

    sdk_session = RealtimeSession()
    live._session = sdk_session
    accepted = await live.notify_failed_run({
        "resultSignature": "run-1",
        "caseLabel": "Case 1",
        "input": "[2,7]",
        "expected": "[0,1]",
        "actual": "[]",
    })
    assert accepted is True
    assert "neutral question" in sdk_session.texts[0]
    live._process_message(
        types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True)),
        tool_call_pending=True,
    )
    assert live._failure_interjection_active is True
    live._process_message(types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"ask", mime_type="audio/pcm;rate=24000"))]),
            turn_complete=True,
        )
    ))
    assert audio.output_buffer.read(8) == b"ask"

    live._process_message(types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"extra", mime_type="audio/pcm;rate=24000"))])
        )
    ))
    assert len(audio.output_buffer) == 0


def test_receiver_stays_connected_across_model_turns(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    audio = AudioIO(output_buffer_bytes=64)
    live = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
    )

    class TwoTurnSession:
        def __init__(self) -> None:
            self.receive_calls = 0

        def receive(self):
            self.receive_calls += 1
            call_number = self.receive_calls

            async def messages():
                yield types.LiveServerMessage(
                    server_content=types.LiveServerContent(
                        model_turn=types.Content(
                            parts=[
                                types.Part(
                                    inline_data=types.Blob(
                                        data=f"turn-{call_number}".encode(),
                                        mime_type="audio/pcm;rate=24000",
                                    )
                                )
                            ]
                        ),
                        turn_complete=True,
                    )
                )
                if call_number == 2:
                    live.stop_event.set()

            return messages()

    sdk_session = TwoTurnSession()
    asyncio.run(live._receive_messages(sdk_session))

    assert sdk_session.receive_calls == 2
    assert len(audio.output_buffer) == len(b"turn-1turn-2")


def test_receiver_ignores_sdk_close_error_during_stop(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    live = GeminiLiveSession(
        config=config,
        audio=AudioIO(),
        system_instruction="test",
        logger=SessionJsonLogger(tmp_path / "logs"),
        client=object(),
    )

    class ClosingSession:
        def receive(self):
            async def messages():
                live.stop_event.set()
                raise RuntimeError("APIError: 1000 None")
                yield  # pragma: no cover - makes this an async generator.

            return messages()

    asyncio.run(live._receive_messages(ClosingSession()))


class FakeAudio:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    async def read_microphone(self) -> bytes:
        import asyncio

        await asyncio.sleep(0)
        return b"audio"

    def write_model_audio(self, data: bytes) -> None:
        del data

    def clear_output(self) -> None:
        return None

    def finish_model_turn(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True


class FakeSession:
    def __init__(self, owner, number: int) -> None:
        self.owner = owner
        self.number = number
        self.sent_initial_turn = False

    async def send_client_content(self, **kwargs) -> None:
        del kwargs
        self.sent_initial_turn = True

    async def send_realtime_input(self, **kwargs) -> None:
        del kwargs

    async def close(self) -> None:
        return None

    async def _messages(self):
        if self.number < 3:
            yield types.LiveServerMessage(
                session_resumption_update=types.LiveServerSessionResumptionUpdate(
                    new_handle=f"resume-me-{self.number}", resumable=True
                ),
                go_away=types.LiveServerGoAway(time_left=f"{self.number}s"),
            )
        else:
            yield types.LiveServerMessage(
                server_content=types.LiveServerContent(turn_complete=True)
            )
            self.owner.stop_event.set()

    def receive(self):
        return self._messages()


class FakeConnectContext:
    def __init__(self, owner, session) -> None:
        self.owner = owner
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False


class FakeClient:
    class Aio:
        def __init__(self, owner) -> None:
            self.live = owner

    def __init__(self, owner) -> None:
        self.owner = owner
        self.aio = self.Aio(self)
        self.calls = []

    def connect(self, *, model, config):
        self.calls.append((model, config))
        return FakeConnectContext(
            self.owner,
            FakeSession(self.owner, len(self.calls)),
        )


def test_go_away_reconnects_with_latest_handle(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    audio = FakeAudio()
    logger = SessionJsonLogger(tmp_path / "logs")
    reconnecting = []
    session = GeminiLiveSession(
        config=config,
        audio=audio,
        system_instruction="test",
        logger=logger,
        client=None,
        on_reconnecting=lambda: reconnecting.append(True),
    )
    client = FakeClient(session)
    session.client = client
    session._reconnect_delays = (0.0, 0.0)

    import asyncio

    asyncio.run(session.run())

    assert audio.started is True
    assert audio.stopped is True
    assert len(client.calls) == 3
    assert client.calls[1][1].session_resumption.handle == "resume-me-1"
    assert client.calls[2][1].session_resumption.handle == "resume-me-2"
    assert reconnecting == [True, True]
    transcripts = list(config.transcripts_dir.iterdir())
    assert len(transcripts) == 1
    assert transcripts[0].read_text(encoding="utf-8").startswith(
        f"This transcript is based off the log: {logger.path.name}\n"
    )
