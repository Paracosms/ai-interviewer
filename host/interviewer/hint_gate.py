"""Application-owned timing rules for the one-question hint boundary."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

HINT_UNLOCK_SECONDS = 20 * 60
HINT_COOLDOWN_SECONDS = 5 * 60
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
    constraints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"allowed": self.allowed, "reason": self.reason}
        if self.allowed:
            result["constraints"] = list(self.constraints)
        return result


class HintGate:
    """Evaluate and authorize hint requests using monotonic time values."""

    def __init__(
        self,
        *,
        unlock_seconds: float = HINT_UNLOCK_SECONDS,
        cooldown_seconds: float = HINT_COOLDOWN_SECONDS,
        stuck_code_seconds: float = STUCK_CODE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.unlock_seconds = float(unlock_seconds)
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
        now: float | None = None,
    ) -> HintDecision:
        """Return whether the model may ask one constrained Socratic question."""

        if not session_running:
            return HintDecision(False, "No interview is currently running.")

        if elapsed_seconds < self.unlock_seconds:
            return HintDecision(
                False,
                "Hints are currently locked. Continue as a neutral interviewer without revealing assistance.",
            )

        current_time = self.clock() if now is None else float(now)
        if last_hint_at is not None and current_time - last_hint_at < self.cooldown_seconds:
            return HintDecision(
                False,
                "A hint was recently permitted. Continue interviewing until the hint cooldown expires.",
            )

        if (
            not candidate_explicitly_requested_help
            and seconds_since_code_change < self.stuck_code_seconds
        ):
            return HintDecision(
                False,
                "Wait for an explicit request or for the candidate to remain inactive before offering help.",
            )

        return HintDecision(True, "One constrained Socratic question is permitted.", HINT_CONSTRAINTS)

