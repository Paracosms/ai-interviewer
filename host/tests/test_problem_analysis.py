from types import SimpleNamespace

import pytest

from interviewer.problem_analysis import (
    PROBLEM_ANALYSIS_MODEL,
    GeminiProblemAnalyzer,
    ProblemAnalysisError,
)


def dossier_json():
    hints = [
        {
            "order": index,
            "diagnostic_target": f"candidate checkpoint {index}",
            "when_to_use": f"candidate is stuck at checkpoint {index}",
            "socratic_question": f"What information would help you at checkpoint {index}?",
        }
        for index in range(1, 6)
    ]
    return """{
      "verified_problem_title": "Two Sum",
      "problem_identity_matches": true,
      "verification_summary": "The searched sources match the supplied title, statement, and constraints.",
      "sources_agree": true,
      "source_consensus": "The sources agree that a single-pass complement lookup is the intended optimum.",
      "intended_solution": {
        "algorithm": "single-pass hash map",
        "summary": "Scan once, storing prior values and looking up the needed complement.",
        "key_invariant": "The map contains exactly the values and indices seen before the current item.",
        "correctness_reasoning": "A complement lookup finds precisely a valid earlier partner without reusing the current item.",
        "time_complexity": "O(n)",
        "space_complexity": "O(n)"
      },
      "interviewer_checkpoints": ["complement", "no reuse", "complexity"],
      "common_wrong_turns": ["same element twice", "returns values"],
      "hint_ladder": %s
    }""" % __import__("json").dumps(hints)


def response(*, grounded=True):
    metadata = None
    if grounded:
        metadata = SimpleNamespace(
            web_search_queries=["LeetCode Two Sum solution"],
            grounding_chunks=[
                SimpleNamespace(web=SimpleNamespace(title="LeetCode", uri="https://leetcode.com/two-sum")),
                SimpleNamespace(web=SimpleNamespace(title="Reference", uri="https://example.com/two-sum")),
            ],
        )
    return SimpleNamespace(
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
        parsed=None,
        text=dossier_json(),
    )


class FakeModels:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeClient:
    def __init__(self, result):
        self.models = FakeModels(result)


@pytest.mark.asyncio
async def test_analysis_makes_one_grounded_structured_request():
    client = FakeClient(response())
    analyzer = GeminiProblemAnalyzer(api_key="test", client=client)

    analysis = await analyzer.analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target.",
    )

    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    assert call["model"] == PROBLEM_ANALYSIS_MODEL == "gemini-3.7-flash"
    assert "MUST use Google Search" in call["contents"]
    dumped_config = call["config"].model_dump(exclude_none=True, by_alias=True)
    assert dumped_config["tools"] == [{"googleSearch": {}}]
    assert dumped_config["responseMimeType"] == "application/json"
    assert analysis.dossier.intended_solution.time_complexity == "O(n)"
    assert len(analysis.sources) == 2
    assert len(analysis.hint_questions) == 5


@pytest.mark.asyncio
async def test_analysis_fails_closed_when_search_was_not_used():
    client = FakeClient(response(grounded=False))
    analyzer = GeminiProblemAnalyzer(api_key="test", client=client)

    with pytest.raises(ProblemAnalysisError, match="did not verify"):
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )

    assert len(client.models.calls) == 1
