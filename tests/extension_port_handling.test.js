const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadBackground(fetchImpl = null) {
  const listeners = [];
  const storage = {};
  const requests = [];
  const browser = {
    storage: {
      local: {
        async get(key) {
          return { [key]: storage[key] };
        },
        async set(values) {
          Object.assign(storage, values);
        },
      },
    },
    runtime: {
      onMessage: {
        addListener(listener) {
          listeners.push(listener);
        },
      },
    },
    tabs: {
      onRemoved: {
        addListener() {},
      },
    },
  };
  const fetch = fetchImpl || (async (url) => {
    requests.push(url);
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, sessionStatus: "stopped" };
      },
    };
  });
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "background.js"),
    "utf8",
  );
  vm.runInNewContext(source, {
    browser,
    fetch,
    AbortController,
    clearTimeout,
    setTimeout,
    console,
  });
  return { listener: listeners[0], storage, requests };
}

test("defaults to 8765 and persists a valid saved port", async () => {
  const background = loadBackground();
  assert.equal((await background.listener({ type: "GET_HOST_PORT" }, {})).port, 8765);
  const response = await background.listener({ type: "SAVE_HOST_PORT", port: "8766" }, {});
  assert.equal(response.ok, true);
  assert.equal(background.storage.hostPort, 8766);
  assert.match(background.requests[0], /^http:\/\/127\.0\.0\.1:8766\/health$/);
});

test("rejects invalid ports without making a request", async () => {
  const background = loadBackground();
  const response = await background.listener({ type: "SAVE_HOST_PORT", port: "70000" }, {});
  assert.equal(response.ok, false);
  assert.equal(response.error, "Host port must be a number between 1 and 65535.");
  assert.equal(background.requests.length, 0);
});

test("persists a supported Gemini voice selection", async () => {
  const background = loadBackground();
  assert.equal((await background.listener({ type: "GET_GEMINI_VOICE" }, {})).voice, "Kore");
  const response = await background.listener(
    { type: "SAVE_GEMINI_VOICE", voice: "Aoede" },
    {},
  );
  assert.equal(response.ok, true);
  assert.equal(response.voice, "Aoede");
  assert.equal(background.storage.geminiVoice, "Aoede");
  assert.equal(
    (await background.listener({ type: "GET_GEMINI_VOICE" }, {})).voice,
    "Aoede",
  );
});

test("rejects an unsupported Gemini voice", async () => {
  const background = loadBackground();
  const response = await background.listener(
    { type: "SAVE_GEMINI_VOICE", voice: "NotARealVoice" },
    {},
  );
  assert.equal(response.ok, false);
  assert.equal(background.storage.geminiVoice, undefined);
});

test("all host requests use the currently stored port", async () => {
  const background = loadBackground();
  await background.listener({ type: "SAVE_HOST_PORT", port: 8766 }, {});
  await background.listener({ type: "HOST_HEALTH" }, {});
  assert.ok(background.requests.every((url) => url.startsWith("http://127.0.0.1:8766/")));
});

test("host-offline errors identify the configured port", async () => {
  const background = loadBackground(async () => {
    throw new Error("connection refused");
  });
  await background.listener({ type: "SAVE_HOST_PORT", port: 8766 }, {});
  const response = await background.listener({ type: "HOST_HEALTH" }, {});
  assert.equal(response.ok, false);
  assert.equal(response.port, 8766);
  assert.match(response.error, /not running on port 8766/);
});

test("HTTP status does not overwrite the interview status", async () => {
  const background = loadBackground(async () => ({
    ok: true,
    status: 200,
    async json() {
      return { ok: true, status: "stopped", running: false };
    },
  }));

  const response = await background.listener({ type: "GET_HOST_STATUS" }, {});
  assert.equal(response.status, "stopped");
  assert.equal(response.httpStatus, 200);
  assert.equal(response.running, false);
});
