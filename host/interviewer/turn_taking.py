"""Conservative local rules for deciding when interviewer audio may play."""

from __future__ import annotations

import re

RESPONSE_HOLD_SECONDS = 10.0

_QUESTION_START = re.compile(
    r"^(?:who|what|when|where|why|how|can|could|would|should|do|does|did|is|are|am|will|may|have|has)\b",
    re.IGNORECASE,
)
_HANDOFF_PHRASES = (
    "i'm done",
    "i am done",
    "that's my answer",
    "that is my answer",
    "go ahead",
    "your turn",
    "ready for feedback",
    "ready for your feedback",
    "what do you think",
    "can you respond",
    "you can respond",
)


def permits_quick_response(text: str) -> bool:
    """Return true only for an explicit question or candidate handoff."""

    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _HANDOFF_PHRASES):
        return True
    words = normalized.rstrip("?.!").split()
    if len(words) < 2:
        return False
    return normalized.endswith("?") or _QUESTION_START.match(normalized) is not None


def is_focus_exit_handoff(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "i'm done",
            "i am done",
            "ready for feedback",
            "ready for your feedback",
        )
    )
