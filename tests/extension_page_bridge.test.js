const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function makeModel(code, language, uri, { attached = false } = {}) {
  let value = code;
  let version = 1;
  return {
    getValue: () => value,
    getLanguageId: () => language,
    getVersionId: () => version,
    isAttachedToEditor: () => attached,
    uri: { toString: () => uri },
    setValue(nextValue) {
      value = nextValue;
      version += 1;
    },
  };
}

test("page bridge selects the largest non-plaintext Monaco model", () => {
  const messages = [];
  const callbacks = [];
  const window = {
    location: { href: "https://leetcode.com/problems/two-sum/", origin: "https://leetcode.com" },
    postMessage(message, targetOrigin) {
      messages.push({ message, targetOrigin });
    },
    monaco: {
      editor: {
        getModels: () => [
          makeModel("plaintext should be ignored even when longer", "plaintext", "plain"),
          makeModel("pass", "python", "python"),
          makeModel("public class Solution {}", "java", "java"),
        ],
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    window,
    setInterval(callback) {
      callbacks.push(callback);
      return 1;
    },
    console,
  });
  assert.equal(messages.length, 1);
  assert.equal(messages[0].message.type, "CODE_SNAPSHOT");
  assert.equal(messages[0].message.payload.language, "java");
  assert.equal(messages[0].targetOrigin, "https://leetcode.com");
});

test("page bridge reacquires the model after SPA navigation", () => {
  const messages = [];
  let poll;
  const model = makeModel("pass", "python", "model");
  const window = {
    location: { href: "https://leetcode.com/problems/two-sum/", origin: "https://leetcode.com" },
    postMessage(message) {
      messages.push(message);
    },
    monaco: { editor: { getModels: () => [model] } },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    window,
    setInterval(callback) {
      poll = callback;
      return 1;
    },
    console,
  });
  assert.equal(messages.length, 1);
  window.location.href = "https://leetcode.com/problems/valid-parentheses/";
  poll();
  assert.equal(messages.length, 2);
  assert.equal(messages[1].type, "CODE_SNAPSHOT");
});

test("page bridge republishes an unchanged snapshot for a delayed listener", () => {
  const messages = [];
  let now = 1000;
  let poll;
  const window = {
    location: { href: "https://leetcode.com/problems/two-sum/", origin: "https://leetcode.com" },
    postMessage(message) {
      messages.push(message);
    },
    monaco: { editor: { getModels: () => [makeModel("pass", "python", "model")] } },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    Date: { now: () => now },
    window,
    setInterval(callback) {
      poll = callback;
      return 1;
    },
    console,
  });

  assert.equal(messages.length, 1);
  poll();
  assert.equal(messages.length, 1);
  now += 3000;
  poll();
  assert.equal(messages.length, 2);
  assert.equal(messages[1].type, "CODE_SNAPSHOT");
});

test("page bridge switches from a static starter model to the model receiving edits", () => {
  const messages = [];
  let poll;
  const starter = makeModel(
    "class Solution { public: int maxProfit(vector<int>& prices) { return 0; } };",
    "cpp",
    "starter",
  );
  const editor = makeModel("class Solution {}", "cpp", "editor");
  const window = {
    location: { href: "https://leetcode.com/problems/best-time-to-buy-and-sell-stock/", origin: "https://leetcode.com" },
    postMessage(message) {
      messages.push(message);
    },
    monaco: { editor: { getModels: () => [starter, editor] } },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    window,
    setInterval(callback) {
      poll = callback;
      return 1;
    },
    console,
  });

  assert.equal(messages[0].payload.editorDetected, true);
  editor.setValue("class Solution {\n  int answer = 42;\n}");
  poll();

  assert.equal(messages.length, 2);
  assert.equal(messages[1].payload.editorDetected, true);
  assert.equal(messages[1].payload.code, "class Solution {\n  int answer = 42;\n}");
});

test("page bridge prefers a model attached to the visible editor", () => {
  const messages = [];
  const window = {
    location: { href: "https://leetcode.com/problems/two-sum/", origin: "https://leetcode.com" },
    postMessage(message) {
      messages.push(message);
    },
    monaco: {
      editor: {
        getModels: () => [
          makeModel("a much longer stale starter implementation", "python", "starter"),
          makeModel("class Solution: pass", "python", "editor", { attached: true }),
        ],
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    window,
    setInterval() {
      return 1;
    },
    console,
  });

  assert.equal(messages[0].payload.editorDetected, true);
  assert.equal(messages[0].payload.code, "class Solution: pass");
});

test("page bridge reports an attached empty editor separately from its code", () => {
  const messages = [];
  const window = {
    location: { href: "https://leetcode.com/problems/two-sum/", origin: "https://leetcode.com" },
    postMessage(message) {
      messages.push(message);
    },
    monaco: {
      editor: {
        getModels: () => [
          makeModel("stale starter implementation", "python", "starter"),
          makeModel("", "python", "editor", { attached: true }),
        ],
      },
    },
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "page_bridge.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    window,
    setInterval() {
      return 1;
    },
    console,
  });

  assert.equal(messages[0].message?.type || messages[0].type, "CODE_SNAPSHOT");
  const snapshot = messages[0].message?.payload || messages[0].payload;
  assert.equal(snapshot.editorDetected, true);
  assert.equal(snapshot.code, "");
});
