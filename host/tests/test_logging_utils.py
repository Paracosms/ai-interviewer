import json
import re
from datetime import datetime
from pathlib import Path

from interviewer.logging_utils import SessionJsonLogger
from interviewer.transcript_utils import generate_transcript, transcript_filename


def test_session_log_uses_machine_local_timestamps(tmp_path: Path) -> None:
    logger = SessionJsonLogger(tmp_path / "logs")
    path = logger.start(now=0)
    logger.log("test_event")

    record = json.loads(path.read_text(encoding="utf-8"))
    parsed_timestamp = datetime.fromisoformat(record["timestamp"])
    assert parsed_timestamp.tzinfo is not None
    assert parsed_timestamp.utcoffset() == datetime.now().astimezone().utcoffset()
    assert re.fullmatch(
        r"interview-\d{8}T\d{6}[+-]\d{4}-[0-9a-f]{8}\.jsonl", path.name
    )


def test_transcript_uses_first_timestamp_and_groups_transcription_chunks(
    tmp_path: Path,
) -> None:
    log = tmp_path / "logs" / "interview-20260824T081244Z-4dfbaff8.jsonl"
    log.parent.mkdir()
    log.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-08-24T08:40:24.077787Z","event":"session_resumption_updated","payload":{"resumable":true}}',
                '{"timestamp":"2026-08-24T08:40:26.383099Z","event":"input_transcript","payload":{"text":"Wait, repeat that."}}',
                '{"timestamp":"2026-08-24T08:40:26.391785Z","event":"output_transcript","payload":{"text":"Your two"}}',
                '{"timestamp":"2026-08-24T08:40:26.409008Z","event":"output_transcript","payload":{"text":" pointers"}}',
                '{"timestamp":"2026-08-24T08:40:26.446793Z","event":"output_transcript","payload":{"text":" move"}}',
                '{"timestamp":"2026-08-24T08:40:26.505472Z","event":"output_transcript","payload":{"text":" toward"}}',
                '{"timestamp":"2026-08-24T08:40:26.611093Z","event":"output_transcript","payload":{"text":" each other,"}}',
                '{"timestamp":"2026-08-24T08:40:26.707176Z","event":"output_transcript","payload":{"text":" removing"}}',
                '{"timestamp":"2026-08-24T08:40:27.340385Z","event":"session_resumption_updated","payload":{"resumable":true}}',
                '{"timestamp":"2026-08-24T08:40:27.366259Z","event":"output_transcript","payload":{"text":" prices"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" from consideration."}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" Is it"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" possible"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" that the"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" best"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" pair"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" is in"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" the middle"}}',
                '{"timestamp":"2026-08-24T08:40:27.546087Z","event":"output_transcript","payload":{"text":" and gets"}}',
                '{"timestamp":"2026-08-24T08:40:28.564067Z","event":"output_transcript","payload":{"text":" missed?"}}',
                '{"timestamp":"2026-08-24T08:40:43.170808Z","event":"input_transcript","payload":{"text":"Because we keep searching until until the pointers meet in the middle."}}',
                '{"timestamp":"2026-08-24T08:40:43.388889Z","event":"output_transcript","payload":{"text":"Understood, your"}}',
                '{"timestamp":"2026-08-24T08:40:44.326723Z","event":"output_transcript","payload":{"text":" pointers"}}',
                '{"timestamp":"2026-08-24T08:40:44.414281Z","event":"output_transcript","payload":{"text":" will meet."}}',
                '{"timestamp":"2026-08-24T08:40:44.545822Z","event":"output_transcript","payload":{"text":" Consider"}}',
                '{"timestamp":"2026-08-24T08:40:44.834743Z","event":"output_transcript","payload":{"text":" how your"}}',
                '{"timestamp":"2026-08-24T08:40:45.085446Z","event":"output_transcript","payload":{"text":" criteria"}}',
                '{"timestamp":"2026-08-24T08:40:45.123326Z","event":"output_transcript","payload":{"text":" for moving"}}',
                '{"timestamp":"2026-08-24T08:40:45.211044Z","event":"output_transcript","payload":{"text":" them"}}',
                '{"timestamp":"2026-08-24T08:40:45.345370Z","event":"output_transcript","payload":{"text":" handles"}}',
                '{"timestamp":"2026-08-24T08:40:45.358505Z","event":"output_transcript","payload":{"text":" different"}}',
                '{"timestamp":"2026-08-24T08:40:45.437479Z","event":"output_transcript","payload":{"text":" kinds"}}',
                '{"timestamp":"2026-08-24T08:40:45.501322Z","event":"output_transcript","payload":{"text":" of price"}}',
                '{"timestamp":"2026-08-24T08:40:45.638946Z","event":"output_transcript","payload":{"text":" trends,"}}',
                '{"timestamp":"2026-08-24T08:40:45.773484Z","event":"output_transcript","payload":{"text":" like"}}',
                '{"timestamp":"2026-08-24T08:40:45.841784Z","event":"output_transcript","payload":{"text":" when the"}}',
                '{"timestamp":"2026-08-24T08:40:46.001399Z","event":"output_transcript","payload":{"text":" prices"}}',
                '{"timestamp":"2026-08-24T08:40:46.127838Z","event":"output_transcript","payload":{"text":" are rising"}}',
                '{"timestamp":"2026-08-24T08:40:46.296216Z","event":"output_transcript","payload":{"text":" or falling"}}',
                '{"timestamp":"2026-08-24T08:40:46.379627Z","event":"output_transcript","payload":{"text":" sharply"}}',
                '{"timestamp":"2026-08-24T08:40:46.581693Z","event":"output_transcript","payload":{"text":" versus"}}',
                '{"timestamp":"2026-08-24T08:40:46.622240Z","event":"output_transcript","payload":{"text":" when they\\u0027re"}}',
                '{"timestamp":"2026-08-24T08:40:46.696604Z","event":"output_transcript","payload":{"text":" fluctuating."}}',
                '{"timestamp":"2026-08-24T08:40:47.021210Z","event":"output_transcript","payload":{"text":" Is there"}}',
                '{"timestamp":"2026-08-24T08:40:47.137015Z","event":"output_transcript","payload":{"text":" anything"}}',
                '{"timestamp":"2026-08-24T08:40:47.226975Z","event":"output_transcript","payload":{"text":" you\'d want"}}',
                '{"timestamp":"2026-08-24T08:40:47.305547Z","event":"output_transcript","payload":{"text":" to change"}}',
                '{"timestamp":"2026-08-24T08:40:47.367571Z","event":"output_transcript","payload":{"text":" about"}}',
                '{"timestamp":"2026-08-24T08:40:47.466948Z","event":"output_transcript","payload":{"text":" how you"}}',
                '{"timestamp":"2026-08-24T08:40:47.523649Z","event":"output_transcript","payload":{"text":" decide"}}',
                '{"timestamp":"2026-08-24T08:40:47.573463Z","event":"output_transcript","payload":{"text":" which"}}',
                '{"timestamp":"2026-08-24T08:40:47.712230Z","event":"output_transcript","payload":{"text":" pointer"}}',
                '{"timestamp":"2026-08-24T08:40:47.738880Z","event":"output_transcript","payload":{"text":" to move?"}}',
                '{"timestamp":"2026-08-24T08:40:48.241571Z","event":"session_resumption_updated","payload":{"resumable":true}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert transcript_filename(log) == "08-24-2026---08:12.txt"
    transcript = generate_transcript(log, tmp_path / "transcripts")
    assert transcript.suffix == ".txt"
    expected = (
        "This transcript is based off the log: interview-20260824T081244Z-4dfbaff8.jsonl\n\n"
        "Andrew - 8:40:26\n\n"
        "Wait, repeat that.\n\n"
        "Interviewer - 8:40:26\n\n"
        "Your two pointers move toward each other, removing prices from consideration. Is it possible that the best pair is in the middle and gets missed?\n\n"
        "Andrew - 8:40:43\n\n"
        "Because we keep searching until until the pointers meet in the middle.\n\n"
        "Interviewer - 8:40:43\n\n"
        "Understood, your pointers will meet. Consider how your criteria for moving them handles different kinds of price trends, like when the prices are rising or falling sharply versus when they're fluctuating. Is there anything you'd want to change about how you decide which pointer to move?\n"
    )
    assert transcript.read_text(encoding="utf-8") == expected
    assert "session_resumption_updated" not in transcript.read_text(encoding="utf-8")
