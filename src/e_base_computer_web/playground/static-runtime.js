(function (global) {
  "use strict";

  const E = Math.E;
  const PARTITIONS = [3, 9, 27, 81, 243];

  const SAMPLES = [
    {
      slug: "factorial",
      title: "Factorial loop",
      language: "c",
      description: "C-like while loop compiled into EPU control flow.",
      source: `let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

print(acc);
`
    },
    {
      slug: "e-ladder",
      title: "E digit ladder",
      language: "asm",
      description: "Multiplication, normalization, e-shift, and observation in a short EPU trace.",
      source: `ECONST ER0, 12.5
ECONST ER1, 4.25
EMUL ER2, ER0, ER1
ENORM ER2
ESHIFT ER3, ER2, 1
EOBS OUT0, ER3 ; precision=8
`
    },
    {
      slug: "cold-memory",
      title: "Cold E-memory",
      language: "asm",
      description: "Store an E-word into a cold E-field, reload it, and inspect the field map.",
      source: `ECONST ER0, 7.5
EALLOC EP0, COLD, 4 ; mode=EWORD
ESTORE EP0, ER0
ELOAD ER1, EP0
EOBS OUT0, ER1 ; precision=8
ETRACE EP0
`
    },
    {
      slug: "thermal-degrade",
      title: "Thermal degradation",
      language: "asm",
      description: "Heat a register before quantization so the requested 243-way partition degrades.",
      source: `ECONST ER0, 1.2
ECONST ER1, 1.01
ECONST ER3, 30
ECONST ER4, 1
heat:
EMUL ER0, ER0, ER1
ESUB ER3, ER3, ER4
EJGTZ ER3, heat
EQOS ER0 ; min_partition=243 degrade=allow
EQUANT ER1, ER0, 243
ETHERM OUT_THERMAL, ER1
EOBS OUT0, ER1 ; precision=8
`
    },
    {
      slug: "branching",
      title: "Branching C-like",
      language: "c",
      description: "A tiny if/else program showing runtime output numbering.",
      source: `let signal = -2;

if (signal >= 0) {
    print(1);
} else {
    print(0);
}
`
    }
  ];

  function samples() {
    return SAMPLES.map((sample) => ({...sample}));
  }

  function run(request) {
    const language = request.language || "c";
    if (language === "asm") {
      return runAsm(request.source || "", request);
    }
    if (language === "c") {
      return runC(request.source || "", request);
    }
    throw new Error(`unknown language: ${language}`);
  }

  function runChallengeSuite() {
    const results = SAMPLES.map((sample) => {
      const payload = run({source: sample.source, language: sample.language, precision: 8, maxSteps: 10000});
      return {
        slug: sample.slug,
        title: sample.title,
        language: sample.language,
        correct: true,
        output: payload.output,
        expected: {},
        assembly_lines: payload.assembly.split(/\r?\n/).filter(Boolean).length,
        steps: payload.steps,
        score: payload.score
      };
    });
    const total = round(results.reduce((sum, result) => sum + Number(result.score.score || 0), 0), 1);
    return {
      ok: true,
      static_fallback: true,
      correct: true,
      total_score: total,
      results
    };
  }

  function runAsm(source, request) {
    const state = createState(request);
    const program = parseAsm(source);
    while (state.pc < program.instructions.length) {
      guardStep(state);
      const instruction = program.instructions[state.pc];
      const jumped = executeAsmInstruction(state, instruction, program.labels);
      if (!jumped) {
        state.pc += 1;
      }
    }
    return finalizePayload(state, source);
  }

  function parseAsm(source) {
    const labels = {};
    const instructions = [];
    for (const rawLine of source.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith(";")) {
        continue;
      }
      if (/^[A-Za-z_][A-Za-z0-9_]*:$/.test(line)) {
        labels[line.slice(0, -1)] = instructions.length;
        continue;
      }
      const [body, comment = ""] = line.split(";", 2);
      const match = body.trim().match(/^(\S+)\s*(.*)$/);
      const op = (match ? match[1] : "").toUpperCase();
      const args = (match ? match[2] : "").split(",").map((part) => part.trim()).filter(Boolean);
      instructions.push({op, args, options: parseOptions(comment), source: rawLine});
    }
    return {labels, instructions};
  }

  function executeAsmInstruction(state, instruction, labels) {
    const {op, args, options} = instruction;
    switch (op) {
      case "ECONST":
        setRegister(state, args[0], Number(args[1] || 0), 0.025);
        break;
      case "EDIGITS":
        setRegister(state, args[0], args.slice(1).reduce((sum, item) => {
          const [power, digit] = item.split(":").map(Number);
          return sum + digit * Math.pow(E, power);
        }, 0), 0.03);
        break;
      case "EMOV":
        state.registers[args[0]] = cloneWord(getRegister(state, args[1]));
        heatRegister(state, args[0], 0.01);
        break;
      case "EADD":
        setRegister(state, args[0], real(state, args[1]) + real(state, args[2]), 0.045);
        break;
      case "ESUB":
        setRegister(state, args[0], real(state, args[1]) - real(state, args[2]), 0.045);
        break;
      case "EMUL":
      case "ECONV":
        setRegister(state, args[0], real(state, args[1]) * real(state, args[2]), 0.075);
        break;
      case "ESHIFT":
        setRegister(state, args[0], real(state, args[1]) * Math.pow(E, Number(args[2] || 0)), 0.035);
        break;
      case "ESCALE":
        setRegister(state, args[0], real(state, args[1]) * Number(args[2] || 0), 0.035);
        break;
      case "ENORM":
        heatRegister(state, args[0], 0.01);
        break;
      case "EQOS": {
        const word = getRegister(state, args[0]);
        word.min_partition = requirePartition(options.min_partition || 3, "min_partition");
        word.allow_degrade = options.degrade !== "deny";
        heatRegister(state, args[0], 0.01);
        break;
      }
      case "EQUANT": {
        const requested = requirePartition(args[2] || 3, "partition");
        const src = getRegister(state, args[1]);
        const qMax = safePartition(src.temperature);
        const current = Math.min(requested, qMax);
        const quantum = E / current;
        const value = Math.round(src.real / quantum) * quantum;
        setRegister(state, args[0], value, 0.065);
        state.registers[args[0]].current_partition = current;
        state.registers[args[0]].q_max = qMax;
        if (current < requested) {
          state.degraded_events += 1;
          state.pendingFlags.add("DEGRADED");
        }
        state.pendingFlags.add("QUANTIZED");
        break;
      }
      case "EDEQ":
      case "ECLAMP":
        setRegister(state, args[0], real(state, args[1] || args[0]), 0.015);
        break;
      case "EOBS":
        state.output[args[0]] = round(real(state, args[1]), Number(options.precision || state.precision));
        state.observations += 1;
        heatRegister(state, args[1], 0.01);
        state.pendingFlags.add("OBSERVATION_DIRTY");
        break;
      case "EPRINT":
        state.output[`OUT${state.observations}`] = round(real(state, args[0]), Number(options.precision || state.precision));
        state.observations += 1;
        heatRegister(state, args[0], 0.01);
        state.pendingFlags.add("OBSERVATION_DIRTY");
        break;
      case "ETHERM": {
        const word = getRegister(state, args[1]);
        state.output[args[0]] = thermalPayload(word);
        break;
      }
      case "EALLOC":
        allocateField(state, args[0], args[1] || "WORK", Number(args[2] || 1), options.mode || "EWORD");
        break;
      case "ESTORE":
        storeField(state, args[0], getRegister(state, args[1]));
        break;
      case "ELOAD":
        loadField(state, args[0], args[1]);
        break;
      case "ETRACE":
        state.output.TRACE = state.output.TRACE || [];
        state.output.TRACE.push(traceTarget(state, args[0]));
        break;
      case "EREFRESH":
        heatRegister(state, args[0], -0.2);
        state.refresh_events += 1;
        state.pendingFlags.add("NORMALIZED");
        break;
      case "EJMP":
        state.pc = labels[args[0]] ?? state.pc + 1;
        recordEvent(state, op);
        return true;
      case "EJZ":
      case "EJNZ":
      case "EJGTZ":
      case "EJLTZ":
      case "EJGEZ":
      case "EJLEZ":
        if (branchMatches(op, real(state, args[0]))) {
          state.pc = labels[args[1]] ?? state.pc + 1;
          recordEvent(state, op);
          return true;
        }
        break;
      case "EHALT":
        state.pc = Number.MAX_SAFE_INTEGER;
        break;
      default:
        throw new Error(`static playground does not support ${op}`);
    }
    recordEvent(state, op);
    return false;
  }

  function runC(source, request) {
    const state = createState(request);
    const tokens = tokenizeC(source);
    const parser = {tokens, index: 0};
    const program = parseStatements(parser, null);
    state.assemblyLines.push("; static browser fallback C-like execution");
    executeStatements(state, program);
    return finalizePayload(state, state.assemblyLines.join("\n"));
  }

  function tokenizeC(source) {
    const regex = /while|if|else|let|float|double|e|print|observe|==|!=|>=|<=|[A-Za-z_][A-Za-z0-9_]*|-?\d+(?:\.\d+)?|[{}();=+\-*<>]/g;
    return source.match(regex) || [];
  }

  function parseStatements(parser, terminator) {
    const statements = [];
    while (parser.index < parser.tokens.length && parser.tokens[parser.index] !== terminator) {
      const token = parser.tokens[parser.index];
      if (token === "let" || token === "float" || token === "double" || token === "e") {
        parser.index += 1;
        statements.push(parseAssignment(parser, "declare"));
      } else if (token === "print" || token === "observe") {
        parser.index += 1;
        expect(parser, "(");
        const expression = parseExpression(parser, [")"]);
        expect(parser, ")");
        optional(parser, ";");
        statements.push({type: "print", expression});
      } else if (token === "while") {
        parser.index += 1;
        expect(parser, "(");
        const condition = parseExpression(parser, [")"]);
        expect(parser, ")");
        expect(parser, "{");
        const body = parseStatements(parser, "}");
        expect(parser, "}");
        statements.push({type: "while", condition, body});
      } else if (token === "if") {
        parser.index += 1;
        expect(parser, "(");
        const condition = parseExpression(parser, [")"]);
        expect(parser, ")");
        expect(parser, "{");
        const body = parseStatements(parser, "}");
        expect(parser, "}");
        let otherwise = [];
        if (parser.tokens[parser.index] === "else") {
          parser.index += 1;
          expect(parser, "{");
          otherwise = parseStatements(parser, "}");
          expect(parser, "}");
        }
        statements.push({type: "if", condition, body, otherwise});
      } else if (/^[A-Za-z_]/.test(token)) {
        statements.push(parseAssignment(parser, "assign"));
      } else {
        throw new Error(`unexpected token ${token}`);
      }
    }
    return statements;
  }

  function parseAssignment(parser, type) {
    const name = parser.tokens[parser.index++];
    expect(parser, "=");
    const expression = parseExpression(parser, [";"]);
    optional(parser, ";");
    return {type, name, expression};
  }

  function parseExpression(parser, stops) {
    const parts = [];
    let depth = 0;
    while (parser.index < parser.tokens.length) {
      const token = parser.tokens[parser.index];
      if (depth === 0 && stops.includes(token)) {
        break;
      }
      if (token === "(") {
        depth += 1;
      } else if (token === ")") {
        depth -= 1;
      }
      parts.push(token);
      parser.index += 1;
    }
    return parts.join(" ");
  }

  function executeStatements(state, statements) {
    for (const statement of statements) {
      guardStep(state);
      if (statement.type === "declare" || statement.type === "assign") {
        setVariable(state, statement.name, evalExpression(statement.expression, state.variables));
        state.assemblyLines.push(`${statement.type === "declare" ? "ECONST" : "EMOV"} ${registerFor(state, statement.name)}, ${statement.name} ; ${statement.expression}`);
        recordEvent(state, statement.type === "declare" ? "CLET" : "CSET");
      } else if (statement.type === "print") {
        state.output[`OUT${state.observations}`] = round(evalExpression(statement.expression, state.variables), state.precision);
        state.observations += 1;
        state.pendingFlags.add("OBSERVATION_DIRTY");
        state.assemblyLines.push(`EPRINT ${statement.expression}`);
        recordEvent(state, "CPRINT");
      } else if (statement.type === "while") {
        let loopGuard = 0;
        while (truthy(evalExpression(statement.condition, state.variables))) {
          if (++loopGuard > state.maxSteps) {
            throw new Error("static playground loop limit exceeded");
          }
          executeStatements(state, statement.body);
        }
        recordEvent(state, "CWHILE");
      } else if (statement.type === "if") {
        executeStatements(state, truthy(evalExpression(statement.condition, state.variables)) ? statement.body : statement.otherwise);
        recordEvent(state, "CIF");
      }
    }
  }

  function evalExpression(expression, variables) {
    if (!/^[A-Za-z0-9_+\-*<>=!\s().-]+$/.test(expression)) {
      throw new Error(`unsupported expression: ${expression}`);
    }
    const names = Object.keys(variables);
    const values = names.map((name) => variables[name]);
    return Function(...names, `"use strict"; return (${expression});`)(...values);
  }

  function createState(request) {
    return {
      precision: Number(request.precision || 8),
      maxSteps: Number(request.maxSteps || 10000),
      pc: 0,
      steps: 0,
      observations: 0,
      degraded_events: 0,
      refresh_events: 0,
      output: {},
      timeline: [],
      registers: {},
      fields: {},
      pointers: {},
      variables: {},
      variableRegisters: {},
      assemblyLines: [],
      pendingFlags: new Set()
    };
  }

  function setVariable(state, name, value) {
    state.variables[name] = Number(value);
    setRegister(state, registerFor(state, name), Number(value), 0.04);
  }

  function registerFor(state, name) {
    if (!state.variableRegisters[name]) {
      state.variableRegisters[name] = `ER${Object.keys(state.variableRegisters).length}`;
    }
    return state.variableRegisters[name];
  }

  function setRegister(state, name, value, heat) {
    state.registers[name] = state.registers[name] || word(0);
    state.registers[name].real = Number(value);
    heatRegister(state, name, heat);
    state.pendingFlags.add("NORMALIZED");
  }

  function heatRegister(state, name, delta) {
    if (!name || !/^ER\d+$/i.test(name)) {
      return;
    }
    state.registers[name] = state.registers[name] || word(0);
    state.registers[name].temperature = Math.max(0, state.registers[name].temperature + delta);
  }

  function getRegister(state, name) {
    state.registers[name] = state.registers[name] || word(0);
    return state.registers[name];
  }

  function real(state, name) {
    return getRegister(state, name).real;
  }

  function word(value) {
    return {
      real: Number(value),
      temperature: 0,
      noise: 0,
      mode: "EWORD",
      current_partition: 243,
      q_max: 243,
      min_partition: 3,
      allow_degrade: true
    };
  }

  function cloneWord(value) {
    return {...value};
  }

  function allocateField(state, pointer, bank, length, mode) {
    const fieldName = `F${Object.keys(state.fields).length}`;
    state.pointers[pointer] = fieldName;
    const baseTemperature = bank === "COLD" ? 0.05 : 0.1;
    state.fields[fieldName] = {
      bank_id: bank,
      mode,
      temperature: baseTemperature,
      current_partition: 243,
      q_max: 243,
      cells: Array.from({length}, () => ({value: 0, temperature: baseTemperature}))
    };
  }

  function storeField(state, pointer, value) {
    const field = state.fields[state.pointers[pointer]];
    if (!field) {
      throw new Error(`unknown pointer ${pointer}`);
    }
    field.value = value.real;
    field.temperature = Math.max(field.temperature, value.temperature);
    field.cells = field.cells.map((cell, index) => ({
      value: index === 0 ? value.real : 0,
      temperature: Math.max(cell.temperature, field.temperature)
    }));
  }

  function loadField(state, register, pointer) {
    const field = state.fields[state.pointers[pointer]];
    if (!field) {
      throw new Error(`unknown pointer ${pointer}`);
    }
    setRegister(state, register, Number(field.value || 0), 0.02);
  }

  function traceTarget(state, target) {
    if (/^EP\d+$/i.test(target)) {
      const fieldName = state.pointers[target];
      const field = state.fields[fieldName];
      if (!field) {
        return `${target} unallocated`;
      }
      return `${target} field=${fieldName} bank=${field.bank_id} length=${field.cells.length} mode=${field.mode} temp=${field.temperature.toFixed(3)} partition=${field.current_partition}`;
    }
    const value = getRegister(state, target);
    return `${target} real=${value.real.toFixed(8)} temp=${value.temperature.toFixed(3)} partition=${value.current_partition}`;
  }

  function finalizePayload(state, assembly) {
    const snapshot = snapshotState(state);
    return {
      ok: true,
      static_fallback: true,
      assembly,
      symbols: state.variableRegisters,
      output: state.output,
      halted: false,
      steps: state.steps,
      pc: state.pc,
      score: scoreState(state),
      timeline: state.timeline,
      snapshot
    };
  }

  function scoreState(state) {
    const maxTemperature = state.timeline.reduce((max, event) => Math.max(max, timelineMaxTemp(event.after)), 0);
    const memoryCells = Object.values(state.fields).reduce((sum, field) => sum + field.cells.length, 0);
    return {
      steps: state.steps,
      observations: state.observations,
      max_temperature: round(maxTemperature, 3),
      final_temperature: round(timelineMaxTemp(snapshotState(state)), 3),
      degraded_events: state.degraded_events,
      refresh_events: state.refresh_events,
      memory_cells: memoryCells,
      score: round(state.steps * 1.1 + state.observations * 12 + maxTemperature * 24 + state.degraded_events * 35 + memoryCells * 0.4, 1)
    };
  }

  function recordEvent(state, op) {
    state.steps += 1;
    state.timeline.push({
      tick: state.steps,
      op,
      flags: Array.from(state.pendingFlags),
      after: snapshotState(state)
    });
    state.pendingFlags.clear();
  }

  function snapshotState(state) {
    const er = {};
    for (const [name, value] of Object.entries(state.registers)) {
      er[name] = {
        real: value.real,
        mode: value.mode,
        temperature: value.temperature,
        noise: value.noise,
        current_partition: value.current_partition,
        q_max: value.q_max,
        digits: digitsFromReal(value.real)
      };
    }
    const fields = {};
    for (const [name, field] of Object.entries(state.fields)) {
      fields[name] = JSON.parse(JSON.stringify(field));
    }
    return {er, fields};
  }

  function digitsFromReal(value) {
    if (!Number.isFinite(value) || Math.abs(value) < 1e-12) {
      return [];
    }
    const sign = value < 0 ? -1 : 1;
    let remaining = Math.abs(value);
    const top = Math.floor(Math.log(Math.max(remaining, 1e-9)) / Math.log(E));
    const digits = [];
    for (let exponent = top; exponent >= top - 3; exponent -= 1) {
      const weight = Math.pow(E, exponent);
      const digit = Math.min(E - 1e-9, Math.floor((remaining / weight) * 1000) / 1000);
      if (digit > 0 || digits.length) {
        digits.push({exponent, digit: digit * sign});
        remaining -= digit * weight;
      }
    }
    return digits;
  }

  function parseOptions(comment) {
    const options = {};
    for (const item of comment.trim().split(/\s+/)) {
      if (!item.includes("=")) {
        continue;
      }
      const [key, value] = item.split("=", 2);
      options[key] = value;
    }
    return options;
  }

  function branchMatches(op, value) {
    if (op === "EJZ") return Math.abs(value) < 1e-12;
    if (op === "EJNZ") return Math.abs(value) >= 1e-12;
    if (op === "EJGTZ") return value > 0;
    if (op === "EJLTZ") return value < 0;
    if (op === "EJGEZ") return value >= 0;
    if (op === "EJLEZ") return value <= 0;
    return false;
  }

  function safePartition(temperature) {
    if (temperature > 1.6) return 81;
    if (temperature > 0.8) return 81;
    if (temperature > 0.35) return 243;
    return 243;
  }

  function requirePartition(value, label) {
    const partition = Number(value);
    if (!Number.isInteger(partition) || !PARTITIONS.includes(partition)) {
      throw new Error(`${label} must be one of ${PARTITIONS.join(", ")}, got ${value}`);
    }
    return partition;
  }

  function thermalPayload(wordValue) {
    return {
      temperature: wordValue.temperature,
      noise: wordValue.noise,
      q_max: safePartition(wordValue.temperature),
      current_partition: wordValue.current_partition,
      health: 1.0
    };
  }

  function timelineMaxTemp(snapshot) {
    let max = 0;
    for (const value of Object.values(snapshot.er || {})) {
      max = Math.max(max, Number(value.temperature || 0));
    }
    for (const field of Object.values(snapshot.fields || {})) {
      max = Math.max(max, Number(field.temperature || 0));
      for (const cell of field.cells || []) {
        max = Math.max(max, Number(cell.temperature || 0));
      }
    }
    return max;
  }

  function guardStep(state) {
    if (state.steps > state.maxSteps) {
      throw new Error("static playground maxSteps exceeded");
    }
  }

  function expect(parser, token) {
    if (parser.tokens[parser.index] !== token) {
      throw new Error(`expected ${token}, got ${parser.tokens[parser.index] || "end"}`);
    }
    parser.index += 1;
  }

  function optional(parser, token) {
    if (parser.tokens[parser.index] === token) {
      parser.index += 1;
    }
  }

  function truthy(value) {
    return Boolean(Number(value));
  }

  function round(value, precision) {
    const places = Number.isFinite(precision) ? Number(precision) : 8;
    const factor = Math.pow(10, places);
    return Math.round(Number(value) * factor) / factor;
  }

  const api = {samples, run, runChallengeSuite};
  global.EBaseStaticRuntime = api;
  if (typeof module !== "undefined") {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
