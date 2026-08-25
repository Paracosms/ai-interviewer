(() => {
  "use strict";

  const DEFAULT_HOST_PORT = 8765;
  const HOST_PORT_KEY = "hostPort";
  const PROTOCOL_VERSION = 1;
  const REQUEST_TIMEOUT_MS = 2500;
  const MAXIMUMS = Object.freeze({
    pageUrl: 2000,
    problemSlug: 200,
    problemTitle: 500,
    problemText: 100000,
    language: 100,
    code: 50000,
  });

  const tabStates = new Map();

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

  function getBaseUrl(port) {
    return `http://127.0.0.1:${port}`;
  }

  function hostOfflineMessage(port) {
    return `Local interviewer host is not running on port ${port}. Start host/run.ps1 or check the configured Host port.`;
  }

  async function requestHost(path, { method = "GET", body } = {}) {
    const port = await getHostPort();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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

  function isTextField(value, key) {
    return typeof value === "string" && value.length <= MAXIMUMS[key];
  }

  function sanitizePageState(value) {
    if (!value || typeof value !== "object") {
      return null;
    }
    const result = {
      protocolVersion: PROTOCOL_VERSION,
      generation: Number.isInteger(value.generation) ? value.generation : 0,
      pageUrl: value.pageUrl,
      problemSlug: value.problemSlug,
      problemTitle: value.problemTitle,
      problemText: value.problemText,
      language: value.language,
      code: value.code,
      codeVersion: value.codeVersion,
      error: value.error ?? null,
      detected: value.detected === true,
    };
    for (const key of ["pageUrl", "problemSlug", "problemTitle", "problemText", "language", "code"]) {
      if (result[key] !== null && result[key] !== undefined && !isTextField(result[key], key)) {
        return null;
      }
    }
    if (!Number.isInteger(result.codeVersion) || result.codeVersion < 0) {
      return null;
    }
    if (result.error !== null && typeof result.error !== "string") {
      return null;
    }
    return result;
  }

  async function handleMessage(message, sender) {
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
    if (type === "PAGE_STATE_UPDATE") {
      const tabId = sender?.tab?.id;
      const pageState = sanitizePageState(message.payload);
      if (!Number.isInteger(tabId) || pageState === null) {
        return { ok: false, error: "Invalid LeetCode page state." };
      }
      tabStates.set(tabId, pageState);
      return { ok: true };
    }
    if (type === "GET_PAGE_STATE") {
      const state = tabStates.get(message.tabId);
      return { ok: true, pageState: state ?? null };
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
      return requestHost("/session/start", { method: "POST", body: message.payload });
    }
    if (type === "STOP_INTERVIEW") {
      return requestHost("/session/stop", { method: "POST", body: {} });
    }
    if (type === "CODE_UPDATE") {
      return requestHost("/session/code", { method: "POST", body: message.payload });
    }
    return { ok: false, error: "Unknown extension message." };
  }

  browser.runtime.onMessage.addListener((message, sender) => handleMessage(message, sender));
  browser.tabs.onRemoved.addListener((tabId) => tabStates.delete(tabId));
})();
