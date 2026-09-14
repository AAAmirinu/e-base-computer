#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const runtime = require(path.join(root, "web", "playground", "static-runtime.js"));
const request = JSON.parse(fs.readFileSync(0, "utf8"));

function execute(testCase) {
  try {
    const result = runtime.run({
      source: testCase.source,
      language: "asm",
      precision: testCase.precision === undefined ? 8 : testCase.precision,
      maxSteps: testCase.max_steps === undefined ? 10000 : testCase.max_steps,
    });
    return {
      name: testCase.name,
      ok: true,
      output: result.output,
      halted: result.halted,
      steps: result.steps,
      pc: result.pc,
      operations: result.timeline.map((event) => event.op),
      snapshot: result.snapshot,
    };
  } catch (error) {
    return {
      name: testCase.name,
      ok: false,
      error_name: error.name,
      error_code: error.code || null,
      error: error.message,
    };
  }
}

process.stdout.write(JSON.stringify({
  public_opcodes: runtime.publicOpcodes(),
  results: request.cases.map(execute),
}));
