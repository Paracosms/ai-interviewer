(() => {
  "use strict";

  const MESSAGE_SOURCE = "leetcode-ai-interviewer-page-bridge";
  const PROTOCOL_VERSION = 1;
  const MAX_CODE_LENGTH = 50000;
  const EDITOR_NOT_DETECTED_MESSAGE = "LeetCode editor model was not detected. Reload the problem page and try again.";
  let lastCode = null;
  let lastLanguage = null;
  let lastError = null;
  let lastPageUrl = window.location.href;

  function publish(type, payload) {
    window.postMessage(
      {
        source: MESSAGE_SOURCE,
        protocolVersion: PROTOCOL_VERSION,
        type,
        payload,
      },
      window.location.origin,
    );
  }

  function chooseModel() {
    const monaco = window.monaco;
    if (!monaco?.editor?.getModels) {
      return null;
    }
    let models;
    try {
      models = monaco.editor.getModels();
    } catch (_error) {
      return null;
    }
    if (!Array.isArray(models)) {
      return null;
    }
    const viable = models
      .map((model) => {
        let code = "";
        let language = "";
        try {
          code = model.getValue();
          language = model.getLanguageId?.() || "";
        } catch (_error) {
          return null;
        }
        return { model, code, language };
      })
      .filter((candidate) => (
        candidate &&
        candidate.code.length > 0 &&
        candidate.code.length <= MAX_CODE_LENGTH &&
        candidate.language &&
        candidate.language.toLowerCase() !== "plaintext"
      ))
      .sort((left, right) => right.code.length - left.code.length);
    return viable[0] || null;
  }

  function pollEditor() {
    if (window.location.href !== lastPageUrl) {
      lastPageUrl = window.location.href;
      lastCode = null;
      lastLanguage = null;
      lastError = null;
    }
    const selected = chooseModel();
    if (!selected) {
      if (lastError !== EDITOR_NOT_DETECTED_MESSAGE) {
        lastError = EDITOR_NOT_DETECTED_MESSAGE;
        publish("DETECTION_ERROR", { message: lastError });
      }
      return;
    }
    lastError = null;
    const { model, code, language } = selected;
    if (code === lastCode && language === lastLanguage) {
      return;
    }
    lastCode = code;
    lastLanguage = language;
    let modelUri = null;
    let version = null;
    try {
      modelUri = model.uri?.toString?.() || null;
      version = model.getVersionId?.() ?? null;
    } catch (_error) {
      // The source and language remain authoritative when optional metadata is unavailable.
    }
    publish("CODE_SNAPSHOT", {
      code,
      language,
      modelUri,
      version,
    });
  }

  setInterval(pollEditor, 750);
  pollEditor();
})();
