const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function textElement(text, onClone = () => {}) {
  return {
    textContent: text,
    cloneNode() {
      onClone();
      return {
        textContent: text,
        querySelectorAll() {
          return [];
        },
      };
    },
  };
}

function loadContent({ title = "Two Sum", description = "", descriptionSelector = "data-track" } = {}) {
  const messages = [];
  const intervals = [];
  const timeouts = [];
  let descriptionCloneCount = 0;
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
  const descriptionElement = description
    ? textElement(description, () => { descriptionCloneCount += 1; })
    : null;
  const document = {
    querySelector(selector) {
      if (selector.includes("question-title")) {
        return titleElement;
      }
      if (selector.includes(descriptionSelector)) {
        return descriptionElement;
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes("question-title")) {
        return titleElement ? [titleElement] : [];
      }
      if (selector.includes(descriptionSelector)) {
        return descriptionElement ? [descriptionElement] : [];
      }
      return [];
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
    getDescriptionCloneCount() {
      return descriptionCloneCount;
    },
    navigate(href, pathname) {
      window.location.href = href;
      window.location.pathname = pathname;
    },
    requestPageState,
  };
}

async function latestPageState(harness) {
  const response = await harness.requestPageState({ type: "REQUEST_PAGE_STATE" });
  return response.pageState;
}

test("content script reports actionable extraction failure", async () => {
  const harness = loadContent({ title: "Two Sum" });
  harness.tick();
  const state = await latestPageState(harness);
  assert.equal(state.detected, false);
  assert.equal(
    state.error,
    "The LeetCode problem description was not detected. The interview was not started.",
  );
});

test("content script combines the problem and complete code snapshot", async () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  harness.tick();
  harness.dispatch({
    source: "leetcode-ai-interviewer-page-bridge",
    protocolVersion: 1,
    type: "CODE_SNAPSHOT",
    payload: {
      code: "class Solution {\n  // off-screen comment\n}",
      language: "java",
      editorDetected: true,
      version: 7,
    },
  });
  const state = await latestPageState(harness);
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

test("content script supports the data-key description container", async () => {
  const harness = loadContent({
    description: "Description text. ".repeat(20),
    descriptionSelector: "data-key",
  });
  harness.tick();
  const state = await latestPageState(harness);
  assert.equal(state.problemText, "Description text. ".repeat(20).trim());
  assert.equal(state.error, "LeetCode editor model was not detected. Reload the problem page and try again.");
});

test("content script treats an empty detected editor as valid code", async () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  harness.dispatch({
    source: "leetcode-ai-interviewer-page-bridge",
    protocolVersion: 1,
    type: "CODE_SNAPSHOT",
    payload: { code: "", language: "python", editorDetected: true, version: 1 },
  });

  const state = await latestPageState(harness);
  assert.equal(state.detected, true);
  assert.equal(state.editorDetected, true);
  harness.flushCodeDebounce();
  const update = harness.messages.find((message) => message.type === "CODE_UPDATE");
  assert.equal(update.payload.code, "");
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
      payload: { code: "pass", language: "python", editorDetected: true, version: 1 },
    },
    {},
  );
  assert.equal(harness.messages.length, before);
});

test("content script caches an extracted problem description until navigation", async () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  harness.tick();
  harness.tick();
  await latestPageState(harness);
  assert.equal(harness.getDescriptionCloneCount(), 1);

  harness.navigate(
    "https://leetcode.com/problems/valid-parentheses/",
    "/problems/valid-parentheses/",
  );
  harness.tick();
  assert.equal(harness.getDescriptionCloneCount(), 2);
  assert.equal((await latestPageState(harness)).problemSlug, "valid-parentheses");
});

test("content script accepts and throttles typing activity", () => {
  const harness = loadContent({ description: "Description text. ".repeat(20) });
  const activity = {
    source: "leetcode-ai-interviewer-page-bridge",
    protocolVersion: 1,
    type: "TYPING_ACTIVITY",
    payload: {},
  };
  harness.dispatch(activity);
  harness.dispatch(activity);

  const typingMessages = harness.messages.filter((message) => message.type === "TYPING_ACTIVITY");
  assert.equal(typingMessages.length, 1);
  assert.equal(typingMessages[0].payload.activity, "typing");
});
