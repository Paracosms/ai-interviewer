(() => {
  "use strict";

  const MESSAGE_SOURCE = "leetcode-ai-interviewer-page-bridge";
  const PROTOCOL_VERSION = 1;
  const MAX_CODE_LENGTH = 50000;
  const CODE_DEBOUNCE_MS = 1200;
  const PROBLEM_RETRY_MS = 1000;
  const DESCRIPTION_NOT_DETECTED_MESSAGE = "The LeetCode problem description was not detected. The interview was not started.";
  const EDITOR_NOT_DETECTED_MESSAGE = "LeetCode editor model was not detected. Reload the problem page and try again.";

  const TITLE_SELECTORS = [
    "[data-cy='question-title']",
    "[data-testid='question-title']",
    "div.text-title-large",
    "h1[data-cy='question-title']",
    "h1",
  ];
  const DESCRIPTION_SELECTORS = [
    "[data-track-load='description_content']",
    "[data-cy='question-content']",
    "[data-key='description-content']",
    "[data-testid='description-content']",
    "[data-cy='description-content']",
    "article",
  ];

  let pageUrl = window.location.href;
  let pageGeneration = 0;
  let latestCode = "";
  let latestLanguage = "";
  let latestCodeVersion = 0;
  let lastSentCode = null;
  let lastSentLanguage = null;
  let codeDebounceTimer = null;
  let latestPageState = null;
  let lastProblemSignature = "";

  function normalizeText(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/\r/g, "")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function firstVisibleText(selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element && element.textContent?.trim()) {
        return normalizeText(element.textContent);
      }
    }
    return "";
  }

  function extractTitle() {
    const visibleTitle = firstVisibleText(TITLE_SELECTORS).replace(/^\d+\.\s*/, "");
    if (visibleTitle) {
      return visibleTitle;
    }
    const meta = document.querySelector("meta[property='og:title']");
    const metaTitle = meta?.getAttribute?.("content") || "";
    if (metaTitle.trim()) {
      return normalizeText(metaTitle).replace(/\s*-\s*LeetCode.*$/i, "");
    }
    return normalizeText(document.title || "").replace(/\s*-\s*LeetCode.*$/i, "");
  }

  function extractDescription() {
    for (const selector of DESCRIPTION_SELECTORS) {
      const elements = typeof document.querySelectorAll === "function"
        ? document.querySelectorAll(selector)
        : [document.querySelector(selector)].filter(Boolean);
      for (const element of elements) {
        const clone = element.cloneNode(true);
        clone.querySelectorAll("button, nav, header, svg, style, script, [aria-hidden='true'], [role='button']")
          .forEach((node) => node.remove());
        const text = normalizeText(clone.textContent);
        if (text.length >= 200) {
          return text;
        }
      }
    }
    return "";
  }

  function extractProblemSlug() {
    const match = window.location.pathname.match(/^\/problems\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function validateBridgeMessage(event) {
    if (event.source !== window || !event.data || typeof event.data !== "object") {
      return null;
    }
    const message = event.data;
    if (
      message.source !== MESSAGE_SOURCE ||
      message.protocolVersion !== PROTOCOL_VERSION ||
      !["CODE_SNAPSHOT", "DETECTION_ERROR"].includes(message.type) ||
      !message.payload ||
      typeof message.payload !== "object"
    ) {
      return null;
    }
    return message;
  }

  function publishPageState() {
    if (!latestPageState) {
      return;
    }
    browser.runtime.sendMessage({
      type: "PAGE_STATE_UPDATE",
      payload: latestPageState,
    }).catch(() => {
      // The popup or background page may be unavailable during extension startup.
    });
  }

  function setPageState(error = null) {
    const title = extractTitle();
    const problemText = extractDescription();
    const problemSlug = extractProblemSlug();
    const detected = Boolean(
      pageUrl.startsWith("https://leetcode.com/problems/") &&
      problemSlug &&
      title &&
      problemText.length >= 200 &&
      latestCode &&
      latestLanguage,
    );
    const derivedError = !title || problemText.length < 200
      ? DESCRIPTION_NOT_DETECTED_MESSAGE
      : (!latestCode || !latestLanguage ? EDITOR_NOT_DETECTED_MESSAGE : null);
    const nextState = {
      protocolVersion: PROTOCOL_VERSION,
      generation: pageGeneration,
      pageUrl,
      problemSlug,
      problemTitle: title,
      problemText,
      language: latestLanguage,
      code: latestCode,
      codeVersion: latestCodeVersion,
      error: error || derivedError,
      detected,
    };
    const signature = JSON.stringify([
      nextState.pageUrl,
      nextState.problemSlug,
      nextState.problemTitle,
      nextState.problemText,
      nextState.language,
      nextState.code,
      nextState.codeVersion,
      nextState.error,
      nextState.detected,
    ]);
    if (signature !== lastProblemSignature) {
      lastProblemSignature = signature;
      latestPageState = nextState;
      publishPageState();
    }
  }

  function scheduleCodeUpdate() {
    if (codeDebounceTimer !== null) {
      clearTimeout(codeDebounceTimer);
    }
    codeDebounceTimer = setTimeout(() => {
      codeDebounceTimer = null;
      if (!latestCode || (latestCode === lastSentCode && latestLanguage === lastSentLanguage)) {
        setPageState();
        return;
      }
      lastSentCode = latestCode;
      lastSentLanguage = latestLanguage;
      browser.runtime.sendMessage({
        type: "CODE_UPDATE",
        payload: {
          protocolVersion: PROTOCOL_VERSION,
          pageUrl,
          language: latestLanguage,
          code: latestCode,
          codeVersion: latestCodeVersion,
        },
      }).catch(() => {
        // Host-offline and stopped-session errors are shown by the popup health/status view.
      });
      setPageState();
    }, CODE_DEBOUNCE_MS);
  }

  function handleBridgeMessage(event) {
    const message = validateBridgeMessage(event);
    if (!message) {
      return;
    }
    if (message.type === "DETECTION_ERROR") {
      if (typeof message.payload.message !== "string") {
        return;
      }
      setPageState(String(message.payload.message || EDITOR_NOT_DETECTED_MESSAGE));
      return;
    }
    const payload = message.payload;
    if (
      typeof payload.code !== "string" ||
      typeof payload.language !== "string" ||
      (typeof payload.modelUri !== "string" && payload.modelUri !== null) ||
      (payload.version !== null && (!Number.isInteger(payload.version) || payload.version < 0)) ||
      payload.code.length > MAX_CODE_LENGTH
    ) {
      return;
    }
    const codeChanged = payload.code !== latestCode;
    const languageChanged = payload.language !== latestLanguage;
    latestCode = payload.code;
    latestLanguage = payload.language;
    if (codeChanged) {
      latestCodeVersion += 1;
    }
    if (codeChanged || languageChanged) {
      scheduleCodeUpdate();
    }
    setPageState();
  }

  function resetForNavigation() {
    if (codeDebounceTimer !== null) {
      clearTimeout(codeDebounceTimer);
      codeDebounceTimer = null;
    }
    pageUrl = window.location.href;
    pageGeneration += 1;
    latestCode = "";
    latestLanguage = "";
    latestCodeVersion = 0;
    lastSentCode = null;
    lastSentLanguage = null;
    lastProblemSignature = "";
    latestPageState = null;
    setPageState("Loading the new LeetCode problem.");
  }

  function checkNavigation() {
    if (window.location.href !== pageUrl) {
      resetForNavigation();
    }
  }

  browser.runtime.onMessage.addListener(async (message) => {
    if (message?.type !== "REQUEST_PAGE_STATE") {
      return undefined;
    }
    checkNavigation();
    setPageState();
    return { ok: true, pageState: latestPageState };
  });

  window.addEventListener("message", handleBridgeMessage, false);

  setInterval(() => {
    checkNavigation();
    setPageState();
  }, PROBLEM_RETRY_MS);
})();
