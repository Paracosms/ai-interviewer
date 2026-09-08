(() => {
  "use strict";

  const DEFAULT_HOST_PORT = 8765;
  const HOST_PORT_KEY = "hostPort";
  const DEFAULT_GEMINI_VOICE = "Kore";
  const GEMINI_VOICE_KEY = "geminiVoice";
  const SUPPORTED_GEMINI_VOICES = new Set([
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina",
    "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar",
    "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia",
    "Sadaltager", "Sulafat",
  ]);
  const PROTOCOL_VERSION = 1;
  const REQUEST_TIMEOUT_MS = 2500;
  const START_INTERVIEW_TIMEOUT_MS = 30000;
  const STOP_INTERVIEW_TIMEOUT_MS = 7000;
  const CODE_SOURCE_ID = `background-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const editorStates = new Map();
  const codeUpdateQueues = new Map();

  function canonicalCodePayload(payload, tabId) {
    const key = Number.isInteger(tabId) ? tabId : "unknown";
    const previous = editorStates.get(key);
    const samePage = previous?.pageUrl === payload.pageUrl;
    const changed = !samePage
      || previous.code !== payload.code
      || previous.language !== payload.language;
    const revision = changed ? ((samePage ? previous?.revision : 0) || 0) + 1 : previous.revision;
    const next = {
      pageUrl: payload.pageUrl,
      language: payload.language,
      code: payload.code,
      revision,
    };
    editorStates.set(key, next);
    return {
      ...payload,
      codeVersion: revision,
      codeSourceId: CODE_SOURCE_ID,
    };
  }

  function queueCodeUpdate(tabId, payload) {
    const key = Number.isInteger(tabId) ? tabId : "unknown";
    const previous = codeUpdateQueues.get(key) || Promise.resolve();
    const queued = previous
      .catch(() => undefined)
      .then(() => requestHost("/session/code", { method: "POST", body: payload }));
    codeUpdateQueues.set(key, queued);
    const cleanup = () => {
      if (codeUpdateQueues.get(key) === queued) {
        codeUpdateQueues.delete(key);
      }
    };
    queued.then(cleanup, cleanup);
    return queued;
  }

  function parseHostPort(value) {
    const text = String(value ?? "").trim();
    if (!/^\d+$/.test(text)) {
      return null;
    }
    const port = Number(text);
    return Number.isInteger(port) && port >= 1 && port <= 65535 ? port : null;
  }

  async function getHostPort() {
    const stored = await browser.storage.local.get(HOST_PORT_KEY);
    return parseHostPort(stored[HOST_PORT_KEY]) ?? DEFAULT_HOST_PORT;
  }

  async function saveHostPort(value) {
    const port = parseHostPort(value);
    if (port === null) {
      return {
        ok: false,
        error: "Host port must be a number between 1 and 65535.",
      };
    }
    await browser.storage.local.set({ [HOST_PORT_KEY]: port });
    return { ok: true, port };
  }

  async function getGeminiVoice() {
    const stored = await browser.storage.local.get(GEMINI_VOICE_KEY);
    const voice = stored[GEMINI_VOICE_KEY];
    return {
      ok: true,
      voice: SUPPORTED_GEMINI_VOICES.has(voice) ? voice : DEFAULT_GEMINI_VOICE,
    };
  }

  async function saveGeminiVoice(value) {
    if (!SUPPORTED_GEMINI_VOICES.has(value)) {
      return { ok: false, error: "Choose a supported Gemini voice." };
    }
    await browser.storage.local.set({ [GEMINI_VOICE_KEY]: value });
    return { ok: true, voice: value };
  }

  function getBaseUrl(port) {
    return `http://127.0.0.1:${port}`;
  }

  function hostOfflineMessage(port) {
    return `Local interviewer host is not running on port ${port}. Start run.ps1 from the repository root or check the configured Host port.`;
  }

  async function requestHost(path, { method = "GET", body, timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
    const port = await getHostPort();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${getBaseUrl(port)}${path}`, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
      });
      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = { ok: false, error: `Local host returned HTTP ${response.status}.` };
      }
      if (!response.ok) {
        return {
          ok: false,
          httpStatus: response.status,
          error: payload.error || `Local host returned HTTP ${response.status}.`,
          port,
        };
      }
      return { ...payload, httpStatus: response.status, port };
    } catch (error) {
      const message = error?.name === "AbortError"
        ? `Local interviewer host request timed out on port ${port}.`
        : hostOfflineMessage(port);
      return { ok: false, error: message, port };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function handleMessage(message, sender = {}) {
    const type = message?.type;
    if (type === "GET_HOST_PORT") {
      return { ok: true, port: await getHostPort() };
    }
    if (type === "SAVE_HOST_PORT") {
      const saved = await saveHostPort(message.port);
      if (!saved.ok) {
        return saved;
      }
      const health = await requestHost("/health");
      return { ...saved, health };
    }
    if (type === "GET_GEMINI_VOICE") {
      return getGeminiVoice();
    }
    if (type === "SAVE_GEMINI_VOICE") {
      return saveGeminiVoice(message.voice);
    }
    if (type === "HOST_HEALTH") {
      return requestHost("/health");
    }
    if (type === "GET_HOST_STATUS") {
      return requestHost("/session/status");
    }
    if (type === "GET_AUDIO_VOLUME") {
      return requestHost("/audio/volume");
    }
    if (type === "SET_AUDIO_VOLUME") {
      return requestHost("/audio/volume", { method: "POST", body: { volume: message.volume } });
    }
    if (type === "START_INTERVIEW") {
      const body = canonicalCodePayload(message.payload, message.tabId);
      return requestHost("/session/start", {
        method: "POST",
        body,
        timeoutMs: START_INTERVIEW_TIMEOUT_MS,
      });
    }
    if (type === "STOP_INTERVIEW") {
      return requestHost("/session/stop", {
        method: "POST",
        body: {},
        timeoutMs: STOP_INTERVIEW_TIMEOUT_MS,
      });
    }
    if (type === "CODE_UPDATE") {
      const payload = canonicalCodePayload(message.payload, sender.tab?.id);
      return queueCodeUpdate(sender.tab?.id, payload);
    }
    if (type === "SET_INTERACTION_MODE") {
      return requestHost("/session/mode", {
        method: "POST",
        body: { protocolVersion: PROTOCOL_VERSION, mode: message.mode },
      });
    }
    if (type === "TYPING_ACTIVITY") {
      return requestHost("/session/activity", {
        method: "POST",
        body: { protocolVersion: PROTOCOL_VERSION, activity: "typing" },
      });
    }
    return { ok: false, error: "Unknown extension message." };
  }

  browser.runtime.onMessage.addListener((message, sender) => handleMessage(message, sender));
})();
