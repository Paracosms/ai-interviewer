(() => {
  "use strict";

  const MESSAGE_SOURCE = "leetcode-ai-interviewer-page-bridge";
  const PROTOCOL_VERSION = 1;
  const MAX_CODE_LENGTH = 50000;
  const FALLBACK_POLL_MS = 3000;
  const MODEL_RESCAN_MS = 15000;
  const SNAPSHOT_HEARTBEAT_MS = 15000;
  const SNAPSHOT_DEBOUNCE_MS = 100;
  const TYPING_ACTIVITY_THROTTLE_MS = 500;
  const EDITOR_NOT_DETECTED_MESSAGE = "LeetCode editor model was not detected. Reload the problem page and try again.";
  let lastCode = null;
  let lastLanguage = null;
  let lastVersion = null;
  let lastError = null;
  let lastPageUrl = window.location.href;
  let lastSnapshotAt = 0;
  let selectedModel = null;
  let modelSnapshots = new WeakMap();
  let activeContentListener = null;
  let activeListenedModel = null;
  let snapshotDebounceTimer = null;
  let lastTypingActivityAt = 0;
  let lastModelScanAt = 0;

  function clearSnapshotDebounce() {
    if (snapshotDebounceTimer !== null) {
      clearTimeout(snapshotDebounceTimer);
      snapshotDebounceTimer = null;
    }
  }

  function publishTypingActivity() {
    const now = Date.now();
    if (now - lastTypingActivityAt < TYPING_ACTIVITY_THROTTLE_MS) {
      return;
    }
    lastTypingActivityAt = now;
    publish("TYPING_ACTIVITY", {});
  }

  function scheduleActiveModelSnapshot() {
    clearSnapshotDebounce();
    snapshotDebounceTimer = setTimeout(() => {
      snapshotDebounceTimer = null;
      publishModelSnapshot(activeListenedModel);
    }, SNAPSHOT_DEBOUNCE_MS);
  }

  function ensureContentListener(model) {
    if (model === activeListenedModel) {
      return;
    }
    clearSnapshotDebounce();
    if (activeContentListener && typeof activeContentListener.dispose === "function") {
      try {
        activeContentListener.dispose();
      } catch (_) {}
    }
    activeContentListener = null;
    activeListenedModel = model;
    if (model && typeof model.onDidChangeContent === "function") {
      try {
        activeContentListener = model.onDidChangeContent(() => {
          publishTypingActivity();
          scheduleActiveModelSnapshot();
        });
      } catch (_) {}
    }
  }

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
    const visibleModels = new Set();
    try {
      models = monaco.editor.getModels();
      lastModelScanAt = Date.now();
      const editors = monaco.editor.getEditors?.() || [];
      for (const editor of editors) {
        const node = editor.getDomNode?.();
        const rect = node?.getBoundingClientRect?.();
        if (
          editor.getModel?.()
          && node?.isConnected !== false
          && rect?.width > 0
          && rect?.height > 0
        ) {
          visibleModels.add(editor.getModel());
        }
      }
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
        let version = null;
        let attached = false;
        try {
          code = model.getValue();
          language = model.getLanguageId?.() || "";
          version = model.getVersionId?.() ?? null;
          attached = model.isAttachedToEditor?.() === true;
        } catch (_error) {
          return null;
        }
        const previous = modelSnapshots.get(model);
        const changed = Boolean(previous) && (
          previous.code !== code ||
          previous.language !== language ||
          previous.version !== version
        );
        return {
          model,
          code,
          language,
          version,
          attached,
          changed,
          visible: visibleModels.has(model),
        };
      })
      .filter((candidate) => (
        candidate &&
        candidate.code.length <= MAX_CODE_LENGTH &&
        candidate.language &&
        candidate.language.toLowerCase() !== "plaintext"
      ));

    for (const candidate of viable) {
      modelSnapshots.set(candidate.model, {
        code: candidate.code,
        language: candidate.language,
        version: candidate.version,
      });
    }

    // LeetCode can retain a larger, static starter model beside the model that
    // backs the visible editor. Prefer an attached model and, most importantly,
    // follow whichever viable model is receiving edits.
    const byLength = (left, right) => right.code.length - left.code.length;
    const changedAttached = viable.filter((candidate) => candidate.changed && candidate.attached).sort(byLength);
    const visible = viable.filter((candidate) => candidate.visible);
    const attached = viable.filter((candidate) => candidate.attached).sort(byLength);
    const attachedEmpty = attached.filter((candidate) => candidate.code.length === 0);
    const empty = viable.filter((candidate) => candidate.code.length === 0);
    const changed = viable.filter((candidate) => candidate.changed).sort(byLength);
    const previousSelection = viable.find((candidate) => candidate.model === selectedModel);
    // Once an attached editor model has been selected, keep it until it is
    // detached. Hidden Monaco models can receive background edits and must not
    // steal selection from the editor the candidate is actually using.
    const selected = visible[0]
      || (previousSelection?.attached ? previousSelection : null)
      || changedAttached[0]
      || attachedEmpty[0]
      || attached[0]
      || (previousSelection?.changed ? previousSelection : null)
      || changed[0]
      || empty[0]
      || previousSelection
      || viable.sort(byLength)[0]
      || null;
    selectedModel = selected?.model || null;
    ensureContentListener(selectedModel);
    return selected;
  }

  function extractProblemSlug(url) {
    const match = String(url || "").match(/\/problems\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function readModelSnapshot(model) {
    if (!model) {
      return null;
    }
    try {
      const code = model.getValue();
      const language = model.getLanguageId?.() || "";
      if (
        typeof code !== "string"
        || code.length > MAX_CODE_LENGTH
        || !language
        || language.toLowerCase() === "plaintext"
      ) {
        return null;
      }
      return {
        code,
        language,
        version: model.getVersionId?.() ?? null,
      };
    } catch (_error) {
      return null;
    }
  }

  function publishModelSnapshot(model, force = false) {
    const now = Date.now();
    if (!force && model === selectedModel && lastLanguage) {
      try {
        const currentVersion = model.getVersionId?.() ?? null;
        const currentLanguage = model.getLanguageId?.() || "";
        if (
          currentVersion !== null
          && currentVersion === lastVersion
          && currentLanguage === lastLanguage
          && now - lastSnapshotAt < SNAPSHOT_HEARTBEAT_MS
        ) {
          return true;
        }
      } catch (_error) {}
    }
    const snapshot = readModelSnapshot(model);
    if (!snapshot) {
      return false;
    }
    if (
      !force
      && snapshot.code === lastCode
      && snapshot.language === lastLanguage
      && now - lastSnapshotAt < SNAPSHOT_HEARTBEAT_MS
    ) {
      lastVersion = snapshot.version;
      return true;
    }
    lastCode = snapshot.code;
    lastLanguage = snapshot.language;
    lastVersion = snapshot.version;
    lastSnapshotAt = now;
    lastError = null;
    publish("CODE_SNAPSHOT", {
      ...snapshot,
      editorDetected: true,
    });
    return true;
  }

  function pollEditor() {
    const prevSlug = extractProblemSlug(lastPageUrl);
    const currSlug = extractProblemSlug(window.location.href);
    const slugChanged = prevSlug !== currSlug || (!currSlug && window.location.href !== lastPageUrl);
    if (slugChanged) {
      lastPageUrl = window.location.href;
      lastCode = null;
      lastLanguage = null;
      lastVersion = null;
      lastError = null;
      lastSnapshotAt = 0;
      selectedModel = null;
      lastModelScanAt = 0;
      clearSnapshotDebounce();
      ensureContentListener(null);
      modelSnapshots = new WeakMap();
    } else if (window.location.href !== lastPageUrl) {
      lastPageUrl = window.location.href;
    }
    const now = Date.now();
    let canReuseSelectedModel = false;
    if (selectedModel) {
      try {
        canReuseSelectedModel = selectedModel.isDisposed?.() !== true
          && selectedModel.isAttachedToEditor?.() === true
          && now - lastModelScanAt < MODEL_RESCAN_MS;
      } catch (_error) {}
    }
    const selected = canReuseSelectedModel ? { model: selectedModel } : chooseModel();
    if (!selected) {
      ensureContentListener(null);
      if (lastError !== EDITOR_NOT_DETECTED_MESSAGE) {
        lastError = EDITOR_NOT_DETECTED_MESSAGE;
        publish("DETECTION_ERROR", { message: lastError });
      }
      return;
    }
    publishModelSnapshot(selected.model);
  }

  setInterval(pollEditor, FALLBACK_POLL_MS);
  pollEditor();
})();
