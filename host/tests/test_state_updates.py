import pytest

from interviewer.hint_gate import HintGate
from interviewer.state import (
    CodeUpdateResult,
    InteractionMode,
    InterviewState,
    ProblemChangedError,
)
from interviewer.gemini_session import HostSessionManager


def make_state() -> InterviewState:
    state = InterviewState()
    state.begin(
        page_url="https://leetcode.com/problems/two-sum/",
        problem_title="Two Sum",
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
        code="",
        code_version=2,
        now=130,
    )
    assert result is CodeUpdateResult.APPLIED
    assert state.code_version == 2
    assert state.code == ""
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


def test_new_code_source_can_resynchronize_after_revision_reset() -> None:
    state = make_state()
    state.code_source_id = "old-background"
    state.code_version = 700
    result = state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="class Solution:\n    return 42",
        code_version=1,
        code_source_id="new-background",
        now=140,
    )
    assert result is CodeUpdateResult.RESYNCHRONIZED
    assert state.code_version == 1
    assert state.code_source_id == "new-background"
    assert "return 42" in state.code


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


def test_interaction_mode_is_application_owned() -> None:
    state = make_state()
    assert state.set_interaction_mode("focus") is InteractionMode.FOCUS
    snapshot = state.public_snapshot(model="model", hint_gate=HintGate())
    assert snapshot["interactionMode"] == "focus"


def test_stopping_rejects_late_connection_callbacks() -> None:
    state = make_state()
    state.mark_stopping()
    with pytest.raises(Exception, match="state as running"):
        state.mark_running()
    with pytest.raises(Exception, match="state"):
        state.mark_reconnecting()
    HostSessionManager._mark_connected(state)
    HostSessionManager._mark_reconnecting(state)
    assert state.status.value == "stopping"
    assert state.gemini_connected is False


def test_problem_submission_and_tab_urls_are_accepted_for_same_slug() -> None:
    state = make_state()
    # Submission URL
    res1 = state.update_code(
        page_url="https://leetcode.com/problems/two-sum/submissions/1376912345/",
        language="python3",
        code="def twoSum(nums, target): return [0, 1]",
        code_version=2,
        now=130,
    )
    assert res1.value == "applied"
    assert state.code_sync_status == "connected"

    # Tab URL with query params
    res2 = state.update_code(
        page_url="https://leetcode.com/problems/two-sum/description/?envType=study-plan-v2",
        language="python3",
        code="def twoSum(nums, target): return [0, 1]",
        code_version=2,
        now=140,
    )
    assert res2.value == "ignored_duplicate"
    assert state.code_sync_status == "connected"
