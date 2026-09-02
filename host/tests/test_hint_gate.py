from interviewer.hint_gate import HintGate


def test_unsolicited_hint_is_denied_before_warmup() -> None:
    gate = HintGate(warmup_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=119,
        last_hint_at=None,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=False,
        candidate_unproductively_looping=True,
        current_phase="approach",
        now=119,
    )
    assert decision.allowed is False
    assert "locked during the initial warmup period" in decision.reason


def test_explicit_request_bypasses_warmup() -> None:
    gate = HintGate(warmup_seconds=240, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=10,
        last_hint_at=None,
        seconds_since_code_change=0,
        candidate_explicitly_requested_help=True,
        now=10,
    )
    assert decision.allowed is True
    assert decision.hint_level == "open_probe"
    assert len(decision.constraints) == 7


def test_hint_cooldown_is_enforced() -> None:
    gate = HintGate(warmup_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=180,
        last_hint_at=160,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=True,
        now=180,
    )
    assert decision.allowed is False
    assert "hint cooldown" in decision.reason


def test_hint_is_allowed_after_cooldown() -> None:
    gate = HintGate(warmup_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=160,
        seconds_since_code_change=999,
        candidate_explicitly_requested_help=True,
        last_hint_level=1,
        now=200,
    )
    assert decision.allowed is True
    assert decision.hint_level == "test_case"


def test_implicit_hint_requires_code_inactivity_and_looping() -> None:
    gate = HintGate(warmup_seconds=120, cooldown_seconds=30, stuck_code_seconds=20)
    recent = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=None,
        seconds_since_code_change=19,
        candidate_explicitly_requested_help=False,
        candidate_unproductively_looping=True,
        current_phase="implementation",
        now=200,
    )
    assert recent.allowed is False

    not_looping = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=None,
        seconds_since_code_change=20,
        candidate_explicitly_requested_help=False,
        candidate_unproductively_looping=False,
        current_phase="implementation",
        now=200,
    )
    assert not_looping.allowed is False

    idle_and_looping = gate.evaluate(
        session_running=True,
        elapsed_seconds=200,
        last_hint_at=None,
        seconds_since_code_change=20,
        candidate_explicitly_requested_help=False,
        candidate_unproductively_looping=True,
        current_phase="implementation",
        now=200,
    )
    assert idle_and_looping.allowed is True
    assert idle_and_looping.hint_level == "open_probe"


def test_hint_ladder_exhaustion() -> None:
    gate = HintGate(warmup_seconds=0, cooldown_seconds=0, stuck_code_seconds=0)
    decision = gate.evaluate(
        session_running=True,
        elapsed_seconds=300,
        last_hint_at=None,
        seconds_since_code_change=0,
        candidate_explicitly_requested_help=True,
        last_hint_level=3,
        now=300,
    )
    assert decision.allowed is False
    assert "exhausted" in decision.reason

