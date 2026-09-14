#!/usr/bin/env node
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const corpus = JSON.parse(fs.readFileSync(path.join(root, "conformance", "runtime-v1.json"), "utf8"));
const runtimePaths = [
  path.join(root, "web", "playground", "static-runtime.js"),
  path.join(root, "src", "e_base_computer_web", "playground", "static-runtime.js"),
];

assert.strictEqual(corpus.corpus_version, 1);
assert.strictEqual(corpus.runtime_schema_version, 1);

for (const runtimePath of runtimePaths) {
  delete require.cache[require.resolve(runtimePath)];
  const runtime = require(runtimePath);
  for (const testCase of corpus.cases) {
    const actual = runtime.run({source: testCase.source, language: "asm", precision: 8, maxSteps: 10000});
    verify(actual, testCase.expected, corpus.float_tolerance, `${runtimePath}:${testCase.id}`);
  }
}

console.log(`static_conformance_ok cases=${corpus.cases.length} runtimes=${runtimePaths.length}`);

function verify(actual, expected, tolerance, label) {
  assert.strictEqual(actual.steps, expected.steps, `${label}:steps`);
  assert.strictEqual(actual.halted, expected.halted, `${label}:halted`);
  assert.strictEqual(actual.snapshot.tick, expected.steps, `${label}:snapshot tick`);
  assert.deepStrictEqual(actual.timeline.map((event) => event.op), expected.ops, `${label}:ops`);
  assert.deepStrictEqual(actual.timeline.map((event) => event.tick), expected.ticks, `${label}:ticks`);
  assert.deepStrictEqual(actual.timeline.map((event) => [...new Set(event.flags.filter((flag) => flag !== "OK"))].sort()), expected.flags, `${label}:flags`);
  floatTree(actual.output, expected.output, tolerance, `${label}:output`);
  for (const [name, registerExpected] of Object.entries(expected.registers)) {
    floatTree(actual.snapshot.er[name], registerExpected, tolerance, `${label}:${name}`);
  }
  assert.deepStrictEqual(Object.keys(actual.snapshot.fields).sort(), Object.keys(expected.fields).sort(), `${label}:fields`);
  for (const [name, fieldExpected] of Object.entries(expected.fields)) {
    const field = actual.snapshot.fields[name];
    assert.deepStrictEqual({bank_id: field.bank_id, length: field.cells.length, current_partition: field.current_partition}, fieldExpected, `${label}:${name}`);
  }
}

function floatTree(actual, expected, tolerance, label) {
  if (expected !== null && typeof expected === "object" && !Array.isArray(expected)) {
    assert(actual !== null && typeof actual === "object", `${label}:object`);
    for (const [key, value] of Object.entries(expected)) {
      assert(Object.prototype.hasOwnProperty.call(actual, key), `${label}:missing ${key}`);
      floatTree(actual[key], value, tolerance, `${label}.${key}`);
    }
  } else if (typeof expected === "number") {
    assert.strictEqual(typeof actual, "number", `${label}:number`);
    assert(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)), `${label}:${actual} != ${expected}`);
  } else {
    assert.deepStrictEqual(actual, expected, label);
  }
}
