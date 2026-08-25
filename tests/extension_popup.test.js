const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function makeElement() {
  return {
    value: "",
    textContent: "",
    disabled: false,
    listeners: {},
    addEventListener(type, listener) {
      this.listeners[type] = listener;
    },
  };
}

async function loadPopup() {
  const elementIds = [
    "host-port",
    "save-port",
    "port-message",
    "volume",
    "volume-value",
    "volume-message",
    "voice",
    "voice-message",
    "host-status",
    "problem-status",
    "problem-title",
    "language",
    "code-length",
    "interview-status",
    "interaction-mode",
    "elapsed",
    "hint-status",
    "last-error",
    "start-interview",
    "stop-interview",
    "toggle-focus",
    "refresh-status",
    "action-message",
  ];
  const elements = Object.fromEntries(elementIds.map((id) => [id, makeElement()]));
  const intervals = [];
  const runtimeMessages = [];
  let interactionMode = "conversation";
  let now = 0;
  const browser = {
    tabs: {
      async query() {
        return [{ id: 42 }];
      },
      async sendMessage() {
        return {
          pageState: {
            detected: true,
            pageUrl: "https://leetcode.com/problems/two-sum/",
            problemSlug: "two-sum",
            problemTitle: "Two Sum",
            problemText: "Find two numbers.",
            language: "python",
            code: "pass",
            codeVersion: 1,
          },
        };
      },
    },
    runtime: {
      async sendMessage(message) {
        runtimeMessages.push(message);
        if (message.type === "GET_HOST_PORT") {
          return { ok: true, port: 8765 };
        }
        if (message.type === "HOST_HEALTH") {
          return { ok: true, port: 8765 };
        }
        if (message.type === "GET_HOST_STATUS") {
          return {
            ok: true,
            running: true,
            status: "running",
            elapsedSeconds: 10,
            hintsEligible: false,
            lastError: null,
            problemAnalysisStatus: "pending",
            problemAnalysisError: null,
            interactionMode,
          };
        }
        if (message.type === "GET_AUDIO_VOLUME") {
          return { ok: true, volume: 1 };
        }
        if (message.type === "GET_GEMINI_VOICE") {
          return { ok: true, voice: "Kore" };
        }
        if (message.type === "SAVE_GEMINI_VOICE") {
          return { ok: true, voice: message.voice };
        }
        if (message.type === "SET_AUDIO_VOLUME") {
          return { ok: true, volume: message.volume };
        }
        if (message.type === "SET_INTERACTION_MODE") {
          interactionMode = message.mode;
          return { ok: true, interactionMode: message.mode };
        }
        throw new Error(`Unexpected message: ${message.type}`);
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "popup", "popup.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    browser,
    console,
    Date: { now: () => now },
    document: { getElementById: (id) => elements[id] },
    performance: undefined,
    setInterval(callback, delay) {
      intervals.push({ callback, delay });
      return intervals.length;
    },
  });

  await new Promise((resolve) => setImmediate(resolve));
  return {
    elements,
    intervals,
    runtimeMessages,
    advance(milliseconds) {
      now += milliseconds;
    },
  };
}

test("popup timer advances while the popup remains open", async () => {
  const popup = await loadPopup();

  assert.equal(popup.elements.elapsed.textContent, "0:10");
  assert.equal(popup.elements["hint-status"].textContent, "Preparing verified hints");
  const timer = popup.intervals.find(({ delay }) => delay === 250);
  assert.ok(timer, "expected a live timer interval");

  popup.advance(1500);
  timer.callback();

  assert.equal(popup.elements.elapsed.textContent, "0:11");
});

test("popup exposes a focus-mode toggle", async () => {
  const popup = await loadPopup();
  assert.equal(popup.elements["interaction-mode"].textContent, "Conversation");
  assert.equal(popup.elements["toggle-focus"].textContent, "Enter Focus");
  popup.elements["toggle-focus"].listeners.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(popup.runtimeMessages.some(
    (message) => message.type === "SET_INTERACTION_MODE" && message.mode === "focus",
  ));
});

test("popup saves the selected interviewer voice", async () => {
  const popup = await loadPopup();
  popup.elements.voice.value = "Aoede";
  popup.elements.voice.listeners.change();
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(popup.runtimeMessages.some(
    (message) => message.type === "SAVE_GEMINI_VOICE" && message.voice === "Aoede",
  ));
});

test("popup keeps diagnostics behind a closed Advanced disclosure", () => {
  const popupHtml = fs.readFileSync(
    path.join(__dirname, "..", "extension", "popup", "popup.html"),
    "utf8",
  );
  const advancedStart = popupHtml.indexOf('<details class="advanced">');
  const advancedEnd = popupHtml.indexOf("</details>", advancedStart);

  assert.ok(advancedStart >= 0, "expected an Advanced disclosure");
  assert.ok(advancedEnd > advancedStart, "expected Advanced content to close");
  assert.equal(
    popupHtml.slice(advancedStart, advancedEnd).includes(" open"),
    false,
    "Advanced should be collapsed on first open",
  );

  const advancedMarkup = popupHtml.slice(advancedStart, advancedEnd);
  for (const id of ["host-port", "host-status", "last-error", "refresh-status"]) {
    assert.ok(advancedMarkup.includes(`id="${id}"`), `${id} should be in Advanced`);
  }
  for (const id of ["volume", "voice", "start-interview", "stop-interview", "toggle-focus"]) {
    assert.ok(
      popupHtml.indexOf(`id="${id}"`) < advancedStart,
      `${id} should remain visible outside Advanced`,
    );
  }
});
