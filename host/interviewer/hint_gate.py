"""Application-owned timing and behavioral rules for the one-question hint boundary."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Literal

InterviewPhase = Literal["warmup", "approach", "implementation", "testing"]
HintLevel = Literal["open_probe", "test_case", "architectural_nudge"]
HINT_LEVEL_ORDER: tuple[HintLevel, ...] = ("open_probe", "test_case", "architectural_nudge")

HINT_WARMUP_SECONDS = 4 * 60
HINT_COOLDOWN_SECONDS = 4 * 60
STUCK_CODE_SECONDS = 3 * 60

HINT_CONSTRAINTS = (
    "Ask exactly one brief Socratic question.",
    "Base it on the candidate's stated approach or current code.",
    "Do not name a new algorithm or data structure.",
    "Do not provide code or pseudocode.",
    "Do not state the bug directly.",
    "Do not reveal a solution-specific edge case.",
    "Do not follow the question with an explanation.",
)


@dataclass(frozen=True, slots=True)
class HintDecision:
    """The application response to a model hint authorization request."""

    allowed: bool
    reason: str
    hint_level: HintLevel | None = None
    constraints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"allowed": self.allowed, "reason": self.reason}
        if self.hint_level is not None:
            result["hintLevel"] = self.hint_level
        if self.allowed:
            result["constraints"] = list(self.constraints)
        return result


class HintGate:
    """Evaluate and authorize hint requests using behavioral state and monotonic time."""

    def __init__(
        self,
        *,
        warmup_seconds: float = HINT_WARMUP_SECONDS,
        cooldown_seconds: float = HINT_COOLDOWN_SECONDS,
        stuck_code_seconds: float = STUCK_CODE_SECONDS,
        unlock_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if unlock_seconds is not None:
            warmup_seconds = unlock_seconds
        self.warmup_seconds = float(warmup_seconds)
        self.unlock_seconds = self.warmup_seconds
        self.cooldown_seconds = float(cooldown_seconds)
        self.stuck_code_seconds = float(stuck_code_seconds)
        self.clock = clock

    def evaluate(
        self,
        *,
        session_running: bool,
        elapsed_seconds: float,
        last_hint_at: float | None,
        seconds_since_code_change: float,
        candidate_explicitly_requested_help: bool,
        candidate_unproductively_looping: bool = False,
        current_phase: InterviewPhase = "warmup",
        last_hint_level: int = 0,
        now: float | None = None,
    ) -> HintDecision:
        """Return whether the model may ask one constrained Socratic question."""

        if not session_running:
            return HintDecision(False, "No interview is currently running.")

        if last_hint_level >= len(HINT_LEVEL_ORDER):
            return HintDecision(
                False,
                "All available hint levels for this problem have been exhausted. Continue reasoning with the candidate.",
            )

        current_time = self.clock() if now is None else float(now)
        if last_hint_at is not None and current_time - last_hint_at < self.cooldown_seconds:
            return HintDecision(
                False,
                "A hint was recently permitted. Continue interviewing until the hint cooldown expires.",
            )

        if candidate_explicitly_requested_help:
            next_level = HINT_LEVEL_ORDER[last_hint_level]
            return HintDecision(
                True,
                "One constrained Socratic question is permitted.",
                hint_level=next_level,
                constraints=HINT_CONSTRAINTS,
            )

        if elapsed_seconds < self.warmup_seconds:
            return HintDecision(
                False,
                "Hints are currently locked during the initial warmup period. Continue as a neutral interviewer.",
            )

        if current_phase not in {"approach", "implementation", "testing"}:
            return HintDecision(
                False,
                "Unsolicited hints are not permitted during the warmup phase.",
            )

        if not candidate_unproductively_looping:
            return HintDecision(
                False,
                "Wait for an explicit request or for the candidate to unproductively loop before offering help.",
            )

        if seconds_since_code_change < self.stuck_code_seconds:
            return HintDecision(
                False,
                "Wait for an explicit request or for the candidate to remain inactive before offering help.",
            )

        next_level = HINT_LEVEL_ORDER[last_hint_level]
        return HintDecision(
            True,
            "One constrained Socratic question is permitted.",
            hint_level=next_level,
            constraints=HINT_CONSTRAINTS,
        )

