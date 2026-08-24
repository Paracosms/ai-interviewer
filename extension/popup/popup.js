(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = {
    port: $("host-port"),
    savePort: $("save-port"),
    portMessage: $("port-message"),
    hostStatus: $("host-status"),
    problemStatus: $("problem-status"),
    problemTitle: $("problem-title"),
    language: $("language"),
    codeLength: $("code-length"),
    interviewStatus: $("interview-status"),
    elapsed: $("elapsed"),
    hintStatus: $("hint-status"),
    lastError: $("last-error"),
    start: $("start-interview"),
    stop: $("stop-interview"),
    refresh: $("refresh-status"),
    actionMessage: $("action-message"),
  };

  let activeTabId = null;
  let hostHealth = { ok: false };
  let hostStatus = { ok: false, status: "stopped" };
  let pageState = null;

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
    elements.elapsed.textContent = hostStatus.running
      ? formatElapsed(hostStatus.elapsedSeconds)
      : "—";
    elements.hintStatus.textContent = hostStatus.hintsEligible ? "Eligible" : "Locked";
    elements.lastError.textContent = hostStatus.lastError || "—";

    const canStart = hostHealth.ok && hostStatus.ok && problemDetected() && !hostStatus.running && ["stopped", "error"].includes(hostStatus.status);
    elements.start.disabled = !canStart;
    elements.stop.disabled = !hostStatus.running && hostStatus.status !== "starting" && hostStatus.status !== "reconnecting";
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
    let directPageState = null;
    try {
      const response = await browser.tabs.sendMessage(activeTabId, { type: "REQUEST_PAGE_STATE" });
      directPageState = response?.pageState || null;
    } catch (_error) {
      // The active tab may not be a matching LeetCode page.
    }
    if (directPageState) {
      pageState = directPageState;
      return;
    }
    const response = await browser.runtime.sendMessage({
      type: "GET_PAGE_STATE",
      tabId: activeTabId,
    });
    pageState = response?.pageState || null;
  }

  async function refreshStatus() {
    showMessage(elements.actionMessage, "");
    const results = await Promise.all([
      browser.runtime.sendMessage({ type: "GET_HOST_PORT" }),
      browser.runtime.sendMessage({ type: "HOST_HEALTH" }),
      browser.runtime.sendMessage({ type: "GET_HOST_STATUS" }),
      refreshPageState(),
    ]);
    const portResult = results[0];
    if (portResult?.ok) {
      elements.port.value = String(portResult.port);
    }
    hostHealth = results[1] || { ok: false, error: "Host health check failed." };
    hostStatus = results[2] || { ok: false, status: "stopped", lastError: hostHealth.error };
    render();
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
      showMessage(elements.actionMessage, "The LeetCode problem and code must be detected before starting.");
      return;
    }
    elements.start.disabled = true;
    const response = await browser.runtime.sendMessage({
      type: "START_INTERVIEW",
      payload: {
        protocolVersion: 1,
        pageUrl: pageState.pageUrl,
        problemSlug: pageState.problemSlug,
        problemTitle: pageState.problemTitle,
        problemText: pageState.problemText,
        language: pageState.language,
        code: pageState.code,
        codeVersion: pageState.codeVersion,
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

  elements.savePort.addEventListener("click", () => savePort());
  elements.refresh.addEventListener("click", () => refreshStatus());
  elements.start.addEventListener("click", () => startInterview());
  elements.stop.addEventListener("click", () => stopInterview());

  (async () => {
    const activeTab = await findActiveTab();
    activeTabId = activeTab?.id ?? null;
    await refreshStatus();
  })().catch((error) => {
    showMessage(elements.actionMessage, error?.message || "Could not load extension status.");
    render();
  });
})();
