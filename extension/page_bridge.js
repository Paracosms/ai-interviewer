(() => {
  "use strict";

  const MESSAGE_SOURCE = "leetcode-ai-interviewer-page-bridge";
  const PROTOCOL_VERSION = 1;
  const MAX_CODE_LENGTH = 50000;
  const SNAPSHOT_HEARTBEAT_MS = 3000;
  const EDITOR_NOT_DETECTED_MESSAGE = "LeetCode editor model was not detected. Reload the problem page and try again.";
  let lastCode = null;
  let lastLanguage = null;
  let lastError = null;
  let lastPageUrl = window.location.href;
  let lastSnapshotAt = 0;
  let selectedModel = null;
  let modelSnapshots = new WeakMap();

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
    return selected;
  }

  function pollEditor() {
    if (window.location.href !== lastPageUrl) {
      lastPageUrl = window.location.href;
      lastCode = null;
      lastLanguage = null;
      lastError = null;
      lastSnapshotAt = 0;
      selectedModel = null;
      modelSnapshots = new WeakMap();
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
    const { code, language, version } = selected;
    const now = Date.now();
    if (
      code === lastCode &&
      language === lastLanguage &&
      now - lastSnapshotAt < SNAPSHOT_HEARTBEAT_MS
    ) {
      return;
    }
    lastCode = code;
    lastLanguage = language;
    lastSnapshotAt = now;
    publish("CODE_SNAPSHOT", {
      code,
      language,
      version,
      editorDetected: true,
    });
  }

  setInterval(pollEditor, 750);
  pollEditor();
})();
