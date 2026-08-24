from interviewer.hint_gate import HintGate
from interviewer.interview_tools import InterviewToolService, build_interview_tools
from interviewer.problem_analysis import (
    GroundedProblemAnalysis,
    GroundedSource,
    IntendedSolution,
    InterviewHint,
    ProblemAnalysisContext,
    ProblemDossier,
)
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


def ready_analysis_context():
    analysis = GroundedProblemAnalysis(
        dossier=ProblemDossier(
            verified_problem_title="Two Sum",
            problem_identity_matches=True,
            verification_summary="Two grounded sources match the supplied problem statement.",
            sources_agree=True,
            source_consensus="Both grounded sources agree on the intended optimal solution.",
            intended_solution=IntendedSolution(
                algorithm="single-pass hash map",
                summary="Store prior values and look up each required complement while scanning.",
                key_invariant="The map contains exactly the values observed before the current item.",
                correctness_reasoning="Each lookup finds a valid earlier partner without reusing the current element.",
                time_complexity="O(n)",
                space_complexity="O(n)",
            ),
            interviewer_checkpoints=["complement", "no reuse", "complexity"],
            common_wrong_turns=["same element twice", "returns values"],
            hint_ladder=[
                InterviewHint(
                    order=index,
                    diagnostic_target=f"checkpoint {index}",
                    when_to_use=f"candidate is stuck at checkpoint {index}",
                    socratic_question=f"What prior information would help at checkpoint {index}?",
                )
                for index in range(1, 6)
            ],
        ),
        sources=(
            GroundedSource("LeetCode", "https://leetcode.com/two-sum"),
            GroundedSource("Reference", "https://example.com/two-sum"),
        ),
    )
    context = ProblemAnalysisContext()
    context.mark_ready(analysis)
    return context


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
    service = InterviewToolService(
        state,
        gate,
        clock=lambda: current_time[0],
        problem_analysis=ready_analysis_context(),
    )
    denied = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert denied["allowed"] is False

    current_time[0] = 120
    allowed = service.request_micro_hint(
        {"candidateExplicitlyRequestedHelp": True, "reason": "help"}
    )
    assert allowed["allowed"] is True
    assert allowed["precomputedHintCandidates"][0] == "What prior information would help at checkpoint 1?"
    assert allowed["problemAnalysis"]["status"] == "ready"
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
    assert state.last_hint_at is None
