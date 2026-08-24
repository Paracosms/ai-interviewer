"""The two application-owned Gemini function tools."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types

from .hint_gate import HintGate
from .state import InterviewState, InterviewStatus


def build_interview_tools() -> list[types.Tool]:
    """Return exactly the two local tools allowed in an interview."""

    get_state = types.FunctionDeclaration(
        name="get_current_interview_state",
        description=(
            "Return the latest authoritative problem, language, complete code buffer, "
            "code version, elapsed time, and hint status. Call before code-specific discussion."
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
            "The application, not the model, decides eligibility."
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
    return [types.Tool(function_declarations=[get_state, request_hint])]


@dataclass(slots=True)
class InterviewToolService:
    """Execute tool calls against the local authoritative state."""

    state: InterviewState
    hint_gate: HintGate
    clock: Callable[[], float] = time.monotonic

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = args or {}
        if name == "get_current_interview_state":
            return self.get_current_interview_state()
        if name == "request_micro_hint":
            return self.request_micro_hint(arguments)
        return {"error": f"Unknown interview tool: {name}"}

    def get_current_interview_state(self) -> dict[str, Any]:
        now = self.clock()
        return {
            "problemTitle": self.state.problem_title,
            "language": self.state.language,
            "code": self.state.code,
            "codeVersion": self.state.code_version,
            "elapsedSeconds": int(self.state.elapsed_seconds(now=now)),
            "hintsEligible": self.state.hints_eligible(self.hint_gate, now=now),
            "secondsSinceCodeChange": int(self.state.seconds_since_code_change(now=now)),
        }

    def request_micro_hint(self, args: dict[str, Any]) -> dict[str, Any]:
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
        return decision.as_dict()

