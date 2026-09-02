from interviewer.hint_gate import HintGate
from interviewer.interview_tools import InterviewToolService, build_interview_tools
from interviewer.problem_analysis import (
    IntendedSolution,
    InterviewCheckpoint,
    InterviewHint,
    ProblemAnalysis,
    ProblemAnalysisContext,
    ProblemDossier,
)
from interviewer.state import InterviewState


def make_state(now=0):
    state = InterviewState()
    state.begin(
        page_url="https://leetcode.com/problems/two-sum/",
        problem_title="Two Sum",
        language="python3",
        code="pass",
        code_version=1,
        now=now,
    )
    state.mark_running()
    return state


def ready_analysis_context():
    analysis = ProblemAnalysis(
        dossier=ProblemDossier(
            problem_title="Two Sum",
            statement_summary="Find two distinct positions whose values add to the target.",
            constraint_implications=[
                "A linear scan is preferable for a large input.",
                "The result must preserve the required index semantics.",
            ],
            analysis_confidence="high",
            confidence_reason="The supplied statement and constraints are clear enough for analysis.",
            assumptions=[],
            intended_solution=IntendedSolution(
                algorithm="single-pass hash map",
                summary="Store prior values and look up each required complement while scanning.",
                key_invariant="The map contains exactly the values observed before the current item.",
                correctness_reasoning="Each lookup finds a valid earlier partner without reusing the current element.",
                time_complexity="O(n)",
                space_complexity="O(n)",
            ),
            interviewer_checkpoints=[
                InterviewCheckpoint(
                    topic="complement relationship",
                    evidence_of_understanding="The candidate explains how each value relates to the target.",
                    concern_signals=["searches without connecting values to the target"],
                    neutral_follow_up_question="How does the target affect the relationship between two values?",
                ),
                InterviewCheckpoint(
                    topic="distinct positions",
                    evidence_of_understanding="The candidate accounts for using two different positions.",
                    concern_signals=["allows the current item to match itself"],
                    neutral_follow_up_question="What does the requirement about the two positions imply?",
                ),
                InterviewCheckpoint(
                    topic="complexity",
                    evidence_of_understanding="The candidate relates repeated work to the input size.",
                    concern_signals=["does not account for nested scans"],
                    neutral_follow_up_question="How does your running time change as the input grows?",
                ),
            ],
            common_wrong_turns=["same element twice", "returns values"],
            hint_ladder=[
                InterviewHint(
                    order=index,
                    diagnostic_target=f"checkpoint {index}",
                    when_to_use=f"candidate is stuck at checkpoint {index}",
                    socratic_question=f"What prior information would help at checkpoint {index}?",
                )
                for index in range(1, 4)
            ],
        ),
    )
    context = ProblemAnalysisContext()
    context.mark_ready(analysis)
    return context


def test_required_interview_tools_are_declared() -> None:
    tools = build_interview_tools()
    names = [declaration.name for declaration in tools[0].function_declarations]
    assert names == ["get_current_interview_state", "request_micro_hint", "set_interaction_mode"]


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
    assert result["interactionMode"] == "conversation"
    assert result["interviewPhase"] == "implementation"
    assert result["codeSyncStatus"] == "connected"


def test_mode_tool_persists_focus_mode() -> None:
    state = make_state()
    service = InterviewToolService(state, HintGate())
    assert service.set_interaction_mode({"mode": "focus"}) == {
        "ok": True,
        "interactionMode": "focus",
    }
    assert service.get_current_interview_state()["interactionMode"] == "focus"


def test_hint_tool_enforces_unlock_and_cooldown() -> None:
    state = make_state(now=0)
    gate = HintGate(warmup_seconds=240, cooldown_seconds=30, stuck_code_seconds=20)
    current_time = [10]
    service = InterviewToolService(
        state,
        gate,
        clock=lambda: current_time[0],
        problem_analysis=ready_analysis_context(),
    )
    allowed = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert allowed["allowed"] is True
    assert allowed["hint"]["question"] == "What prior information would help at checkpoint 1?"
    assert allowed["hint"]["levelName"] == "open_probe"
    assert allowed["precomputedHintCandidates"][0] == "What prior information would help at checkpoint 1?"
    assert allowed["problemAnalysis"]["status"] == "ready"
    assert state.last_hint_at == 10
    assert state.last_hint_level == 1

    current_time[0] = 30
    cooldown = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert cooldown["allowed"] is False
    assert "hint cooldown" in cooldown["reason"]

    current_time[0] = 45
    allowed2 = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert allowed2["allowed"] is True
    assert allowed2["hint"]["levelName"] == "test_case"
    assert state.last_hint_level == 2


def test_implicit_hint_requires_code_inactivity() -> None:
    state = make_state(now=0)
    gate = HintGate(warmup_seconds=60, cooldown_seconds=30, stuck_code_seconds=20)
    current_time = [130]
    state.update_code(
        page_url=state.problem_url,
        language="python3",
        code="changed",
        code_version=2,
        now=120,
    )
    service = InterviewToolService(
        state,
        gate,
        clock=lambda: current_time[0],
        problem_analysis=ready_analysis_context(),
    )
    recent = service.request_micro_hint({
        "candidateExplicitlyRequestedHelp": False,
        "candidateUnproductivelyLooping": True,
    })
    assert recent["allowed"] is False

    current_time[0] = 150
    idle = service.request_micro_hint({
        "candidateExplicitlyRequestedHelp": False,
        "candidateUnproductivelyLooping": True,
    })
    assert idle["allowed"] is True


def test_pending_analysis_blocks_hint_without_consuming_cooldown() -> None:
    state = make_state(now=0)
    gate = HintGate(unlock_seconds=0, cooldown_seconds=30, stuck_code_seconds=0)
    context = ProblemAnalysisContext()
    service = InterviewToolService(
        state,
        gate,
        clock=lambda: 100,
        problem_analysis=context,
    )

    result = service.request_micro_hint({"candidateExplicitlyRequestedHelp": True})

    assert result["allowed"] is False
    assert result["problemAnalysis"]["status"] == "pending"
    assert result["reason"] == "Interviewer hints are still being prepared."
    assert state.last_hint_at is None


def test_failed_analysis_explains_that_interviewer_hints_are_unavailable() -> None:
    state = make_state(now=0)
    context = ProblemAnalysisContext()
    context.mark_error("analysis failed")
    service = InterviewToolService(
        state,
        HintGate(unlock_seconds=0, cooldown_seconds=30, stuck_code_seconds=0),
        clock=lambda: 100,
        problem_analysis=context,
    )

    result = service.request_micro_hint({"candidateExplicitlyRequestedHelp": True})

    assert result["allowed"] is False
    assert result["reason"] == (
        "Interviewer hints are unavailable because background problem analysis failed."
    )
