from interviewer.hint_gate import HintGate
from interviewer.interview_tools import InterviewToolService, build_interview_tools
from interviewer.state import InterviewState


def make_state(now=0):
    state = InterviewState()
    state.begin(
        page_url="https://leetcode.com/problems/two-sum/",
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two numbers that add to a target.",
        language="python3",
        code="pass",
        code_version=1,
        now=now,
    )
    state.mark_running()
    return state


def test_only_the_two_required_tools_are_declared() -> None:
    tools = build_interview_tools()
    names = [declaration.name for declaration in tools[0].function_declarations]
    assert names == ["get_current_interview_state", "request_micro_hint"]


def test_current_state_tool_returns_latest_code() -> None:
    state = make_state(now=100)
    state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="latest",
        code_version=2,
        now=140,
    )
    service = InterviewToolService(state, HintGate(), clock=lambda: 150)
    result = service.get_current_interview_state()
    assert result["code"] == "latest"
    assert result["codeVersion"] == 2
    assert result["secondsSinceCodeChange"] == 10


def test_hint_tool_enforces_unlock_and_cooldown() -> None:
    state = make_state(now=0)
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    current_time = [119]
    service = InterviewToolService(state, gate, clock=lambda: current_time[0])
    denied = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert denied["allowed"] is False

    current_time[0] = 120
    allowed = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert allowed["allowed"] is True
    assert state.last_hint_at == 120

    current_time[0] = 149
    cooldown = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert cooldown["allowed"] is False


def test_implicit_hint_requires_code_inactivity() -> None:
    state = make_state(now=0)
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    current_time = [130]
    state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="changed",
        code_version=2,
        now=120,
    )
    service = InterviewToolService(state, gate, clock=lambda: current_time[0])
    recent = service.request_micro_hint({"candidateExplicitlyRequestedHelp": False})
    assert recent["allowed"] is False

    current_time[0] = 150
    idle = service.request_micro_hint({"candidateExplicitlyRequestedHelp": False})
    assert idle["allowed"] is True
