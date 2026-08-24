const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function textElement(text) {
  return {
    textContent: text,
    cloneNode() {
      return {
        textContent: text,
        querySelectorAll() {
          return [];
        },
      };
    },
  };
}

function loadContent({ title = "Two Sum", description = "" } = {}) {
  const messages = [];
  const intervals = [];
  const timeouts = [];
  const window = {
    location: {
      href: "https://leetcode.com/problems/two-sum/",
      pathname: "/problems/two-sum/",
    },
    addEventListener(type, listener) {
      if (type === "message") {
        this.messageListener = listener;
      }
    },
  };
  const titleElement = title ? textElement(title) : null;
  const descriptionElement = description ? textElement(description) : null;
  const document = {
    querySelector(selector) {
      if (selector.includes("question-title")) {
        return titleElement;
      }
      if (selector.includes("description")) {
        return descriptionElement;
      }
      return null;
    },
    createElement() {
      return {
        remove() {},
      };
    },
    head: {
      appendChild() {},
    },
    documentElement: {
      appendChild() {},
    },
  };
  let requestPageState;
  const browser = {
    runtime: {
      getURL() {
        return "moz-extension://test/page_bridge.js";
      },
      sendMessage(message) {
        messages.push(message);
        return Promise.resolve({ ok: true });
      },
      onMessage: {
        addListener(listener) {
          requestPageState = listener;
        },
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "content.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    browser,
    document,
    window,
    clearTimeout,
    console,
    setInterval(callback) {
      intervals.push(callback);
      return intervals.length;
    },
    setTimeout(callback) {
      timeouts.push(callback);
      return timeouts.length;
    },
  });
  return {
    messages,
    window,
    tick() {
      intervals[0]();
    },
    dispatch(data, sourceWindow = window) {
      window.messageListener({ source: sourceWindow, data });
    },
    flushCodeDebounce() {
      const callback = timeouts.shift();
      assert.ok(callback, "expected a pending code debounce");
      callback();
    },
    requestPageState,
  };
}

function latestPageState(messages) {
  const stateMessage = [...messages]
    .reverse()
    .find((message) => message.type === "PAGE_STATE_UPDATE");
  return stateMessage?.payload;
}

test("content script reports actionable extraction failure", () => {
  const harness = loadContent({ title: "Two Sum" });
  harness.tick();
  const state = latestPageState(harness.messages);
  assert.equal(state.detected, false);
  assert.equal(
    state.error,
    "The LeetCode problem description was not detected. The interview was not started.",
  );
});

test("content script combines the problem and complete code snapshot", () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  harness.tick();
  harness.dispatch({
    source: "leetcode-ai-interviewer-page-bridge",
    protocolVersion: 1,
    type: "CODE_SNAPSHOT",
    payload: {
      code: "class Solution {\n  // off-screen comment\n}",
      language: "java",
      modelUri: "inmemory://model",
      version: 7,
    },
  });
  const state = latestPageState(harness.messages);
  assert.equal(state.detected, true);
  assert.equal(state.problemTitle, "Two Sum");
  assert.equal(state.problemSlug, "two-sum");
  assert.equal(state.language, "java");
  assert.equal(state.code, "class Solution {\n  // off-screen comment\n}");
  assert.equal(state.codeVersion, 1);

  harness.flushCodeDebounce();
  const update = harness.messages.find((message) => message.type === "CODE_UPDATE");
  assert.deepEqual(JSON.parse(JSON.stringify(update.payload)), {
    protocolVersion: 1,
    pageUrl: "https://leetcode.com/problems/two-sum/",
    language: "java",
    code: "class Solution {\n  // off-screen comment\n}",
    codeVersion: 1,
  });
});

test("content script ignores spoofed page messages from another window", () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  harness.tick();
  const before = harness.messages.length;
  harness.dispatch(
    {
      source: "leetcode-ai-interviewer-page-bridge",
      protocolVersion: 1,
      type: "CODE_SNAPSHOT",
      payload: { code: "pass", language: "python", modelUri: null, version: 1 },
    },
    {},
  );
  assert.equal(harness.messages.length, before);
});
