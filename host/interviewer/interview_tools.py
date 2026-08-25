"""Application-owned Gemini function tools for the live interview."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types

from .hint_gate import HintGate
from .problem_analysis import ProblemAnalysisContext
from .state import InterviewState, InterviewStatus


def build_interview_tools() -> list[types.Tool]:
    """Return the application-owned tools allowed in an interview."""

    get_state = types.FunctionDeclaration(
        name="get_current_interview_state",
        description=(
            "Return the latest authoritative problem, language, complete code buffer, "
            "code version, elapsed time, hint status, and background problem-analysis status. "
            "Once analysis is ready, this also returns the private verified solution dossier "
            "and hint ladder. Call before code-specific or solution-specific discussion."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )
    request_hint = types.FunctionDeclaration(
        name="request_micro_hint",
        description=(
            "Ask the application whether one constrained Socratic question may be used. "
            "The application, not the model, decides eligibility and returns the private "
            "precomputed hint candidates when permission is granted."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the candidate appears to need a small push.",
                },
                "candidateExplicitlyRequestedHelp": {
                    "type": "boolean",
                    "description": "Whether the candidate explicitly asked for help.",
                },
            },
            "additionalProperties": False,
        },
    )
    set_mode = types.FunctionDeclaration(
        name="set_interaction_mode",
        description=(
            "Persist whether the candidate wants normal conversation or uninterrupted focus time. "
            "Use focus when the candidate says they will implement, explain while coding, think "
            "out loud, or asks for a moment. Use conversation when they explicitly say they are "
            "done or ready for normal feedback."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["conversation", "focus"]},
                "reason": {"type": "string"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    )
    return [types.Tool(function_declarations=[get_state, request_hint, set_mode])]


@dataclass(slots=True)
class InterviewToolService:
    """Execute tool calls against the local authoritative state."""

    state: InterviewState
    hint_gate: HintGate
    clock: Callable[[], float] = time.monotonic
    problem_analysis: ProblemAnalysisContext | None = None

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = args or {}
        if name == "get_current_interview_state":
            return self.get_current_interview_state()
        if name == "request_micro_hint":
            return self.request_micro_hint(arguments)
        if name == "set_interaction_mode":
            return self.set_interaction_mode(arguments)
        return {"error": f"Unknown interview tool: {name}"}

    def get_current_interview_state(self) -> dict[str, Any]:
        now = self.clock()
        result = {
            "problemTitle": self.state.problem_title,
            "language": self.state.language,
            "code": self.state.code,
            "codeVersion": self.state.code_version,
            "elapsedSeconds": int(self.state.elapsed_seconds(now=now)),
            "hintsEligible": self.state.hints_eligible(self.hint_gate, now=now),
            "secondsSinceCodeChange": int(self.state.seconds_since_code_change(now=now)),
            "interactionMode": self.state.interaction_mode.value,
            "latestRunResult": self.state.latest_run_result,
        }
        if self.problem_analysis is not None:
            result["problemAnalysis"] = self.problem_analysis.tool_payload()
        return result

    def set_interaction_mode(self, args: dict[str, Any]) -> dict[str, Any]:
        mode = args.get("mode")
        if not isinstance(mode, str):
            return {"error": "mode must be conversation or focus."}
        try:
            resolved = self.state.set_interaction_mode(mode)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"ok": True, "interactionMode": resolved.value}

    def request_micro_hint(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.problem_analysis is not None and self.problem_analysis.status != "ready":
            if self.problem_analysis.status == "error":
                reason = (
                    "Verified hints are unavailable because background problem analysis failed. "
                    "Continue as a neutral interviewer without solution-specific assistance."
                )
            else:
                reason = (
                    "Verified hints are still being prepared. Continue as a neutral interviewer "
                    "and do not generate a hint from your own solution attempt."
                )
            return {
                "allowed": False,
                "reason": reason,
                "problemAnalysis": self.problem_analysis.tool_payload(),
            }

        now = self.clock()
        explicit = args.get("candidateExplicitlyRequestedHelp") is True
        decision = self.hint_gate.evaluate(
            session_running=self.state.status == InterviewStatus.RUNNING,
            elapsed_seconds=self.state.elapsed_seconds(now=now),
            last_hint_at=self.state.last_hint_at,
            seconds_since_code_change=self.state.seconds_since_code_change(now=now),
            candidate_explicitly_requested_help=explicit,
            now=now,
        )
        if decision.allowed:
            self.state.last_hint_at = now
        result = decision.as_dict()
        analysis = self.problem_analysis.analysis if self.problem_analysis is not None else None
        if decision.allowed and analysis is not None:
            result["problemAnalysis"] = self.problem_analysis.tool_payload()
            result["precomputedHintCandidates"] = list(analysis.hint_questions)
            result["selectionInstruction"] = (
                "Select the least revealing candidate appropriate to the current conversation "
                "and code. Ask exactly that one Socratic question, with only minimal wording "
                "changes needed to fit the candidate's approach."
            )
        return result
