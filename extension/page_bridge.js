(() => {
  "use strict";

  const MESSAGE_SOURCE = "leetcode-ai-interviewer-page-bridge";
  const PROTOCOL_VERSION = 1;
  const MAX_CODE_LENGTH = 50000;
  const SNAPSHOT_HEARTBEAT_MS = 3000;
  const RUN_RESULT_TIMEOUT_MS = 120000;
  const EDITOR_NOT_DETECTED_MESSAGE = "LeetCode editor model was not detected. Reload the problem page and try again.";
  let lastCode = null;
  let lastLanguage = null;
  let lastError = null;
  let lastPageUrl = window.location.href;
  let lastSnapshotAt = 0;
  let selectedModel = null;
  let modelSnapshots = new WeakMap();
  let pendingRun = null;
  let lastRunResultSignature = null;
  let resultObserver = null;

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

  function normalizedLabel(element) {
    return String(
      element?.getAttribute?.("aria-label")
      || element?.getAttribute?.("title")
      || element?.textContent
      || "",
    ).replace(/\s+/g, " ").trim().toLowerCase();
  }

  function resultSignature(text) {
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return `run-${(hash >>> 0).toString(16)}`;
  }

  function extractSection(text, label, followingLabels) {
    const expression = new RegExp(
      `${label}\\s*:?\\s*([\\s\\S]*?)(?=\\n\\s*(?:${followingLabels.join("|")})\\s*:?|$)`,
      "i",
    );
    return (text.match(expression)?.[1] || "").trim().slice(0, 10000);
  }

  function resultText(element) {
    return String(element?.innerText || element?.textContent || "")
      .replace(/\r/g, "")
      .trim();
  }

  function findResultCandidates() {
    const pageDocument = window.document;
    const candidates = [];
    if (!pageDocument?.querySelectorAll) {
      return candidates;
    }
    for (const [selector, specific] of [
      ["[data-e2e-locator*='console-result']", true],
      ["[data-testid*='test-result']", true],
      ["[data-cy*='test-result']", true],
      ["[role='tabpanel']", false],
    ]) {
      try {
        candidates.push(...[...pageDocument.querySelectorAll(selector)].map((element) => ({ element, specific })));
      } catch (_error) {
        // Ignore selector support differences across LeetCode versions.
      }
    }
    return candidates;
  }

  function inspectRunResult() {
    const pageDocument = window.document;
    if (!pendingRun || !pageDocument?.querySelectorAll) {
      return;
    }
    if (Date.now() - pendingRun.startedAt > RUN_RESULT_TIMEOUT_MS) {
      pendingRun = null;
      return;
    }
    const candidates = findResultCandidates();
    const failurePattern = /\b(wrong answer|runtime error|time limit exceeded|memory limit exceeded|compile error|failed)\b/i;
    const successPattern = /\b(accepted|all test cases passed|success)\b/i;
    for (const candidate of candidates) {
      const text = resultText(candidate.element);
      if (!text) {
        continue;
      }
      if (failurePattern.test(text) && (candidate.specific || /\b(input|output|expected|testcase)\b/i.test(text))) {
        const signature = resultSignature(text);
        if (pendingRun.baselineSignatures.has(signature)) {
          continue;
        }
        pendingRun = null;
        if (signature === lastRunResultSignature) {
          return;
        }
        lastRunResultSignature = signature;
        publish("RUN_RESULT", {
          status: "failed",
          resultSignature: signature,
          caseLabel: text.match(/\bCase\s+\d+\b/i)?.[0] || "",
          input: extractSection(text, "Input", ["Output", "Expected", "Stdout"]),
          actual: extractSection(text, "Output", ["Expected", "Stdout", "Input"]),
          expected: extractSection(text, "Expected", ["Output", "Stdout", "Input"]),
        });
        return;
      }
      if (successPattern.test(text)) {
        const signature = resultSignature(text);
        if (pendingRun.baselineSignatures.has(signature)) {
          continue;
        }
        pendingRun = null;
        return;
      }
    }
  }

  function handleActionClick(event) {
    const button = event?.target?.closest?.("button");
    const label = normalizedLabel(button);
    if (label === "run" || label.startsWith("run ")) {
      pendingRun = {
        startedAt: Date.now(),
        baselineSignatures: new Set(
          findResultCandidates()
            .map((candidate) => resultText(candidate.element))
            .filter(Boolean)
            .map(resultSignature),
        ),
      };
    } else if (label === "submit" || label.startsWith("submit ")) {
      pendingRun = null;
    }
  }

  function ensureResultObserver() {
    const pageDocument = window.document;
    if (resultObserver || !pageDocument?.body || typeof window.MutationObserver !== "function") {
      return;
    }
    resultObserver = new window.MutationObserver(() => inspectRunResult());
    resultObserver.observe(pageDocument.body, { childList: true, subtree: true, characterData: true });
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
        return { model, code, language, version, attached, changed };
      })
      .filter((candidate) => (
        candidate &&
        candidate.code.length > 0 &&
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
    const attached = viable.filter((candidate) => candidate.attached).sort(byLength);
    const changed = viable.filter((candidate) => candidate.changed).sort(byLength);
    const previousSelection = viable.find((candidate) => candidate.model === selectedModel);
    const selected = changedAttached[0]
      || changed[0]
      || (previousSelection?.attached ? previousSelection : null)
      || attached[0]
      || previousSelection
      || viable.sort(byLength)[0]
      || null;
    selectedModel = selected?.model || null;
    return selected;
  }

  function pollEditor() {
    ensureResultObserver();
    if (window.location.href !== lastPageUrl) {
      lastPageUrl = window.location.href;
      lastCode = null;
      lastLanguage = null;
      lastError = null;
      lastSnapshotAt = 0;
      selectedModel = null;
      modelSnapshots = new WeakMap();
      pendingRun = null;
      lastRunResultSignature = null;
    }
    inspectRunResult();
    const selected = chooseModel();
    if (!selected) {
      if (lastError !== EDITOR_NOT_DETECTED_MESSAGE) {
        lastError = EDITOR_NOT_DETECTED_MESSAGE;
        publish("DETECTION_ERROR", { message: lastError });
      }
      return;
    }
    lastError = null;
    const { model, code, language, version: selectedVersion } = selected;
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
    let modelUri = null;
    let version = null;
    try {
      modelUri = model.uri?.toString?.() || null;
      version = selectedVersion;
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
  window.document?.addEventListener?.("click", handleActionClick, true);
  pollEditor();
})();
