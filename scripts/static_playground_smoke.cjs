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
const numericalSlugs = ["numerical-polynomial", "numerical-cancellation", "numerical-recurrence"];

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
  assert.strictEqual(typeof runtime.compileC, "function", `${runtimePath} compileC()`);
  assert.strictEqual(
    typeof runtime.runChallengeSuite,
    "function",
    `${runtimePath} runChallengeSuite()`,
  );

  const samples = runtime.samples();
  assert(samples.length >= 8, `${runtimePath} sample count`);
  assert(samples.some((sample) => sample.slug === "thermal-degrade"), `${runtimePath} thermal sample`);
  assert.deepStrictEqual(
    samples.filter((sample) => sample.slug.startsWith("numerical-")).map((sample) => sample.slug),
    numericalSlugs,
    `${runtimePath} numerical samples`,
  );
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
  assert(cResult.assembly.includes("EJGTZ"), `${runtimePath} c comparison lowering`);
  assert(!/\bC(?:LET|SET|PRINT|WHILE|IF)\b/.test(cResult.assembly), `${runtimePath} no direct-evaluator pseudo ops`);
  assert(cResult.timeline.every((event) => /^E[A-Z]+$/.test(event.op)), `${runtimePath} C executes through EPU assembly`);
  assert(Array.isArray(cResult.timeline), `${runtimePath} c timeline`);

  const compiled = runtime.compileC("let x = 1 + 2 * 3; print(-x);", 8);
  assert.strictEqual(compiled.symbols.x, "ER2", `${runtimePath} promoted initializer register`);
  assert(compiled.assembly.includes("EMUL"), `${runtimePath} multiplication precedence`);
  assert(compiled.assembly.includes("ESUB"), `${runtimePath} unary minus lowering`);
  assert.throws(
    () => runtime.compileC("print(missing);", 8),
    (error) => error.name === "CStyleCompileError" && error.message === "unknown variable: missing near token 3",
    `${runtimePath} compiler diagnostics`,
  );

  const asmResult = runtime.run({
    source: "ECONST ER0, 7.5\nEOBS OUT0, ER0 ; precision=8\n",
    language: "asm",
    precision: 8,
    maxSteps: 10000,
  });
  assert.strictEqual(asmResult.static_fallback, true, `${runtimePath} asm static fallback`);
  assert.strictEqual(asmResult.output.OUT0, 7.5, `${runtimePath} asm output`);
  assert.strictEqual(asmResult.schema_version, 1, `${runtimePath} runtime schema`);
  assert.strictEqual(asmResult.score.steps, 2, `${runtimePath} asm steps`);
  assert.strictEqual(asmResult.score.score, 14.8, `${runtimePath} asm score parity`);
  assert.strictEqual(asmResult.snapshot.tick, 2, `${runtimePath} asm tick`);
  assert.deepStrictEqual(asmResult.timeline.map((event) => event.tick), [0, 1], `${runtimePath} asm event ticks`);

  const challenge = runtime.runChallengeSuite();
  assert.strictEqual(challenge.ok, true, `${runtimePath} challenge ok`);
  assert.strictEqual(challenge.static_fallback, true, `${runtimePath} challenge static fallback`);
  assert.strictEqual(challenge.challenge_schema_version, 2, `${runtimePath} challenge schema`);
  assert.strictEqual(challenge.emulator_version, "0.2.0", `${runtimePath} emulator version`);
  assert.strictEqual(challenge.scoring_model, "official-score-v1", `${runtimePath} official scoring model`);
  assert.strictEqual(challenge.correct, true, `${runtimePath} challenge correct`);
  assert.strictEqual(challenge.results.length, 5, `${runtimePath} challenge count`);
  assert.strictEqual(challenge.total_score, 366.6, `${runtimePath} Python challenge score parity`);
  assert.deepStrictEqual(
    challenge.results.map((result) => result.slug),
    expectedSlugs,
    `${runtimePath} challenge slugs`,
  );
  assert(
    challenge.results.some((result) => result.slug === "thermal-degrade" && result.score.degraded_events >= 1),
    `${runtimePath} challenge thermal degradation`,
  );
  const scoreBySlug = Object.fromEntries(challenge.results.map((result) => [result.slug, result.score.score]));
  assert.strictEqual(scoreBySlug["e-ladder"], 20.7, `${runtimePath} e-ladder Python parity`);
  assert.strictEqual(scoreBySlug["cold-memory"], 20.2, `${runtimePath} cold-memory Python parity`);
  assert.strictEqual(scoreBySlug["thermal-degrade"], 230.5, `${runtimePath} thermal Python parity`);
  assert.strictEqual(scoreBySlug.factorial, 70.7, `${runtimePath} factorial Python parity`);
  assert.strictEqual(scoreBySlug.branching, 24.5, `${runtimePath} branching Python parity`);

  const numerical = runtime.runChallengeSuite("numerical");
  assert.strictEqual(numerical.suite, "numerical", `${runtimePath} numerical suite`);
  assert.strictEqual(numerical.challenge_schema_version, 2, `${runtimePath} numerical challenge schema`);
  assert.strictEqual(numerical.emulator_version, "0.2.0", `${runtimePath} numerical emulator version`);
  assert.strictEqual(numerical.scoring_model, "numerical-score-v1", `${runtimePath} numerical scoring model`);
  assert.strictEqual(numerical.correct, true, `${runtimePath} numerical correct`);
  assert.strictEqual(numerical.total_score, 302.304481, `${runtimePath} numerical Python parity`);
  assert.strictEqual(numerical.performance_score, 302.3, `${runtimePath} numerical performance parity`);
  assert.strictEqual(numerical.mean_accuracy_digits, 11.115, `${runtimePath} numerical accuracy parity`);
  assert.deepStrictEqual(
    numerical.results.map((result) => result.slug),
    numericalSlugs,
    `${runtimePath} numerical slugs`,
  );
}

async function smokeStaticPage(pageRoot) {
  const runtimePath = path.join(pageRoot, "static-runtime.js");
  const appPath = path.join(pageRoot, "app.js");
  const document = createDocument();
  const windowListeners = new Map();
  const window = {
    document,
    location: {href: "https://example.test/playground/", protocol: "https:", hostname: "example.test", hash: ""},
    addEventListener(type, listener) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(listener);
      windowListeners.set(type, listeners);
    },
    async dispatch(type) {
      await Promise.all((windowListeners.get(type) || []).map((listener) => listener()));
    },
    EBaseStaticRuntime: undefined,
  };
  let clipboardText = "";
  const unhandled = [];
  const onUnhandled = (reason) => unhandled.push(reason);
  const originalWarn = console.warn;
  process.on("unhandledRejection", onUnhandled);
  console.warn = () => undefined;

  global.window = window;
  global.document = document;
  defineGlobal("navigator", {clipboard: {writeText: async (value) => { clipboardText = String(value); }}});
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
    await settle();

    assert.strictEqual(text("engineStatus"), "static fallback", `${pageRoot} engine status`);
    assert(optionValues(document.getElementById("sampleSelect")).includes("thermal-degrade"), `${pageRoot} sample options`);
    assert(text("sampleDescription").length > 0, `${pageRoot} sample description`);
    assert(text("outputView").includes('"OUT0": 120'), `${pageRoot} initial run output`);
    assert(metricsText(document).includes("engine"), `${pageRoot} metrics engine label`);
    assert(metricsText(document).includes("static"), `${pageRoot} metrics static value`);

    document.getElementById("sourceEditor").value = "ECONST ER0, 9\nEOBS OUT0, ER0 ; precision=5";
    document.getElementById("languageSelect").value = "asm";
    document.getElementById("precisionInput").value = "5";
    await document.getElementById("copyLinkButton").click();
    const sharedUrl = new URL(clipboardText);
    const sharedParams = new URLSearchParams(sharedUrl.hash.slice(1));
    assert.strictEqual(sharedParams.get("source"), document.getElementById("sourceEditor").value, `${pageRoot} share source`);
    assert.strictEqual(sharedParams.get("lang"), "asm", `${pageRoot} share language`);
    assert.strictEqual(sharedParams.get("precision"), "5", `${pageRoot} share precision`);
    document.getElementById("sourceEditor").value = "changed";
    window.location.hash = sharedUrl.hash;
    await window.dispatch("hashchange");
    await settle();
    assert.strictEqual(document.getElementById("sourceEditor").value, sharedParams.get("source"), `${pageRoot} share restore source`);
    assert.strictEqual(text("shareStatus"), "shared link", `${pageRoot} share restore status`);
    assert(text("outputView").includes('"OUT0": 9'), `${pageRoot} shared program runs`);

    await document.getElementById("challengeButton").click();
    await settle();

    assert(text("challengeStatus").startsWith("demo official correct=true"), `${pageRoot} demo challenge status`);
    assert.strictEqual(document.getElementById("copyChallengeButton").disabled, true, `${pageRoot} copy disabled`);
    assert(text("challengeView").includes("thermal-degrade"), `${pageRoot} official challenge table`);
    document.getElementById("challengeSuiteSelect").value = "numerical";
    await document.getElementById("challengeButton").click();
    await settle();
    assert(text("challengeStatus").startsWith("demo numerical correct=true"), `${pageRoot} numerical status`);
    assert(text("challengeView").includes("numerical-recurrence"), `${pageRoot} numerical challenge table`);
    assert(text("timelineStatus").includes("tick"), `${pageRoot} timeline selected tick`);
    assert(text("stepDetail").includes("q_max="), `${pageRoot} step precision detail`);
    assert(document.getElementById("operationProfile").children.length > 0, `${pageRoot} operation profile`);
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
    ["challengeSuiteSelect", "select"],
    ["copyChallengeButton", "button"],
    ["metrics", "div"],
    ["outputView", "pre"],
    ["assemblyView", "pre"],
    ["challengeStatus", "span"],
    ["challengeView", "div"],
    ["shareStatus", "span"],
    ["engineStatus", "span"],
    ["eventList", "div"],
    ["registerLadder", "div"],
    ["fieldMap", "div"],
    ["timelineCanvas", "canvas"],
    ["timelineScrubber", "input"],
    ["timelineStatus", "span"],
    ["stepDetail", "pre"],
    ["operationProfile", "div"],
    ["sampleDescription", "div"],
  ];
  for (const [id, tagName] of ids) {
    const element = new Element(tagName);
    element.id = id;
    byId.set(id, element);
  }
  byId.get("languageSelect").value = "c";
  byId.get("precisionInput").value = "8";
  byId.get("challengeSuiteSelect").value = "official";
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
    this.style = {};
    this._textContent = "";
    this._innerHTML = "";
    this.classList = {
      toggle: (name, enabled) => {
        const classes = new Set(this.className.split(/\s+/).filter(Boolean));
        if (enabled) classes.add(name);
        else classes.delete(name);
        this.className = Array.from(classes).join(" ");
      },
    };
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    if (this.tagName === "SELECT" && !this.value) {
      this.value = child.value;
    }
    return child;
  }

  append(...children) {
    children.forEach((child) => this.appendChild(child));
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
