const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function makeModel(code, language, uri) {
  return {
    getValue: () => code,
    getLanguageId: () => language,
    getVersionId: () => 1,
    uri: { toString: () => uri },
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

