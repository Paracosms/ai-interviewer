import json
from types import SimpleNamespace

import pytest

from interviewer.problem_analysis import (
    PROBLEM_ANALYSIS_MODEL,
    GeminiProblemAnalyzer,
    ProblemAnalysisError,
    ProblemDossier,
)


def _dossier_payload(*, confidence="high"):
    return {
        "problem_title": "Two Sum",
        "statement_summary": "Find two distinct positions whose values add up to the target value.",
        "constraint_implications": [
            "The input can be large enough that repeated full scans are too slow.",
            "The output must preserve positions, not only the selected values.",
        ],
        "analysis_confidence": confidence,
        "confidence_reason": "The supplied statement and constraints are complete and unambiguous.",
        "assumptions": [],
        "intended_solution": {
            "algorithm": "single-pass hash map",
            "summary": "Scan once while retaining prior values and looking up each needed complement.",
            "key_invariant": "The retained entries represent exactly the values seen before the current item.",
            "correctness_reasoning": "A match is found precisely when the current value has a valid earlier partner.",
            "time_complexity": "O(n)",
            "space_complexity": "O(n)",
        },
        "interviewer_checkpoints": [
            {
                "topic": "target relationship",
                "evidence_of_understanding": "The candidate connects each chosen value to the target.",
                "concern_signals": ["does not explain how a pair reaches the target"],
                "neutral_follow_up_question": "What relationship between the two values must hold?",
            },
            {
                "topic": "distinct positions",
                "evidence_of_understanding": "The candidate accounts for selecting two different positions.",
                "concern_signals": ["allows one position to be reused"],
                "neutral_follow_up_question": "How does your approach keep the selected positions distinct?",
            },
            {
                "topic": "complexity",
                "evidence_of_understanding": "The candidate relates each operation to the input size.",
                "concern_signals": ["does not account for repeated scans"],
                "neutral_follow_up_question": "How does the amount of work grow with the input?",
            },
        ],
        "common_wrong_turns": [
            "reuses the current position as both members of the pair",
            "returns values when the statement requires positions",
        ],
        "hint_ladder": [
            {
                "order": 1,
                "diagnostic_target": "open_probe",
                "when_to_use": "The candidate has not clearly restated what must be returned.",
                "socratic_question": "What exactly must your result identify?",
            },
            {
                "order": 2,
                "diagnostic_target": "test_case",
                "when_to_use": "The candidate is searching without using the target relationship.",
                "socratic_question": "What relationship would let one value complete another?",
            },
            {
                "order": 3,
                "diagnostic_target": "architectural_nudge",
                "when_to_use": "The candidate repeats work over values already considered.",
                "socratic_question": "What information from earlier positions could you retain?",
            },
        ],
    }


def dossier_json(**overrides):
    payload = _dossier_payload()
    payload.update(overrides)
    return json.dumps(payload)


def response_with_text(text):
    # Deliberately contains only the plain structured response fields.
    return SimpleNamespace(parsed=None, text=text)


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


class ProviderError(Exception):
    def __init__(self, status_code, message, *, status=None):
        super().__init__(message)
        self.code = status_code
        self.status = status
        self.message = message


class SequencedModels:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.mark.asyncio
async def test_analysis_makes_one_tool_free_structured_request():
    client = FakeClient(response_with_text(dossier_json()))
    analyzer = GeminiProblemAnalyzer(api_key="test", client=client)

    analysis = await analyzer.analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target under the stated constraints.",
    )

    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    assert call["model"] == PROBLEM_ANALYSIS_MODEL == "gemini-3.7-flash"
    assert "sole authoritative source" in call["contents"]
    assert "Find two indices" in call["contents"]
    assert "google search" not in call["contents"].lower()
    assert "tools" not in call

    dumped_config = call["config"].model_dump(exclude_none=True, by_alias=True)
    assert dumped_config["responseMimeType"] == "application/json"
    assert "responseSchema" in dumped_config
    assert dumped_config["thinkingConfig"]["thinkingLevel"] == "MEDIUM"
    assert dumped_config["maxOutputTokens"] == 8192
    assert "tools" not in dumped_config
    assert analysis.dossier.problem_title == "Two Sum"
    assert analysis.dossier.intended_solution.time_complexity == "O(n)"
    assert len(analysis.hint_questions) == 3


@pytest.mark.asyncio
async def test_plain_structured_response_without_candidates_or_grounding_succeeds():
    response = response_with_text(dossier_json())
    client = FakeClient(response)

    analysis = await GeminiProblemAnalyzer(api_key="test", client=client).analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target.",
    )

    assert not hasattr(response, "candidates")
    assert analysis.hint_questions[0] == "What exactly must your result identify?"


@pytest.mark.asyncio
async def test_parsed_pydantic_response_succeeds():
    dossier = ProblemDossier.model_validate_json(dossier_json())
    client = FakeClient(SimpleNamespace(parsed=dossier, text=""))

    analysis = await GeminiProblemAnalyzer(api_key="test", client=client).analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target.",
    )

    assert analysis.dossier is dossier
    assert len(client.models.calls) == 1


@pytest.mark.asyncio
async def test_invalid_json_raises_problem_analysis_error():
    analyzer = GeminiProblemAnalyzer(api_key="test", client=FakeClient(response_with_text("not json")))

    with pytest.raises(ProblemAnalysisError, match="invalid interviewer hint dossier"):
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )


@pytest.mark.asyncio
async def test_transient_503_then_success_is_retried():
    models = SequencedModels(
        [
            ProviderError(
                503,
                "This model is currently experiencing high demand.",
                status="UNAVAILABLE",
            ),
            response_with_text(dossier_json()),
        ]
    )
    failures = []
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=SimpleNamespace(models=models),
        retry_delays=(0,),
        failure_observer=failures.append,
    )

    analysis = await analyzer.analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target.",
    )

    assert len(models.calls) == 2
    assert analysis.dossier.problem_title == "Two Sum"
    assert failures == [
        {
            "operation": "generate_content",
            "model": PROBLEM_ANALYSIS_MODEL,
            "attempt": 1,
            "exceptionType": "ProviderError",
            "statusCode": 503,
            "providerMessage": "This model is currently experiencing high demand.",
            "elapsedSeconds": failures[0]["elapsedSeconds"],
        }
    ]


@pytest.mark.asyncio
async def test_repeated_503_exhausts_bounded_attempts():
    models = SequencedModels(
        [ProviderError(503, "high demand", status="UNAVAILABLE") for _ in range(3)]
    )
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=SimpleNamespace(models=models),
        retry_delays=(0, 0),
    )

    with pytest.raises(ProblemAnalysisError, match="after 3 attempts") as error:
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )

    assert len(models.calls) == 3
    assert error.value.status_code == 503
    assert error.value.attempt == 3


@pytest.mark.asyncio
async def test_429_is_retried_with_backoff():
    models = SequencedModels(
        [
            ProviderError(429, "too many requests", status="RESOURCE_EXHAUSTED"),
            response_with_text(dossier_json()),
        ]
    )
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=SimpleNamespace(models=models),
        retry_delays=(0, 0),
    )

    analysis = await analyzer.analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="Find two indices whose values sum to target.",
    )

    assert len(models.calls) == 2
    assert analysis.dossier.problem_title == "Two Sum"


@pytest.mark.asyncio
async def test_429_exhaustion_raises_problem_analysis_error():
    models = SequencedModels(
        [ProviderError(429, "too many requests", status="RESOURCE_EXHAUSTED") for _ in range(3)]
    )
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=SimpleNamespace(models=models),
        retry_delays=(0, 0),
    )

    with pytest.raises(ProblemAnalysisError, match="rate limit or project quota") as error:
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )

    assert len(models.calls) == 3
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_failure_diagnostics_redact_problem_text_and_api_key():
    problem_text = "SENSITIVE PROBLEM STATEMENT"
    models = SequencedModels(
        [ProviderError(400, f"invalid input: {problem_text}; key=test-secret")]
    )
    failures = []
    analyzer = GeminiProblemAnalyzer(
        api_key="test-secret",
        client=SimpleNamespace(models=models),
        retry_delays=(0, 0),
        failure_observer=failures.append,
    )

    with pytest.raises(ProblemAnalysisError):
        await analyzer.analyze(
            problem_slug="sensitive-problem",
            problem_title="Sensitive Problem",
            problem_text=problem_text,
        )

    assert failures[0]["providerMessage"] == (
        "invalid input: [REDACTED]; key=[REDACTED]"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["hint_ladder"].__setitem__(1, {**payload["hint_ladder"][1], "order": 3}), "consecutive"),
        (lambda payload: payload["hint_ladder"].__setitem__(0, {**payload["hint_ladder"][0], "socratic_question": "Not a question"}), "question"),
        (lambda payload: payload["hint_ladder"].__setitem__(1, {**payload["hint_ladder"][1], "socratic_question": payload["hint_ladder"][0]["socratic_question"]}), "unique"),
        (lambda payload: payload["interviewer_checkpoints"].__setitem__(0, {**payload["interviewer_checkpoints"][0], "neutral_follow_up_question": "Not a question"}), "follow-up"),
    ],
)
async def test_dossier_validation_failures_raise_problem_analysis_error(mutation, message):
    payload = _dossier_payload()
    mutation(payload)
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=FakeClient(response_with_text(json.dumps(payload))),
    )

    del message
    with pytest.raises(ProblemAnalysisError, match="invalid interviewer hint dossier"):
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )


@pytest.mark.asyncio
async def test_missing_required_field_is_schema_validation_failure():
    payload = _dossier_payload()
    del payload["intended_solution"]
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=FakeClient(response_with_text(json.dumps(payload))),
    )

    with pytest.raises(ProblemAnalysisError, match="invalid interviewer hint dossier") as error:
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )

    assert error.value.operation == "parse_problem_dossier"
    assert (
        error.value.provider_message
        == "Structured output did not match the ProblemDossier schema."
    )


@pytest.mark.asyncio
async def test_low_confidence_dossier_is_accepted():
    payload = _dossier_payload(confidence="low")
    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=FakeClient(response_with_text(json.dumps(payload))),
    )

    analysis = await analyzer.analyze(
        problem_slug="two-sum",
        problem_title="Two Sum",
        problem_text="The statement is incomplete but includes a target and input values.",
    )

    assert analysis.dossier.analysis_confidence == "low"


@pytest.mark.asyncio
async def test_rate_limit_error_is_reported_without_billing_tier_claim():
    class RateLimitError(Exception):
        status_code = 429

    class RateLimitedModels:
        def generate_content(self, **kwargs):
            del kwargs
            raise RateLimitError("too many requests")

    analyzer = GeminiProblemAnalyzer(
        api_key="test",
        client=SimpleNamespace(models=RateLimitedModels()),
        retry_delays=(0, 0),
    )

    with pytest.raises(ProblemAnalysisError, match="rate limit or project quota") as error:
        await analyzer.analyze(
            problem_slug="two-sum",
            problem_title="Two Sum",
            problem_text="Find two indices whose values sum to target.",
        )

    assert "free-tier" not in str(error.value).lower()
    assert "No Search" in str(error.value)
