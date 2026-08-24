# Privacy

This is a personal, local application. It has no account system, cloud backend,
database, analytics, advertising, automatic updates, or third-party telemetry.

- The Firefox extension reads the current LeetCode problem and Monaco editor
  code from the active `leetcode.com/problems/*` page.
- At each interview start, the local host sends the problem to Gemini 3.7 Flash
  with Google Search grounding enabled. Search queries and public web results
  are processed by Google to verify the intended solution and generate hints.
- The local host sends the resulting private interviewer dossier, code when
  requested through the interview tools, microphone audio, and conversation
  context to the configured Gemini Live model.
- The user is responsible for accepting Google's free-tier data handling before
  using a Gemini API key with this project.
- The Gemini API key remains in the local `host/.env` file and is never sent to
  or stored by the extension.
- No raw microphone audio is written to disk.
- Local token-usage JSONL logs are written under `host/logs/`, and a readable
  speaker-labelled transcript is written under `host/transcripts/` when an
  interview ends. The private solution dossier and grounded source list are
  not written to either artifact.
- Log redaction excludes API keys, resumption handles, raw audio bytes,
  environment variables, and secret-bearing headers.
- No data is sent to OpenAI.
- The extension communicates with the host only over loopback HTTP at
  `127.0.0.1` and uses the configured port.
- The extension is intended for unlisted, self-distributed Mozilla signing and
  is not a public AMO listing.

The host is bound to `127.0.0.1`, but the user should still protect the Windows
machine and the `.env` file containing the API key.
