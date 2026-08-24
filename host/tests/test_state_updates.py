import pytest

from interviewer.state import (
    CodeUpdateResult,
    InterviewState,
    ProblemChangedError,
)
from interviewer.gemini_session import HostSessionManager


def make_state() -> InterviewState:
    state = InterviewState()
    state.begin(
        page_url="https://leetcode.com/problems/two-sum/",
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two numbers that add to a target.",
        language="python3",
        code="class Solution: pass",
        code_version=1,
        now=100,
    )
    state.mark_running()
    return state


def test_newer_code_version_replaces_old_code() -> None:
    state = make_state()
    result = state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="class Solution:\n    pass",
        code_version=2,
        now=130,
    )
    assert result is CodeUpdateResult.APPLIED
    assert state.code_version == 2
    assert state.code == "class Solution:\n    pass"
    assert state.last_code_change_at == 130


def test_duplicate_code_version_is_ignored() -> None:
    state = make_state()
    result = state.update_code(
        page_url=state.problem_url,
        language="python3",
        code=state.code,
        code_version=1,
        now=130,
    )
    assert result is CodeUpdateResult.IGNORED_DUPLICATE
    assert state.last_code_change_at == 100


def test_older_code_version_is_ignored() -> None:
    state = make_state()
    state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="new code",
        code_version=2,
        now=130,
    )
    result = state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="old code",
        code_version=1,
        now=140,
    )
    assert result is CodeUpdateResult.IGNORED_OLDER
    assert state.code == "new code"


def test_language_update_is_accepted_without_code_change() -> None:
    state = make_state()
    result = state.update_code(
        page_url=state.problem_url,
        language="java",
        code=state.code,
        code_version=2,
        now=130,
    )
    assert result is CodeUpdateResult.APPLIED
    assert state.language == "java"
    assert state.last_code_change_at == 100


def test_problem_url_mismatch_is_rejected() -> None:
    state = make_state()
    with pytest.raises(ProblemChangedError):
        state.update_code(
            page_url="https://leetcode.com/problems/valid-parentheses/",
            language="python3",
            code="new code",
            code_version=2,
            now=130,
        )


def test_reconnecting_and_connected_callbacks_preserve_live_state() -> None:
    state = make_state()
    HostSessionManager._mark_reconnecting(state)
    assert state.status.value == "reconnecting"
    assert state.gemini_connected is False
    HostSessionManager._mark_connected(state)
    assert state.status.value == "running"
    assert state.gemini_connected is True


def test_code_updates_are_rejected_after_session_error() -> None:
    state = make_state()
    state.mark_error("connection failed")
    with pytest.raises(Exception, match="currently running"):
        state.update_code(
            page_url=state.problem_url,
            language="python3",
            code="new code",
            code_version=2,
        )


def test_stopping_is_an_active_state() -> None:
    state = make_state()
    state.mark_stopping()
    assert state.status.value == "stopping"
    assert state.is_active is True
    assert state.gemini_connected is False
