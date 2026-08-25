from interviewer.turn_taking import permits_quick_response


def test_direct_questions_and_explicit_handoffs_release_quickly() -> None:
    assert permits_quick_response("What is the expected input format?") is True
    assert permits_quick_response("Can I assume the array is sorted") is True
    assert permits_quick_response("I'm done; go ahead.") is True
    assert permits_quick_response("Ready for feedback") is True


def test_ambiguous_or_incomplete_statements_are_held() -> None:
    assert permits_quick_response("I think the next step is um") is False
    assert permits_quick_response("This loop handles the duplicate case.") is False
    assert permits_quick_response("") is False
