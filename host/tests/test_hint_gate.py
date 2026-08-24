from interviewer.hint_gate import HintGate


def test_hint_is_denied_before_unlock() -> None:
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=119,
        last_hint_at=None,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=True,
        now=119,
    )
    assert decision.allowed is False


def test_explicit_request_is_allowed_at_unlock() -> None:
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=120,
        last_hint_at=None,
        seconds_since_code_change=0,
        candidate_explicitly_requested_help=True,
        now=120,
    )
    assert decision.allowed is True
    assert len(decision.constraints) == 7


def test_hint_cooldown_is_enforced() -> None:
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=180,
        last_hint_at=160,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=True,
        now=180,
    )
    assert decision.allowed is False


def test_hint_is_allowed_after_cooldown() -> None:
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=160,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=True,
        now=200,
    )
    assert decision.allowed is True


def test_implicit_hint_requires_code_inactivity() -> None:
    gate = HintGate(unlock_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    recent = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=None,
        seconds_since_code_change=19,
        candidate_explicitly_requested_help=False,
        now=200,
    )
    idle = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=None,
        seconds_since_code_change=20,
        candidate_explicitly_requested_help=False,
        now=200,
    )
    assert recent.allowed is False
    assert idle.allowed is True

