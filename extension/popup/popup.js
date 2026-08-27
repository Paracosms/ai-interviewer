(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TIMER_TICK_INTERVAL_MS = 250;
  const STATUS_REFRESH_INTERVAL_MS = 5000;
  const elements = {
    port: $("host-port"),
    savePort: $("save-port"),
    portMessage: $("port-message"),
    volume: $("volume"),
    volumeValue: $("volume-value"),
    volumeMessage: $("volume-message"),
    voice: $("voice"),
    voiceMessage: $("voice-message"),
    hostStatus: $("host-status"),
    problemStatus: $("problem-status"),
    problemTitle: $("problem-title"),
    language: $("language"),
    codeLength: $("code-length"),
    interviewStatus: $("interview-status"),
    interactionMode: $("interaction-mode"),
    elapsed: $("elapsed"),
    hintStatus: $("hint-status"),
    lastError: $("last-error"),
    start: $("start-interview"),
    stop: $("stop-interview"),
    toggleFocus: $("toggle-focus"),
    refresh: $("refresh-status"),
    actionMessage: $("action-message"),
  };

  let activeTabId = null;
  let hostHealth = { ok: false };
  let hostStatus = { ok: false, status: "stopped" };
  let pageState = null;
  let elapsedBaseSeconds = null;
  let elapsedSyncedAt = null;
  let statusRefreshPromise = null;
  let volumeEditing = false;
  let volumeRequestTimer = null;
  let voiceEditing = false;

  function showMessage(element, text = "") {
    element.textContent = text;
  }

  function formatElapsed(seconds) {
    if (!Number.isFinite(seconds)) {
      return "—";
    }
    const total = Math.max(0, Math.floor(seconds));
    const minutes = Math.floor(total / 60);
    const remainder = String(total % 60).padStart(2, "0");
    return `${minutes}:${remainder}`;
  }

  function monotonicNow() {
    return typeof performance !== "undefined" && typeof performance.now === "function"
      ? performance.now()
      : Date.now();
  }

  function updateHostStatus(nextStatus) {
    hostStatus = nextStatus || { ok: false, status: "stopped" };
    if (hostStatus.running && Number.isFinite(hostStatus.elapsedSeconds)) {
      elapsedBaseSeconds = hostStatus.elapsedSeconds;
      elapsedSyncedAt = monotonicNow();
    } else {
      elapsedBaseSeconds = null;
      elapsedSyncedAt = null;
    }
  }

  function displayedElapsedSeconds() {
    if (elapsedBaseSeconds === null || elapsedSyncedAt === null) {
      return hostStatus.elapsedSeconds;
    }
    return elapsedBaseSeconds + Math.max(0, monotonicNow() - elapsedSyncedAt) / 1000;
  }

  function problemDetected() {
    return pageState?.detected === true;
  }

  function render() {
    const port = elements.port.value || "configured port";
    elements.hostStatus.textContent = hostHealth.ok
      ? `Connected on ${hostHealth.port ?? port}`
      : (hostHealth.error || `Not running on ${port}`);
    elements.problemStatus.textContent = problemDetected()
      ? "Detected"
      : (pageState?.error || "Not detected");
    elements.problemTitle.textContent = pageState?.problemTitle || "—";
    elements.language.textContent = pageState?.language || "—";
    elements.codeLength.textContent = typeof pageState?.code === "string"
      ? `${pageState.code.length} chars`
      : "—";
    elements.interviewStatus.textContent = hostStatus.status || "Unknown";
    const interactionMode = hostStatus.interactionMode || "conversation";
    elements.interactionMode.textContent = interactionMode === "focus" ? "Focus" : "Conversation";
    elements.elapsed.textContent = hostStatus.running
      ? formatElapsed(displayedElapsedSeconds())
      : "—";
    elements.hintStatus.textContent = hostStatus.problemAnalysisStatus === "pending"
      ? "Preparing interviewer hints"
      : (hostStatus.problemAnalysisStatus === "error"
        ? "Interviewer hints unavailable"
        : (hostStatus.hintsEligible ? "Eligible" : "Locked"));
    elements.lastError.textContent = hostStatus.lastError || hostStatus.problemAnalysisError || "—";
    elements.volumeValue.textContent = `${elements.volume.value}%`;
    elements.voice.disabled = hostStatus.running;

    const canStart = hostHealth.ok && hostStatus.ok && problemDetected() && !hostStatus.running && ["stopped", "error"].includes(hostStatus.status);
    elements.start.disabled = !canStart;
    elements.stop.disabled = !hostStatus.running && hostStatus.status !== "starting" && hostStatus.status !== "reconnecting";
    elements.toggleFocus.disabled = !hostStatus.running || hostStatus.status !== "running";
    elements.toggleFocus.textContent = interactionMode === "focus" ? "Resume Conversation" : "Enter Focus";
  }

  function applyVolumeResponse(response) {
    if (!response?.ok || !Number.isFinite(response.volume)) {
      return;
    }
    elements.volume.value = String(Math.round(Math.max(0, Math.min(1, response.volume)) * 100));
    elements.volumeValue.textContent = `${elements.volume.value}%`;
  }

  function applyVoiceResponse(response) {
    if (!response?.ok || typeof response.voice !== "string") {
      return;
    }
    elements.voice.value = response.voice;
  }

  async function findActiveTab() {
    const tabs = await browser.tabs.query({ active: true, currentWindow: true });
    return tabs[0] || null;
  }

  async function refreshPageState() {
    if (!Number.isInteger(activeTabId)) {
      pageState = null;
      return;
    }
    let response = null;
    try {
      response = await browser.tabs.sendMessage(activeTabId, { type: "REQUEST_PAGE_STATE" });
    } catch (_error) {
      // The active tab may not be a matching LeetCode page.
    }
    pageState = response?.pageState || null;
  }

  async function refreshStatus({ clearActionMessage = true } = {}) {
    if (statusRefreshPromise) {
      return statusRefreshPromise;
    }
    statusRefreshPromise = (async () => {
      if (clearActionMessage) {
        showMessage(elements.actionMessage, "");
      }
      const results = await Promise.all([
        browser.runtime.sendMessage({ type: "GET_HOST_PORT" }),
        browser.runtime.sendMessage({ type: "HOST_HEALTH" }),
        browser.runtime.sendMessage({ type: "GET_HOST_STATUS" }),
        browser.runtime.sendMessage({ type: "GET_AUDIO_VOLUME" }),
        browser.runtime.sendMessage({ type: "GET_GEMINI_VOICE" }),
        refreshPageState(),
      ]);
      const portResult = results[0];
      if (portResult?.ok) {
        elements.port.value = String(portResult.port);
      }
      hostHealth = results[1] || { ok: false, error: "Host health check failed." };
      updateHostStatus(results[2] || { ok: false, status: "stopped", lastError: hostHealth.error });
      if (!volumeEditing && volumeRequestTimer === null) {
        applyVolumeResponse(results[3]);
      }
      if (!voiceEditing) {
        applyVoiceResponse(results[4]);
      }
      render();
    })();
    try {
      return await statusRefreshPromise;
    } finally {
      statusRefreshPromise = null;
    }
  }

  async function saveVoice() {
    showMessage(elements.voiceMessage, "");
    const response = await browser.runtime.sendMessage({
      type: "SAVE_GEMINI_VOICE",
      voice: elements.voice.value,
    });
    if (!response?.ok) {
      showMessage(elements.voiceMessage, response?.error || "Could not save interviewer voice.");
      return;
    }
    showMessage(elements.voiceMessage, "Saved. Applies to the next interview.");
  }

  function scheduleVolumeUpdate() {
    elements.volumeValue.textContent = `${elements.volume.value}%`;
    showMessage(elements.volumeMessage, "");
    if (volumeRequestTimer !== null) {
      clearTimeout(volumeRequestTimer);
    }
    volumeRequestTimer = setTimeout(async () => {
      volumeRequestTimer = null;
      const response = await browser.runtime.sendMessage({
        type: "SET_AUDIO_VOLUME",
        volume: Number(elements.volume.value) / 100,
      });
      if (!response?.ok) {
        showMessage(elements.volumeMessage, response?.error || "Could not set speaker volume.");
      }
    }, 100);
  }

  async function savePort() {
    showMessage(elements.portMessage, "");
    const raw = elements.port.value.trim();
    if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 65535) {
      showMessage(elements.portMessage, "Host port must be a number between 1 and 65535.");
      return;
    }
    const response = await browser.runtime.sendMessage({ type: "SAVE_HOST_PORT", port: raw });
    if (!response?.ok) {
      showMessage(elements.portMessage, response?.error || "Could not save the host port.");
      return;
    }
    showMessage(elements.portMessage, response.health?.ok ? "Saved. Local host is reachable." : (response.health?.error || "Saved."));
    await refreshStatus();
  }

  async function startInterview() {
    if (!problemDetected()) {
      showMessage(elements.actionMessage, "The LeetCode problem and editor must be detected before starting.");
      return;
    }
    elements.start.disabled = true;
    const response = await browser.runtime.sendMessage({
      type: "START_INTERVIEW",
      tabId: activeTabId,
      payload: {
        protocolVersion: 1,
        pageUrl: pageState.pageUrl,
        problemSlug: pageState.problemSlug,
        problemTitle: pageState.problemTitle,
        problemText: pageState.problemText,
        language: pageState.language,
        code: pageState.code,
        codeVersion: pageState.codeVersion,
        voice: elements.voice.value,
      },
    });
    if (!response?.ok) {
      showMessage(elements.actionMessage, response?.error || "The interview could not be started.");
    }
    await refreshStatus();
  }

  async function stopInterview() {
    elements.stop.disabled = true;
    const response = await browser.runtime.sendMessage({ type: "STOP_INTERVIEW" });
    if (!response?.ok) {
      showMessage(elements.actionMessage, response?.error || "The interview could not be stopped cleanly.");
    }
    await refreshStatus();
  }

  async function toggleFocus() {
    const nextMode = hostStatus.interactionMode === "focus" ? "conversation" : "focus";
    elements.toggleFocus.disabled = true;
    const response = await browser.runtime.sendMessage({
      type: "SET_INTERACTION_MODE",
      mode: nextMode,
    });
    if (!response?.ok) {
      showMessage(elements.actionMessage, response?.error || "Could not change interaction mode.");
    }
    await refreshStatus({ clearActionMessage: false });
  }

  elements.savePort.addEventListener("click", () => savePort());
  elements.volume.addEventListener("focus", () => { volumeEditing = true; });
  elements.volume.addEventListener("blur", () => { volumeEditing = false; });
  elements.volume.addEventListener("input", () => scheduleVolumeUpdate());
  elements.voice.addEventListener("focus", () => { voiceEditing = true; });
  elements.voice.addEventListener("blur", () => { voiceEditing = false; });
  elements.voice.addEventListener("change", () => saveVoice());
  elements.refresh.addEventListener("click", () => refreshStatus());
  elements.start.addEventListener("click", () => startInterview());
  elements.stop.addEventListener("click", () => stopInterview());
  elements.toggleFocus.addEventListener("click", () => toggleFocus());

  setInterval(() => {
    if (hostStatus.running) {
      render();
    }
  }, TIMER_TICK_INTERVAL_MS);
  setInterval(() => {
    refreshStatus({ clearActionMessage: false }).catch(() => {
      // Keep the current display until the next refresh if the host is temporarily unavailable.
    });
  }, STATUS_REFRESH_INTERVAL_MS);

  (async () => {
    const activeTab = await findActiveTab();
    activeTabId = activeTab?.id ?? null;
    await refreshStatus();
  })().catch((error) => {
    showMessage(elements.actionMessage, error?.message || "Could not load extension status.");
    render();
  });
})();
