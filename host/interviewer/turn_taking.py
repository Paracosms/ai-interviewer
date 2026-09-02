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
    "i'm finished",
    "i am finished",
    "i think i am finished",
    "i think i'm finished",
    "i think that covers it",
    "that covers it",
    "ready to test",
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

_FOCUS_DIRECT_PREFIXES = (
    "interviewer",
    "can you",
    "could you",
    "would you",
    "will you",
    "do you",
    "what do you",
    "how would you",
    "can i assume",
    "can i ask",
    "could i assume",
    "should i assume",
    "may i assume",
    "am i allowed",
    "is it okay to assume",
    "is it valid to assume",
    "does the problem",
    "what does the problem",
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


def permits_focus_response(text: str) -> bool:
    """Require an explicit question, prefix, or handoff while focusing."""

    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _HANDOFF_PHRASES):
        return True
    if any(normalized.startswith(prefix) for prefix in _FOCUS_DIRECT_PREFIXES):
        return True
    if normalized.endswith("?"):
        words = normalized.rstrip("?.!").split()
        if len(words) >= 2:
            return True
    return False
