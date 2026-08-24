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
    "host-status",
    "problem-status",
    "problem-title",
    "language",
    "code-length",
    "interview-status",
    "elapsed",
    "hint-status",
    "last-error",
    "start-interview",
    "stop-interview",
    "refresh-status",
    "action-message",
  ];
  const elements = Object.fromEntries(elementIds.map((id) => [id, makeElement()]));
  const intervals = [];
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
          };
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
    advance(milliseconds) {
      now += milliseconds;
    },
  };
}

test("popup timer advances while the popup remains open", async () => {
  const popup = await loadPopup();

  assert.equal(popup.elements.elapsed.textContent, "0:10");
  const timer = popup.intervals.find(({ delay }) => delay === 250);
  assert.ok(timer, "expected a live timer interval");

  popup.advance(1500);
  timer.callback();

  assert.equal(popup.elements.elapsed.textContent, "0:11");
});
