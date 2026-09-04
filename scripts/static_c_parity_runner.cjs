#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const runtime = require(path.join(root, "web", "playground", "static-runtime.js"));
const request = JSON.parse(fs.readFileSync(0, "utf8"));

const results = request.cases.map((testCase) => {
  const precision = testCase.precision === undefined ? 8 : testCase.precision;
  const maxSteps = testCase.max_steps === undefined ? 10000 : testCase.max_steps;
  try {
    const compiled = runtime.compileC(testCase.source, precision);
    const executed = runtime.run({
      source: testCase.source,
      language: "c",
      precision,
      maxSteps,
    });
    return {
      name: testCase.name,
      ok: true,
      assembly: compiled.assembly,
      symbols: compiled.symbols,
      output: executed.output,
      halted: executed.halted,
      steps: executed.steps,
      pc: executed.pc,
      operations: executed.timeline.map((event) => event.op),
      score: executed.score,
    };
  } catch (error) {
    return {
      name: testCase.name,
      ok: false,
      error_name: error.name,
      error: error.message,
    };
  }
});

process.stdout.write(JSON.stringify({results}));
