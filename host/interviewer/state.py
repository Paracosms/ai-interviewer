"""Authoritative, in-memory interview state shared by the host components."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum

from .hint_gate import HINT_WARMUP_SECONDS, HintGate, InterviewPhase

_LEETCODE_PROBLEM_SLUG_RE = re.compile(
    r"/problems/([^/?#]+)",
    re.IGNORECASE,
)


def extract_problem_slug(url: str) -> str:
    """Extract canonical slug from any LeetCode problem URL, tab, or submission."""
    match = _LEETCODE_PROBLEM_SLUG_RE.search(str(url or "").strip())
    return match.group(1).lower() if match else ""


class InterviewStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    ERROR = "error"


class InteractionMode(str, Enum):
    CONVERSATION = "conversation"
    FOCUS = "focus"


class StateError(ValueError):
    """Raised when an operation would make interview state inconsistent."""


class ProblemChangedError(StateError):
    """Raised when a browser update belongs to another LeetCode problem."""


class CodeUpdateResult(str, Enum):
    APPLIED = "applied"
    RESYNCHRONIZED = "resynchronized"
    LANGUAGE_UPDATED = "language_updated"
    IGNORED_DUPLICATE = "ignored_duplicate"
    IGNORED_OLDER = "ignored_older"


@dataclass(slots=True)
class InterviewState:
    """The single mutable interview state owned by the local host."""

    status: InterviewStatus = InterviewStatus.STOPPED
    started_at_monotonic: float | None = None
    problem_url: str | None = None
    problem_title: str | None = None
    language: str | None = None
    code: str | None = None
    code_version: int = 0
    code_source_id: str | None = None
    last_code_change_at: float | None = None
    last_hint_at: float | None = None
    gemini_connected: bool = False
    last_error: str | None = None
    problem_analysis_status: str = "unavailable"
    problem_analysis_error: str | None = None
    interaction_mode: InteractionMode = InteractionMode.CONVERSATION
    interview_phase: InterviewPhase = "warmup"
    last_hint_level: int = 0
    typing_active_until: float = 0.0
    code_sync_status: str = "connected"

    @property
    def is_active(self) -> bool:
        return self.status in {
            InterviewStatus.STARTING,
            InterviewStatus.RUNNING,
            InterviewStatus.RECONNECTING,
            InterviewStatus.STOPPING,
        }

    def mark_typing_activity(self, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else float(now)
        self.typing_active_until = timestamp + 1.5

    def candidate_is_typing(self, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else float(now)
        return timestamp < self.typing_active_until

    def mark_code_sync_disconnected(self) -> None:
        self.code_sync_status = "disconnected"

    def current_interview_phase(self, now: float | None = None) -> InterviewPhase:
        if self.interview_phase == "warmup" and self.elapsed_seconds(now=now) >= HINT_WARMUP_SECONDS:
            return "approach"
        return self.interview_phase

    def begin(
        self,
        *,
        page_url: str,
        problem_title: str,
        language: str,
        code: str,
        code_version: int,
        code_source_id: str | None = None,
        now: float | None = None,
    ) -> None:
        if self.is_active:
            raise StateError("An interview is already active.")
        if code_version < 0:
            raise StateError("code_version must be nonnegative.")

        timestamp = time.monotonic() if now is None else float(now)
        self.status = InterviewStatus.STARTING
        self.started_at_monotonic = timestamp
        self.problem_url = page_url
        self.problem_title = problem_title
        self.language = language
        self.code = code
        self.code_version = code_version
        self.code_source_id = code_source_id
        self.last_code_change_at = timestamp
        self.last_hint_at = None
        self.gemini_connected = False
        self.last_error = None
        self.problem_analysis_status = "pending"
        self.problem_analysis_error = None
        self.interaction_mode = InteractionMode.CONVERSATION
        self.interview_phase = "warmup"
        self.last_hint_level = 0
        self.typing_active_until = 0.0
        self.code_sync_status = "connected"

    def mark_running(self, *, gemini_connected: bool = True) -> None:
        if self.status not in {InterviewStatus.STARTING, InterviewStatus.RECONNECTING}:
            raise StateError(
                f"Cannot mark an interview in {self.status.value} state as running."
            )
        self.status = InterviewStatus.RUNNING
        self.gemini_connected = gemini_connected
        self.last_error = None

    def mark_reconnecting(self) -> None:
        if self.status is not InterviewStatus.RUNNING:
            raise StateError(
                f"Cannot reconnect an interview in {self.status.value} state."
            )
        self.status = InterviewStatus.RECONNECTING
        self.gemini_connected = False

    def mark_stopping(self) -> None:
        if self.is_active:
            self.status = InterviewStatus.STOPPING
            self.gemini_connected = False

    def mark_error(self, message: str) -> None:
        self.status = InterviewStatus.ERROR
        self.gemini_connected = False
        self.last_error = message

    def mark_problem_analysis_ready(self) -> None:
        self.problem_analysis_status = "ready"
        self.problem_analysis_error = None

    def mark_problem_analysis_error(self, message: str) -> None:
        self.problem_analysis_status = "error"
        self.problem_analysis_error = message

    def update_code(
        self,
        *,
        page_url: str,
        language: str,
        code: str,
        code_version: int,
        code_source_id: str | None = None,
        now: float | None = None,
    ) -> CodeUpdateResult:
        if self.problem_url is None:
            raise StateError("No interview problem has been started.")
        if not self.is_active:
            raise StateError("No interview is currently running.")
        incoming_slug = extract_problem_slug(page_url)
        current_slug = extract_problem_slug(self.problem_url) if self.problem_url else ""
        is_same_problem = (
            incoming_slug == current_slug
            if (incoming_slug and current_slug)
            else (page_url == self.problem_url)
        )
        if not is_same_problem:
            self.code_sync_status = "disconnected"
            raise ProblemChangedError("The active LeetCode problem changed. Stop and restart the interview.")
        self.code_sync_status = "connected"
        self.problem_url = page_url
        if code_version < 0:
            raise StateError("code_version must be nonnegative.")
        source_changed = bool(
            code_source_id
            and self.code_source_id
            and code_source_id != self.code_source_id
        )
        if code_version < self.code_version and not source_changed:
            return CodeUpdateResult.IGNORED_OLDER

        timestamp = time.monotonic() if now is None else float(now)
        if code_version == self.code_version and not source_changed:
            if language != self.language:
                self.language = language
                return CodeUpdateResult.LANGUAGE_UPDATED
            return CodeUpdateResult.IGNORED_DUPLICATE

        code_changed = code != self.code
        self.language = language
        self.code = code
        self.code_version = code_version
        if code_source_id:
            self.code_source_id = code_source_id
        if code_changed:
            self.last_code_change_at = timestamp
            self.interview_phase = "implementation"
            self.code_sync_status = "connected"
        return CodeUpdateResult.RESYNCHRONIZED if source_changed else CodeUpdateResult.APPLIED

    def set_interaction_mode(self, mode: str | InteractionMode) -> InteractionMode:
        if not self.is_active:
            raise StateError("No interview is currently running.")
        try:
            resolved = mode if isinstance(mode, InteractionMode) else InteractionMode(mode)
        except ValueError as exc:
            raise StateError("Interaction mode must be conversation or focus.") from exc
        if self.interaction_mode == InteractionMode.FOCUS and resolved == InteractionMode.CONVERSATION:
            self.interview_phase = "testing"
        self.interaction_mode = resolved
        return resolved

    def stop(self, *, error: str | None = None) -> None:
        """Clear live interview context after the session has been stopped."""

        self.status = InterviewStatus.STOPPED
        self.started_at_monotonic = None
        self.problem_url = None
        self.problem_title = None
        self.language = None
        self.code = None
        self.code_version = 0
        self.code_source_id = None
        self.last_code_change_at = None
        self.last_hint_at = None
        self.gemini_connected = False
        self.last_error = error
        self.problem_analysis_status = "unavailable"
        self.problem_analysis_error = None
        self.interaction_mode = InteractionMode.CONVERSATION
        self.interview_phase = "warmup"
        self.last_hint_level = 0
        self.typing_active_until = 0.0
        self.code_sync_status = "connected"

    def elapsed_seconds(self, *, now: float | None = None) -> float:
        if self.started_at_monotonic is None:
            return 0.0
        timestamp = time.monotonic() if now is None else float(now)
        return max(0.0, timestamp - self.started_at_monotonic)

    def seconds_since_code_change(self, *, now: float | None = None) -> float:
        if self.last_code_change_at is None:
            return 0.0
        timestamp = time.monotonic() if now is None else float(now)
        return max(0.0, timestamp - self.last_code_change_at)

    def hints_eligible(self, gate: HintGate, *, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else float(now)
        decision = gate.evaluate(
            session_running=self.status == InterviewStatus.RUNNING,
            elapsed_seconds=self.elapsed_seconds(now=timestamp),
            last_hint_at=self.last_hint_at,
            seconds_since_code_change=self.seconds_since_code_change(now=timestamp),
            candidate_explicitly_requested_help=True,
            current_phase=self.current_interview_phase(now=timestamp),
            last_hint_level=self.last_hint_level,
            now=timestamp,
        )
        return decision.allowed

    def public_snapshot(
        self,
        *,
        model: str,
        hint_gate: HintGate,
        now: float | None = None,
    ) -> dict[str, object]:
        timestamp = time.monotonic() if now is None else float(now)
        return {
            "ok": True,
            "protocolVersion": 1,
            "running": self.is_active,
            "status": self.status.value,
            "elapsedSeconds": int(self.elapsed_seconds(now=timestamp)),
            "hintsEligible": self.hints_eligible(hint_gate, now=timestamp),
            "geminiConnected": self.gemini_connected,
            "problemTitle": self.problem_title,
            "language": self.language,
            "codeVersion": self.code_version if self.problem_url else None,
            "secondsSinceCodeChange": int(self.seconds_since_code_change(now=timestamp)),
            "model": model,
            "lastError": self.last_error,
            "problemAnalysisStatus": self.problem_analysis_status,
            "problemAnalysisError": self.problem_analysis_error,
            "interactionMode": self.interaction_mode.value,
            "interviewPhase": self.current_interview_phase(now=timestamp),
            "codeSyncStatus": self.code_sync_status,
        }
