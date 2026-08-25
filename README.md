# LeetCode AI Interviewer

A focused Windows-only MVP for a voice-based LeetCode mock interview. The
project follows the implementation brief in
`C:\Users\Andrew\Downloads\Project_Overview.md`.

The application has two local pieces:

- `extension/`: a Mozilla-signed, self-distributed Firefox WebExtension that
  reads the active LeetCode problem and complete Monaco editor buffer;
- `host/`: a Python localhost application that owns audio, Gemini Live,
  web-grounded problem analysis, interview state, timing, hint authorization,
  and JSONL session logs.

The host binds only to `127.0.0.1`. The extension and host must use the same
configurable port, defaulting to `8765`.

## Requirements

- Windows
- Desktop Firefox 142 or newer
- Python 3.11 or newer
- Node.js/npm for Mozilla's `web-ext` CLI
- A Google AI Studio Gemini API key with free-tier access
- Headphones or a headset

At every interview start, the host makes exactly one request to the fixed
`gemini-3.7-flash` model. That request uses Google Search grounding and a
structured schema to verify the intended solution and prepare a progressive
Socratic hint ladder. It runs concurrently with the configured Gemini Live
voice session, so it does not delay interview startup. There is no alternate
analysis model or silent fallback, and the application never makes an OpenAI
request.

## First-time host setup

```powershell
cd host
.\setup.ps1
```

Edit `host/.env` and add the key. The default configuration is:

```dotenv
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_VOICE=Kore
LOCAL_HOST=127.0.0.1
LOCAL_PORT=8765
AUDIO_INPUT_DEVICE=
AUDIO_OUTPUT_DEVICE=
LOG_LEVEL=INFO
```

If port `8765` is occupied, set another value such as `LOCAL_PORT=8766`. The
host will not select another port automatically.

Optionally list available PortAudio devices:

```powershell
.\.venv\Scripts\python.exe -m interviewer --list-audio-devices
```

Set `AUDIO_INPUT_DEVICE` and `AUDIO_OUTPUT_DEVICE` to a device ID or name only
when Windows defaults are not appropriate.

## Start the host

```powershell
cd host
.\run.ps1
```

Expected output reflects the actual configured port:

```text
LeetCode AI Interviewer host
Listening on http://127.0.0.1:8765
Model: gemini-3.1-flash-live-preview
Audio input: Windows default
Audio output: Windows default
Status: ready
```

Use headphones or a headset. Speakerphone mode is not supported in the MVP and
acoustic echo cancellation is intentionally not implemented.

For an audio-only development check before browser integration:

```powershell
.\.venv\Scripts\python.exe -m interviewer --terminal-spike
```

This uses the editable `host/interviewer_prompt.txt` with a sample problem and
requires a working API key and audio setup.

## Build and sign the Firefox extension

Install Mozilla's build tool once:

```powershell
npm install --global web-ext
```

Build from the repository root:

```powershell
.\extension\scripts\build.ps1
```

The script generates readable source artifacts under
`extension/dist/leetcode_ai_interviewer-0.1.7.zip`, runs `web-ext lint`, and
keeps the stable Gecko ID:

```text
leetcode-ai-interviewer@local.invalid
```

Use the real Mozilla signing flow for release Firefox:

1. Open the Mozilla Add-ons Developer Hub.
2. Upload the generated ZIP.
3. Choose self-distribution / **On your own**.
4. Download the signed `.xpi`.
5. Open the signed `.xpi` in normal release Firefox and approve installation.
6. Use that signed installation for browser integration testing.

Do not use `about:debugging` temporary add-ons, `web-ext run`, or an unsigned
release Firefox installation. Any extension-code change requires a version
increment, rebuild, and newly signed XPI. Host-only Python changes and port
changes do not require re-signing.

## Configure the extension port

Open the extension popup and set **Host port** to the same value as
`LOCAL_PORT` in `host/.env`, then press **Save**. The value is stored in
`browser.storage.local`; changing it does not require rebuilding or signing the
extension.

## Run an interview

1. Wear headphones.
2. Start `host/run.ps1`.
3. Open a LeetCode problem in Firefox.
4. Wait for the problem description and editor to load.
5. Open the signed extension popup.
6. Confirm **Local host: Connected**.
7. Confirm the detected title, language, and code length.
8. Click **Start Interview**. The voice interview starts immediately while the
   host verifies the intended solution and prepares private hints in the
   background.
9. Adjust **Speaker volume** in the extension popup at any time, including while
   the interviewer is speaking.
10. Speak naturally and interrupt the interviewer when needed.
11. Edit code normally in LeetCode; debounced full-buffer updates go to the
    localhost host.
12. Click **Stop Interview** when finished.

The host sends the problem to Gemini 3.7 Flash with Google Search enabled while
the Live interviewer begins its greeting and neutral opening questions. The
analysis requires structured output, evidence that search ran, and at least two
distinct grounded web sources. Once ready, the private verified solution,
evaluation checkpoints, and hint ladder become available to the Live
interviewer through its existing tools. Until then, solution-specific judgments
and hints are prohibited. The hint timer and tool gate still control whether the
interviewer may use a verified hint.

If background analysis fails, the voice interview continues, but verified hints
and solution-specific evaluation remain unavailable. The popup and session
status report the analysis failure separately from the Live session status.

The host sends the problem, current code when requested by the model tool,
microphone audio, private interviewer dossier, and conversation context to
Gemini. The Live session enables server VAD, input/output transcription, native
audio, interruption, context-window compression, and session resumption. One
JSONL log with machine-local timestamps is written under `host/logs/` per
interview; the private solution dossier, API keys, resumption handles, and raw
audio are not logged. When the interview ends, the latest JSONL log is converted
to a readable speaker-labelled transcript under `host/transcripts/`. The
logical transcript name follows `MM-DD-YYYY---HH:MM` using the timestamp in the
log filename. Windows does not permit `:` in a normal filename, so Windows
writes the minute separator as `-` on disk (for example,
`08-24-2026---08-12`).

## Tests and checks

From the repository root:

```powershell
python -m pytest -q
node --test tests\extension_*.test.js
node --check extension\background.js
node --check extension\content.js
node --check extension\page_bridge.js
node --check extension\popup\popup.js
```

The Python tests cover state versioning, port/configuration validation,
localhost endpoints, the single grounded analysis request, dossier validation,
hint timing, tool authorization, audio buffering and device failure, Live
configuration, interruption handling, usage logging, logging redaction,
transcript formatting and shutdown generation, and mocked session renewal. The
extension tests verify
problem extraction failure/success, complete code payloads, bridge-message
validation, default port `8765`, port validation and storage, host-offline
messaging, and that subsequent requests use the saved port.

## Manual release validation

After installing the Mozilla-signed XPI in release Firefox, verify one Python
problem and one Java problem, comments and off-screen code, a language switch,
LeetCode SPA navigation, host offline/restart, default and alternate ports,
and an intentionally incorrect then corrected extension port. Run the voice
checks before 20 minutes (direct requests for an algorithm, code, or the
answer must be redirected), an eligible post-20-minute request (exactly one
short Socratic question), interruption while model audio is playing, and a
25–30 minute session crossing a normal Live connection renewal. These checks
require the user's Gemini API key and signed XPI installation; the automated
suite uses fake Live sessions and cannot prove external service behavior.

## Known limitations

1. Firefox and LeetCode only.
2. The user must wear headphones or a headset.
3. LeetCode DOM or editor changes may require selector updates.
4. The configured Gemini Live model is a preview model and its identifier or
   availability may change. The analysis model is fixed to stable
   `gemini-3.7-flash`.
5. The application stops when Live session quota is unavailable. If analysis or
   Google Search grounding quota is unavailable, the interview continues in
   neutral mode without verified hints. Search can have separate billing or
   quota.
6. No run-result or test-result awareness exists.
7. No post-interview report exists.
8. Online grounding and multi-source validation reduce solution errors but
   cannot mathematically guarantee that every generated dossier is correct.
9. No theoretical guarantee can prevent every possible model-policy violation,
   although the private dossier, timer, tool gate, prompt rules, and acceptance
   tests substantially constrain assistance.
10. Only one interview can run at a time.
11. Changing to another LeetCode problem requires stopping and starting a new
    interview.
12. The localhost host and Firefox extension must be configured with the same
    port.
13. There is no automatic port discovery in the MVP.
