from pathlib import Path

import pytest

from interviewer.config import ConfigurationError, load_config, parse_local_port
from interviewer.http_api import validate_code_payload, validate_start_payload


def test_unknown_protocol_version_is_rejected() -> None:
    with pytest.raises(Exception, match="Unsupported protocol version"):
        validate_code_payload(
            {
                "protocolVersion": 99,
                "pageUrl": "https://leetcode.com/problems/two-sum/",
                "language": "python3",
                "code": "pass",
                "codeVersion": 1,
            }
        )


def test_oversized_code_is_rejected() -> None:
    with pytest.raises(Exception, match="code exceeds"):
        validate_start_payload(
            {
                "protocolVersion": 1,
                "pageUrl": "https://leetcode.com/problems/two-sum/",
                "problemSlug": "two-sum",
                "problemTitle": "Two Sum",
                "problemText": "x" * 200,
                "language": "python3",
                "code": "x" * 50_001,
                "codeVersion": 1,
            }
        )


def test_non_leetcode_page_url_is_rejected() -> None:
    with pytest.raises(Exception, match="HTTPS LeetCode problem URL"):
        validate_code_payload(
            {
                "protocolVersion": 1,
                "pageUrl": "https://example.com/problems/two-sum/",
                "language": "python3",
                "code": "pass",
                "codeVersion": 1,
            }
        )


def test_invalid_local_port_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="LOCAL_PORT"):
        parse_local_port("65536")


def test_invalid_log_level_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=LOUD\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        load_config(env_file, environ={"GEMINI_API_KEY": "test-key"})


def test_missing_api_key_has_actionable_message(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_PORT=8765\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY is missing from host/.env"):
        load_config(env_file, environ={}, require_api_key=True)
