#!/usr/bin/env node
"use strict";

const assert = require("assert");
const path = require("path");

const root = path.resolve(__dirname, "..");

const runtimePaths = [
  path.join(root, "web", "playground", "static-runtime.js"),
  path.join(root, "src", "e_base_computer_web", "playground", "static-runtime.js"),
];
const expectedSlugs = ["factorial", "e-ladder", "cold-memory", "thermal-degrade", "branching"];

for (const runtimePath of runtimePaths) {
  smokeRuntime(runtimePath);
}

const pageRoots = [
  path.join(root, "web", "playground"),
  path.join(root, "src", "e_base_computer_web", "playground"),
];

function smokeRuntime(runtimePath) {
  delete require.cache[require.resolve(runtimePath)];
  const runtime = require(runtimePath);

  assert(runtime, `${runtimePath} exports runtime`);
  assert.strictEqual(typeof runtime.samples, "function", `${runtimePath} samples()`);
  assert.strictEqual(typeof runtime.run, "function", `${runtimePath} run()`);
  assert.strictEqual(
    typeof runtime.runChallengeSuite,
    "function",
    `${runtimePath} runChallengeSuite()`,
  );

  const samples = runtime.samples();
  assert(samples.length >= 5, `${runtimePath} sample count`);
  assert(samples.some((sample) => sample.slug === "thermal-degrade"), `${runtimePath} thermal sample`);
  assert(samples.every((sample) => sample.description), `${runtimePath} sample descriptions`);

  const cResult = runtime.run({
    source: "let n = 5; let acc = 1; while (n > 1) { acc = acc * n; n = n - 1; } print(acc);",
    language: "c",
    precision: 8,
    maxSteps: 10000,
  });
  assert.strictEqual(cResult.static_fallback, true, `${runtimePath} c static fallback`);
  assert.strictEqual(cResult.output.OUT0, 120, `${runtimePath} c output`);
  assert(cResult.assembly.includes("EPRINT"), `${runtimePath} c assembly`);
  assert(Array.isArray(cResult.timeline), `${runtimePath} c timeline`);

  const asmResult = runtime.run({
    source: "ECONST ER0, 7.5\nEOBS OUT0, ER0 ; precision=8\n",
    language: "asm",
    precision: 8,
    maxSteps: 10000,
  });
  assert.strictEqual(asmResult.static_fallback, true, `${runtimePath} asm static fallback`);
  assert.strictEqual(asmResult.output.OUT0, 7.5, `${runtimePath} asm output`);
  assert(asmResult.score.steps >= 2, `${runtimePath} asm score`);

  const challenge = runtime.runChallengeSuite();
  assert.strictEqual(challenge.ok, true, `${runtimePath} challenge ok`);
  assert.strictEqual(challenge.static_fallback, true, `${runtimePath} challenge static fallback`);
  assert.strictEqual(challenge.correct, true, `${runtimePath} challenge correct`);
  assert.strictEqual(challenge.results.length, 5, `${runtimePath} challenge count`);
  assert.strictEqual(challenge.total_score, 297.9, `${runtimePath} challenge score`);
  assert.deepStrictEqual(
    challenge.results.map((result) => result.slug),
    expectedSlugs,
    `${runtimePath} challenge slugs`,
  );
  assert(
    challenge.results.some((result) => result.slug === "thermal-degrade" && result.score.degraded_events >= 1),
    `${runtimePath} challenge thermal degradation`,
  );
}

async function smokeStaticPage(pageRoot) {
  const runtimePath = path.join(pageRoot, "static-runtime.js");
  const appPath = path.join(pageRoot, "app.js");
  const document = createDocument();
  const window = {
    document,
    location: {href: "https://example.test/playground/", hash: ""},
    addEventListener() {},
    EBaseStaticRuntime: undefined,
  };
  const unhandled = [];
  const onUnhandled = (reason) => unhandled.push(reason);
  const originalWarn = console.warn;
  process.on("unhandledRejection", onUnhandled);
  console.warn = () => undefined;

  global.window = window;
  global.document = document;
  defineGlobal("navigator", {clipboard: {writeText: async () => undefined}});
  defineGlobal("history", {replaceState(_state, _title, url) { window.location.href = String(url); }});
  defineGlobal("fetch", async () => {
    throw new Error("static smoke blocks API fetch");
  });

  try {
    delete require.cache[require.resolve(runtimePath)];
    delete require.cache[require.resolve(appPath)];
    window.EBaseStaticRuntime = require(runtimePath);
    require(appPath);
    await settle();

    assert.strictEqual(text("engineStatus"), "static fallback", `${pageRoot} engine status`);
    assert(optionValues(document.getElementById("sampleSelect")).includes("thermal-degrade"), `${pageRoot} sample options`);
    assert(text("sampleDescription").length > 0, `${pageRoot} sample description`);
    assert(text("outputView").includes('"OUT0": 120'), `${pageRoot} initial run output`);
    assert(metricsText(document).includes("engine"), `${pageRoot} metrics engine label`);
    assert(metricsText(document).includes("static"), `${pageRoot} metrics static value`);

    await document.getElementById("challengeButton").click();
    await settle();

    assert(text("challengeStatus").startsWith("demo only correct=true"), `${pageRoot} demo challenge status`);
    assert.strictEqual(document.getElementById("copyChallengeButton").disabled, true, `${pageRoot} copy disabled`);
    const challengePayload = JSON.parse(text("challengeView"));
    assert.strictEqual(challengePayload.demo_only, true, `${pageRoot} demo_only payload`);
    assert.strictEqual(challengePayload.official_submission, false, `${pageRoot} official submission flag`);
    assert.strictEqual(challengePayload.total_score, 297.9, `${pageRoot} static challenge score`);
    assert.deepStrictEqual(
      challengePayload.results.map((result) => result.slug),
      expectedSlugs,
      `${pageRoot} static challenge slugs`,
    );
    assert.deepStrictEqual(unhandled, [], `${pageRoot} unhandled rejections`);
  } finally {
    console.warn = originalWarn;
    process.off("unhandledRejection", onUnhandled);
  }

  function text(id) {
    return document.getElementById(id).textContent;
  }
}

function createDocument() {
  const byId = new Map();
  const document = {
    createElement(tagName) {
      return new Element(tagName);
    },
    getElementById(id) {
      return byId.get(id);
    },
  };
  const ids = [
    ["sourceEditor", "textarea"],
    ["sampleSelect", "select"],
    ["languageSelect", "select"],
    ["precisionInput", "input"],
    ["runButton", "button"],
    ["copyLinkButton", "button"],
    ["challengeButton", "button"],
    ["copyChallengeButton", "button"],
    ["metrics", "div"],
    ["outputView", "pre"],
    ["assemblyView", "pre"],
    ["challengeStatus", "span"],
    ["challengeView", "pre"],
    ["shareStatus", "span"],
    ["engineStatus", "span"],
    ["eventList", "div"],
    ["registerLadder", "div"],
    ["fieldMap", "div"],
    ["timelineCanvas", "canvas"],
    ["sampleDescription", "div"],
  ];
  for (const [id, tagName] of ids) {
    const element = new Element(tagName);
    element.id = id;
    byId.set(id, element);
  }
  byId.get("languageSelect").value = "c";
  byId.get("precisionInput").value = "8";
  byId.get("copyChallengeButton").disabled = true;
  byId.get("timelineCanvas").width = 900;
  byId.get("timelineCanvas").height = 220;
  return document;
}

class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.attributes = {};
    this.disabled = false;
    this.value = "";
    this.id = "";
    this.className = "";
    this._textContent = "";
    this._innerHTML = "";
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    if (this.tagName === "SELECT" && !this.value) {
      this.value = child.value;
    }
    return child;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  async click() {
    const listeners = this.listeners.get("click") || [];
    await Promise.all(listeners.map((listener) => listener({target: this})));
  }

  querySelector(selector) {
    const optionValue = selector.match(/^option\[value="(.+)"\]$/);
    if (optionValue) {
      return this.children.find((child) => child.tagName === "OPTION" && child.value === optionValue[1]) || null;
    }
    return null;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    this._textContent = stripTags(this._innerHTML);
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._textContent = String(value);
    this._innerHTML = "";
    this.children = [];
  }

  get textContent() {
    const childText = this.children.map((child) => child.textContent).join("");
    return `${this._textContent}${childText}`;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getContext() {
    return {
      clearRect() {},
      fillRect() {},
      beginPath() {},
      moveTo() {},
      lineTo() {},
      stroke() {},
      fillText() {},
      set fillStyle(_value) {},
      set strokeStyle(_value) {},
      set lineWidth(_value) {},
      set font(_value) {},
    };
  }
}

function optionValues(select) {
  return select.children.filter((child) => child.tagName === "OPTION").map((child) => child.value);
}

function metricsText(document) {
  return document.getElementById("metrics").children.map((child) => child.textContent).join(" ");
}

function stripTags(value) {
  return String(value).replace(/<[^>]*>/g, "");
}

function defineGlobal(name, value) {
  Object.defineProperty(global, name, {
    value,
    configurable: true,
    writable: true,
  });
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

(async () => {
  for (const pageRoot of pageRoots) {
    await smokeStaticPage(pageRoot);
  }
  console.log("static_playground_smoke_ok");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
