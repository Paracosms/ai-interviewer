const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const manifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "extension", "manifest.json"),
  "utf8",
));

test("page bridge is injected directly into the page main world", () => {
  const bridgeRegistration = manifest.content_scripts.find((registration) => (
    registration.js?.includes("page_bridge.js")
  ));
  assert.ok(bridgeRegistration, "expected page_bridge.js to be a registered content script");
  assert.equal(bridgeRegistration.world, "MAIN");
  assert.equal(bridgeRegistration.run_at, "document_start");
});

test("isolated content script runs separately from the page bridge", () => {
  const contentRegistration = manifest.content_scripts.find((registration) => (
    registration.js?.includes("content.js")
  ));
  assert.ok(contentRegistration, "expected content.js to be a registered content script");
  assert.notEqual(contentRegistration.world, "MAIN");
  assert.equal(contentRegistration.run_at, "document_start");
  assert.ok(
    manifest.content_scripts.indexOf(contentRegistration) <
      manifest.content_scripts.indexOf(manifest.content_scripts.find((registration) => (
        registration.js?.includes("page_bridge.js")
      ))),
    "content.js must register its message listener before page_bridge.js publishes",
  );
});
