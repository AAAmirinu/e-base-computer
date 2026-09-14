(function (global) {
  "use strict";

  const E = Math.E;
  const CHALLENGE_SCHEMA_VERSION = 2;
  const EMULATOR_VERSION = "0.2.0";
  const CHALLENGE_SCORING_MODELS = {
    official: "official-score-v1",
    numerical: "numerical-score-v1"
  };
  const PARTITIONS = [3, 9, 27, 81, 243];
  const E_MODES = new Set(["CONTINUOUS", "EWORD", "TRIT", "PACKED_TRIT", "COEFFICIENT", "OBSERVED"]);
  const PUBLIC_OPS = new Set([
    "ECONST", "EDIGITS", "EMOV", "EADD", "ESUB", "EMUL", "ECONV", "ESHIFT", "ESCALE", "ENORM",
    "EALLOC", "ELOAD", "ESTORE", "EMODE", "ETRIT", "ETCMP", "ETSEL", "ETEMP", "EQOS", "EQUANT",
    "EDEQ", "ECLAMP", "EOBS", "EPRINT", "ETRACE", "ETHERM", "EREFRESH", "ESCRUB", "ESNAP", "ERESTORE",
    "EJMP", "EJZ", "EJNZ", "EJGTZ", "EJLTZ", "EJGEZ", "EJLEZ", "EHALT"
  ]);
  const BANK_META = {
    COLD: {kind: "COLD", cooling_rate: 0.04, base_guard: 0.002, base_temperature: 0.05},
    ARCHIVE: {kind: "ARCHIVE", cooling_rate: 0.03, base_guard: 0.003, base_temperature: 0.1},
    SACRED: {kind: "SACRED", cooling_rate: 0.05, base_guard: 0.0015, base_temperature: 0.02},
    WORK: {kind: "WORK", cooling_rate: 0.015, base_guard: 0.006, base_temperature: 0.25},
  };

  class EPUError extends Error {
    constructor(code, message) {
      super(`${code}: ${message}`);
      this.name = "EPUError";
      this.code = code;
      this.detail = message;
    }
  }

  function fail(code, message) {
    throw new EPUError(code, message);
  }
  const EXPECTED_OUTPUTS = {
    "factorial": {OUT0: 120},
    "e-ladder": {OUT0: 144.40872214},
    "cold-memory": {OUT0: 7.5},
    "thermal-degrade": {OUT0: 1.62761319},
    "branching": {OUT0: 0}
  };
  const OFFICIAL_SLUGS = Object.keys(EXPECTED_OUTPUTS);
  const NUMERICAL_EXPECTED = {
    "numerical-polynomial": -0.9704407594824638,
    "numerical-cancellation": 1.23456789,
    "numerical-recurrence": 0.843256190266822
  };

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
    },
    {
      slug: "numerical-polynomial",
      title: "Numerical: Horner polynomial",
      language: "c",
      description: "Evaluate a mixed-sign polynomial with Horner's method.",
      source: `let x = 1.23456789;
let y = 0.125;

y = y * x - 0.75;
y = y * x + 1.5;
y = y * x - 2.0;
y = y * x + 0.333333333333;

print(y);
`
    },
    {
      slug: "numerical-cancellation",
      title: "Numerical: cancellation",
      language: "c",
      description: "Preserve a small residual across subtraction of large nearby values.",
      source: `let large = 100000000;
let residual = 1.23456789;
let combined = large + residual;
let recovered = combined - large;

print(recovered);
`
    },
    {
      slug: "numerical-recurrence",
      title: "Numerical: logistic recurrence",
      language: "c",
      description: "Track rounding and operation ordering through a sensitive recurrence.",
      source: `let x = 0.31415926;
let rate = 3.9;
let one = 1;
let n = 12;

while (n > 0) {
    x = rate * x * (one - x);
    n = n - 1;
}

print(x);
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

  function runChallengeSuite(suite = "official") {
    const selected = suite === "numerical"
      ? SAMPLES.filter((sample) => Object.prototype.hasOwnProperty.call(NUMERICAL_EXPECTED, sample.slug))
      : SAMPLES.filter((sample) => OFFICIAL_SLUGS.includes(sample.slug));
    const results = selected.map((sample) => {
      const payload = run({
        source: sample.source,
        language: sample.language,
        precision: suite === "numerical" ? 12 : 8,
        maxSteps: 10000
      });
      const expected = suite === "numerical"
        ? {OUT0: NUMERICAL_EXPECTED[sample.slug]}
        : EXPECTED_OUTPUTS[sample.slug];
      const result = {
        slug: sample.slug,
        title: sample.title,
        language: sample.language,
        correct: outputsMatch(payload.output, expected),
        output: payload.output,
        expected,
        assembly_lines: payload.assembly.split(/\r?\n/).filter(Boolean).length,
        steps: payload.steps,
        score: payload.score
      };
      if (suite === "numerical") {
        const expectedValue = NUMERICAL_EXPECTED[sample.slug];
        const actual = Number(payload.output.OUT0);
        const absoluteError = Math.abs(actual - expectedValue);
        const relativeError = absoluteError / Math.max(Math.abs(expectedValue), 1e-15);
        result.correct = relativeError <= 5e-8 || absoluteError <= 5e-8;
        result.absolute_error = round(absoluteError, 15);
        result.relative_error = round(relativeError, 15);
        result.accuracy_digits = round(
          relativeError <= 0 ? 15 : Math.max(0, Math.min(15, -Math.log10(relativeError))),
          3
        );
        result.error_penalty = round(Math.min(1000000, relativeError * 1000000), 6);
        result.numerical_score = round(result.score.score + result.error_penalty, 6);
      }
      return result;
    });
    const total = round(
      results.reduce(
        (sum, result) => sum + Number(suite === "numerical" ? result.numerical_score : result.score.score || 0),
        0
      ),
      suite === "numerical" ? 6 : 1
    );
    return {
      ok: true,
      static_fallback: true,
      demo_only: true,
      challenge_schema_version: CHALLENGE_SCHEMA_VERSION,
      emulator_version: EMULATOR_VERSION,
      suite,
      scoring_model: CHALLENGE_SCORING_MODELS[suite],
      correct: results.every((result) => result.correct),
      total_score: total,
      performance_score: round(
        results.reduce((sum, result) => sum + Number(result.score.score || 0), 0),
        6
      ),
      mean_accuracy_digits: suite === "numerical"
        ? round(results.reduce((sum, result) => sum + result.accuracy_digits, 0) / results.length, 3)
        : undefined,
      results
    };
  }

  function runAsm(source, request) {
    const state = createState(request);
    const program = parseAsm(source);
    while (!state.halted && state.pc < program.instructions.length) {
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
      let line = stripAsmComment(rawLine).trim();
      if (!line || line.startsWith(";")) {
        continue;
      }
      while (line.includes(":")) {
        const separator = line.indexOf(":");
        const label = line.slice(0, separator).trim();
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(label)) break;
        if (Object.prototype.hasOwnProperty.call(labels, label)) {
          fail("BAD_OPERAND", `duplicate label: ${label}`);
        }
        labels[label] = instructions.length;
        line = line.slice(separator + 1).trim();
        if (!line) break;
      }
      if (!line) continue;
      const [body, comment = ""] = line.split(";", 2);
      const match = body.trim().match(/^(\S+)\s*(.*)$/);
      const op = (match ? match[1] : "").toUpperCase();
      const args = (match ? match[2] : "").split(",").map((part) => part.trim()).filter(Boolean);
      instructions.push({op, args, options: parseOptions(comment), source: rawLine});
    }
    return {labels, instructions};
  }

  function stripAsmComment(line) {
    let result = String(line);
    const slash = result.indexOf("//");
    if (slash >= 0) result = result.slice(0, slash);
    const hash = result.indexOf("#");
    if (hash >= 0) result = result.slice(0, hash);
    return result;
  }

  function executeAsmInstruction(state, instruction, labels) {
    const {op, args, options} = instruction;
    if (!PUBLIC_OPS.has(op)) fail("BAD_OPCODE", `unknown opcode: ${op}`);
    switch (op) {
      case "ECONST": {
        expectArgs(op, args, 2);
        const value = Number(args[1]);
        if (!Number.isFinite(value)) fail("BAD_OPERAND", `could not convert string to float: '${args[1]}'`);
        setRegister(state, args[0], value, 0.02, 0);
        break;
      }
      case "EDIGITS": {
        if (args.length < 2) fail("BAD_OPERAND", "EDIGITS requires a destination and digits");
        setRegister(state, args[0], args.slice(1).reduce((sum, item) => {
          if (!item.includes(":")) fail("BAD_OPERAND", `invalid digit pair: ${item}`);
          const [power, digit] = item.split(":", 2).map(Number);
          if (!Number.isInteger(power) || !Number.isFinite(digit)) fail("BAD_OPERAND", `invalid digit pair: ${item}`);
          return sum + digit * Math.pow(E, power);
        }, 0), 0.02, 0);
        break;
      }
      case "EMOV": {
        expectArgs(op, args, 2);
        if (/^ER/i.test(args[0])) {
          state.registers[registerName(args[0])] = cloneWord(getRegister(state, args[1]));
        } else if (/^EP/i.test(args[0])) {
          const destination = pointerName(args[0]);
          state.pointers[destination] = getPointer(state, args[1]).fieldName;
        } else {
          fail("BAD_OPERAND", `invalid EMOV destination: ${args[0]}`);
        }
        break;
      }
      case "EADD":
      case "ESUB":
      case "EMUL":
      case "ECONV": {
        expectArgs(op, args, 3);
        const left = getRegister(state, args[1]);
        const right = getRegister(state, args[2]);
        const value = op === "EADD" ? left.real + right.real : op === "ESUB" ? left.real - right.real : left.real * right.real;
        const destination = registerName(args[0]);
        state.registers[destination] = {
          ...word(value),
          temperature: Math.max(left.temperature, right.temperature),
          min_partition: Math.max(left.min_partition, right.min_partition),
          current_partition: Math.min(left.current_partition, right.current_partition),
          allow_degrade: left.allow_degrade && right.allow_degrade,
          guard_band: Math.max(left.guard_band, right.guard_band),
          noise: Math.max(left.noise, right.noise),
          health: Math.min(left.health, right.health),
          last_refresh: state.tick
        };
        heatRegister(state, destination, ["EMUL", "ECONV"].includes(op) ? 0.08 : 0.04);
        state.pendingFlags.add("NORMALIZED");
        break;
      }
      case "ESHIFT": {
        expectArgs(op, args, 3);
        const power = Number(args[2]);
        if (!Number.isInteger(power)) fail("BAD_OPERAND", `invalid literal for int(): '${args[2]}'`);
        const source = getRegister(state, args[1]);
        const destination = registerName(args[0]);
        state.registers[destination] = {...cloneWord(source), real: source.real * Math.pow(E, power), last_refresh: state.tick};
        heatRegister(state, destination, 0.03);
        break;
      }
      case "ESCALE": {
        expectArgs(op, args, 3);
        const factor = Number(args[2]);
        if (!Number.isFinite(factor)) fail("BAD_OPERAND", `could not convert string to float: '${args[2]}'`);
        const source = getRegister(state, args[1]);
        const destination = registerName(args[0]);
        state.registers[destination] = {...cloneWord(source), real: source.real * factor, last_refresh: state.tick};
        heatRegister(state, destination, 0.04);
        state.pendingFlags.add("NORMALIZED");
        break;
      }
      case "ENORM": {
        expectArgs(op, args, 1);
        registerName(args[0]);
        state.pendingFlags.add("NORMALIZED");
        break;
      }
      case "EMODE": {
        expectArgs(op, args, 2);
        const mode = String(args[1]).toUpperCase();
        if (!E_MODES.has(mode)) fail("MODE_ERROR", `unknown E mode: ${mode}`);
        if (/^ER/i.test(args[0])) getRegister(state, args[0]).mode = mode;
        else getPointer(state, args[0]).field.mode = mode;
        break;
      }
      case "ETRIT": {
        if (args.length < 2) fail("BAD_OPERAND", "ETRIT requires a destination and lanes");
        const destination = trName(args[0]);
        const lanes = args.slice(1).map((item) => {
          if (!/^-?\d+$/.test(item)) fail("BAD_OPERAND", `invalid literal for int(): '${item}'`);
          return Number(item);
        });
        state.tr[destination] = trit(lanes);
        break;
      }
      case "ETCMP": {
        expectArgs(op, args, 3);
        const epsilon = options.epsilon === undefined ? 1e-12 : Number(options.epsilon);
        if (!Number.isFinite(epsilon) || epsilon < 0) fail("BAD_OPERAND", "ETCMP epsilon must be finite and non-negative");
        const difference = real(state, args[1]) - real(state, args[2]);
        state.tr[trName(args[0])] = trit([difference < -epsilon ? -1 : difference > epsilon ? 1 : 0]);
        break;
      }
      case "ETSEL": {
        expectArgs(op, args, 5);
        const destination = registerName(args[0]);
        const condition = state.tr[trName(args[1])].lanes[0];
        const source = getRegister(state, args[condition + 3]);
        state.registers[destination] = cloneWord(source);
        heatRegister(state, destination, 0.02);
        heatRegister(state, args[condition + 3], 0.02);
        break;
      }
      case "ETEMP":
        expectArgs(op, args, 1);
        state.output[args[0]] = temperatureRegister(state);
        break;
      case "EQOS": {
        expectArgs(op, args, 1);
        const requested = Number(options.min_partition || 3);
        if (!PARTITIONS.includes(requested)) {
          fail("BAD_OPERAND", `partition must be one of (3, 9, 27, 81, 243), got ${requested}`);
        }
        if (options.degrade !== undefined && !["allow", "deny"].includes(String(options.degrade).toLowerCase())) fail("BAD_OPERAND", "EQOS degrade must be allow or deny");
        const value = /^ER/i.test(args[0]) ? getRegister(state, args[0]) : getPointer(state, args[0]).field;
        value.min_partition = requested;
        value.allow_degrade = options.degrade === undefined ? value.allow_degrade : String(options.degrade).toLowerCase() !== "deny";
        value.current_partition = allowedPartition(state, requested, value.temperature, value.guard_band, value.allow_degrade);
        break;
      }
      case "EQUANT": {
        expectArgs(op, args, 3);
        const requested = Number(args[2] || 3);
        const src = getRegister(state, args[1]);
        if (!PARTITIONS.includes(requested)) {
          fail("BAD_OPERAND", `partition must be one of (3, 9, 27, 81, 243), got ${requested}`);
        }
        const current = allowedPartition(state, requested, src.temperature, src.guard_band, src.allow_degrade);
        const cellValue = ((src.real % E) + E) % E;
        const discreteState = Math.min(current - 1, Math.floor((cellValue / E) * current));
        const value = ((discreteState + 0.5) / current) * E;
        const destination = registerName(args[0]);
        state.registers[destination] = {...cloneWord(src), real: value, mode: current === 3 ? "TRIT" : "PACKED_TRIT", min_partition: Math.min(requested, current), current_partition: current, quantized_state: discreteState, partition: current, last_refresh: state.tick};
        heatRegister(state, destination, 0.05);
        state.pendingFlags.add("QUANTIZED");
        break;
      }
      case "EDEQ": {
        expectArgs(op, args, 2);
        const src = getRegister(state, args[1]);
        if (src.quantized_state === null || src.partition === null) fail("MODE_ERROR", "EDEQ requires a quantized register");
        const destination = registerName(args[0]);
        state.registers[destination] = {...cloneWord(src), real: ((src.quantized_state + 0.5) / src.partition) * E, mode: "CONTINUOUS", quantized_state: null, partition: null, last_refresh: state.tick};
        heatRegister(state, destination, 0.03);
        break;
      }
      case "ECLAMP": {
        expectArgs(op, args, 1);
        const value = getRegister(state, args[0]);
        if (value.quantized_state === null || value.partition === null) fail("MODE_ERROR", "ECLAMP requires a quantized register");
        value.real = ((value.quantized_state + 0.5) / value.partition) * E;
        state.pendingFlags.add("QUANTIZED");
        break;
      }
      case "EOBS": {
        expectArgs(op, args, 2);
        state.output[args[0]] = round(real(state, args[1]), Number(options.precision || state.precision));
        state.observations += 1;
        heatRegister(state, args[1], 0.03);
        state.pendingFlags.add("OBSERVATION_DIRTY");
        break;
      }
      case "EPRINT": {
        expectArgs(op, args, 1);
        state.output[nextOutputName(state)] = round(real(state, args[0]), Number(options.precision || state.precision));
        state.observations += 1;
        heatRegister(state, args[0], 0.03);
        state.pendingFlags.add("OBSERVATION_DIRTY");
        break;
      }
      case "ETHERM": {
        expectArgs(op, args, 2);
        if (/^ER/i.test(args[1])) {
          const value = getRegister(state, args[1]);
          state.output[args[0]] = thermalPayload(value);
          heatRegister(state, args[1], 0.01);
        } else {
          const {field} = getPointer(state, args[1]);
          state.output[args[0]] = {...thermalPayload(field), refresh_due: state.tick - field.last_refresh >= field.refresh_deadline};
          heatField(field, 0.01);
        }
        break;
      }
      case "EALLOC": {
        expectArgs(op, args, 3);
        const fieldName = allocateField(state, args[0], args[1], Number(args[2]), options.mode || "EWORD", Number(options.exponent_offset || 0));
        heatField(state.fields[fieldName], 0.01);
        break;
      }
      case "ESTORE": {
        expectArgs(op, args, 2);
        storeField(state, args[0], getRegister(state, args[1]));
        heatField(getPointer(state, args[0]).field, 0.02);
        break;
      }
      case "ELOAD": {
        expectArgs(op, args, 2);
        loadField(state, args[0], args[1]);
        heatRegister(state, args[0], 0.02);
        break;
      }
      case "ETRACE": {
        expectArgs(op, args, 1);
        state.output.TRACE = state.output.TRACE || [];
        state.output.TRACE.push(traceTarget(state, args[0]));
        if (/^ER/i.test(args[0])) heatRegister(state, args[0], 0.01);
        else heatField(getPointer(state, args[0]).field, 0.01);
        break;
      }
      case "EREFRESH": {
        expectArgs(op, args, 1);
        if (/^ER/i.test(args[0])) refreshWord(state, getRegister(state, args[0]));
        else refreshField(state, getPointer(state, args[0]).field);
        state.refresh_events += 1;
        state.pendingFlags.add("NORMALIZED");
        break;
      }
      case "ESCRUB": {
        expectArgs(op, args, 1);
        const bank = String(args[0]).toUpperCase();
        for (const field of Object.values(state.fields)) if (field.bank_id === bank) refreshField(state, field);
        state.pendingFlags.add("NORMALIZED");
        break;
      }
      case "ESNAP": {
        expectArgs(op, args, 2);
        if (/^ER/i.test(args[1])) state.snapshots[args[0]] = {kind: "register", value: cloneWord(getRegister(state, args[1]))};
        else state.snapshots[args[0]] = {kind: "field", field: deepClone(getPointer(state, args[1]).field)};
        break;
      }
      case "ERESTORE": {
        expectArgs(op, args, 2);
        const snapshot = state.snapshots[args[1]];
        if (!snapshot) fail("RESTORE_ERROR", `unknown snapshot: ${args[1]}`);
        if (/^ER/i.test(args[0]) && snapshot.kind === "register") state.registers[registerName(args[0])] = cloneWord(snapshot.value);
        else if (/^EP/i.test(args[0]) && snapshot.kind === "field") {
          const field = getPointer(state, args[0]).field;
          if (field.length !== snapshot.field.length) fail("RESTORE_ERROR", "snapshot length does not match target field");
          const restored = deepClone(snapshot.field);
          restored.bank_id = field.bank_id;
          restored.offset = field.offset;
          state.fields[state.pointers[pointerName(args[0])]] = restored;
        } else fail("RESTORE_ERROR", `cannot restore ${snapshot.kind} snapshot into ${args[0]}`);
        break;
      }
      case "EJMP":
        expectArgs(op, args, 1);
        state.pc = labelPc(args[0], labels);
        recordEvent(state, op);
        return true;
      case "EJZ":
      case "EJNZ":
      case "EJGTZ":
      case "EJLTZ":
      case "EJGEZ":
      case "EJLEZ":
        expectArgs(op, args, 2);
        if (branchMatches(op, real(state, args[0]))) {
          state.pc = labelPc(args[1], labels);
          recordEvent(state, op);
          return true;
        }
        break;
      case "EHALT":
        expectArgs(op, args, 0);
        state.halted = true;
        break;
    }
    recordEvent(state, op);
    return false;
  }

  function runC(source, request) {
    const compiled = compileC(source, request.precision === undefined ? 8 : Number(request.precision));
    const payload = runAsm(compiled.assembly, request);
    payload.symbols = {...compiled.symbols};
    return payload;
  }

  class CStyleCompileError extends Error {
    constructor(message) {
      super(message);
      this.name = "CStyleCompileError";
    }
  }

  class StaticCStyleCompiler {
    constructor(precision = 8) {
      this.precision = precision;
      this.tokens = [];
      this.pos = 0;
      this.assembly = [];
      this.symbols = {};
      this.freeRegisters = [];
      this.tempRegisters = new Set();
      this.labelCounter = 0;
    }

    compile(source) {
      this.tokens = tokenizeC(source);
      this.pos = 0;
      this.assembly = [];
      this.symbols = {};
      this.freeRegisters = Array.from({length: 16}, (_unused, index) => `ER${15 - index}`);
      this.tempRegisters = new Set();
      this.labelCounter = 0;

      while (!this.atEnd()) {
        this.statement();
      }
      return {
        source,
        assembly: `${this.assembly.join("\n")}\n`,
        symbols: {...this.symbols},
      };
    }

    statement() {
      if (this.matchValue("let") || this.matchValue("float") || this.matchValue("double") || this.matchValue("e")) {
        this.declaration();
        return;
      }
      if (this.matchValue("print") || this.matchValue("observe")) {
        this.printStatement();
        return;
      }
      if (this.matchValue("while")) {
        this.whileStatement();
        return;
      }
      if (this.matchValue("if")) {
        this.ifStatement();
        return;
      }
      if (this.peekKind() === "ID") {
        this.assignment();
        return;
      }
      throw this.error(`expected statement, got ${pythonRepr(this.peekValue())}`);
    }

    declaration() {
      const name = this.consume("ID", "expected variable name").value;
      if (Object.prototype.hasOwnProperty.call(this.symbols, name)) {
        throw this.error(`variable already declared: ${name}`);
      }
      this.consumeValue("=");
      const [valueReg, valueTemp] = this.expression();
      if (valueTemp) {
        this.tempRegisters.delete(valueReg);
        this.symbols[name] = valueReg;
      } else {
        const target = this.reserveVariable(name);
        this.emit(`EMOV ${target}, ${valueReg}`);
      }
      this.consumeValue(";");
    }

    assignment() {
      const name = this.consume("ID", "expected assignment target").value;
      if (!Object.prototype.hasOwnProperty.call(this.symbols, name)) {
        throw this.error(`unknown variable: ${name}`);
      }
      this.consumeValue("=");
      const [valueReg, valueTemp] = this.expression();
      this.emit(`EMOV ${this.symbols[name]}, ${valueReg}`);
      this.freeTemp(valueReg, valueTemp);
      this.consumeValue(";");
    }

    printStatement() {
      this.consumeValue("(");
      const [valueReg, valueTemp] = this.expression();
      this.consumeValue(")");
      this.consumeValue(";");
      this.emit(`EPRINT ${valueReg} ; precision=${this.precision}`);
      this.freeTemp(valueReg, valueTemp);
    }

    whileStatement() {
      const startLabel = this.newLabel("while_start");
      const bodyLabel = this.newLabel("while_body");
      const endLabel = this.newLabel("while_end");
      this.emit(`${startLabel}:`);
      const [branchOp, condReg, condTemp] = this.condition();
      this.emit(`${branchOp} ${condReg}, ${bodyLabel}`);
      this.emit(`EJMP ${endLabel}`);
      this.freeTemp(condReg, condTemp);
      this.emit(`${bodyLabel}:`);
      this.block();
      this.emit(`EJMP ${startLabel}`);
      this.emit(`${endLabel}:`);
    }

    ifStatement() {
      const thenLabel = this.newLabel("if_then");
      const elseLabel = this.newLabel("if_else");
      const endLabel = this.newLabel("if_end");
      const [branchOp, condReg, condTemp] = this.condition();
      this.emit(`${branchOp} ${condReg}, ${thenLabel}`);
      this.emit(`EJMP ${elseLabel}`);
      this.freeTemp(condReg, condTemp);
      this.emit(`${thenLabel}:`);
      this.block();
      this.emit(`EJMP ${endLabel}`);
      this.emit(`${elseLabel}:`);
      if (this.matchValue("else")) {
        this.block();
      }
      this.emit(`${endLabel}:`);
    }

    block() {
      this.consumeValue("{");
      while (!this.checkValue("}") && !this.atEnd()) {
        this.statement();
      }
      this.consumeValue("}");
    }

    condition() {
      this.consumeValue("(");
      const [leftReg, leftTemp] = this.expression();
      if ([">", "<", ">=", "<=", "==", "!="].includes(this.peekValue())) {
        const operator = this.advance().value;
        const [rightReg, rightTemp] = this.expression();
        const condReg = this.allocTemp();
        this.emit(`ESUB ${condReg}, ${leftReg}, ${rightReg}`);
        this.emit(`ENORM ${condReg}`);
        this.freeTemp(leftReg, leftTemp);
        this.freeTemp(rightReg, rightTemp);
        this.consumeValue(")");
        return [branchForComparison(operator), condReg, true];
      }
      this.consumeValue(")");
      return ["EJNZ", leftReg, leftTemp];
    }

    expression() {
      return this.addition();
    }

    addition() {
      let [leftReg, leftTemp] = this.multiplication();
      while (["+", "-"].includes(this.peekValue())) {
        const operator = this.advance().value;
        const [rightReg, rightTemp] = this.multiplication();
        const target = this.allocTemp();
        this.emit(`${operator === "+" ? "EADD" : "ESUB"} ${target}, ${leftReg}, ${rightReg}`);
        this.emit(`ENORM ${target}`);
        this.freeTemp(leftReg, leftTemp);
        this.freeTemp(rightReg, rightTemp);
        leftReg = target;
        leftTemp = true;
      }
      return [leftReg, leftTemp];
    }

    multiplication() {
      let [leftReg, leftTemp] = this.unary();
      while (this.peekValue() === "*") {
        this.advance();
        const [rightReg, rightTemp] = this.unary();
        const target = this.allocTemp();
        this.emit(`EMUL ${target}, ${leftReg}, ${rightReg}`);
        this.emit(`ENORM ${target}`);
        this.freeTemp(leftReg, leftTemp);
        this.freeTemp(rightReg, rightTemp);
        leftReg = target;
        leftTemp = true;
      }
      if (this.peekValue() === "/") {
        throw this.error("division is not supported by the current EPU instruction set");
      }
      return [leftReg, leftTemp];
    }

    unary() {
      if (this.matchValue("-")) {
        const [valueReg, valueTemp] = this.unary();
        const zeroReg = this.allocTemp();
        const target = this.allocTemp();
        this.emit(`ECONST ${zeroReg}, 0`);
        this.emit(`ESUB ${target}, ${zeroReg}, ${valueReg}`);
        this.emit(`ENORM ${target}`);
        this.freeTemp(zeroReg, true);
        this.freeTemp(valueReg, valueTemp);
        return [target, true];
      }
      return this.primary();
    }

    primary() {
      if (this.matchValue("(")) {
        const result = this.expression();
        this.consumeValue(")");
        return result;
      }
      if (this.peekKind() === "NUMBER") {
        const number = this.advance().value;
        const register = this.allocTemp();
        this.emit(`ECONST ${register}, ${number}`);
        return [register, true];
      }
      if (this.peekKind() === "ID") {
        const name = this.advance().value;
        if (!Object.prototype.hasOwnProperty.call(this.symbols, name)) {
          throw this.error(`unknown variable: ${name}`);
        }
        return [this.symbols[name], false];
      }
      throw this.error(`expected expression, got ${pythonRepr(this.peekValue())}`);
    }

    reserveVariable(name) {
      if (!this.freeRegisters.length) {
        throw this.error("out of E registers");
      }
      const register = this.freeRegisters.pop();
      this.symbols[name] = register;
      return register;
    }

    allocTemp() {
      if (!this.freeRegisters.length) {
        throw this.error("out of E registers");
      }
      const register = this.freeRegisters.pop();
      this.tempRegisters.add(register);
      return register;
    }

    freeTemp(register, isTemp) {
      if (!isTemp || !this.tempRegisters.has(register)) {
        return;
      }
      this.tempRegisters.delete(register);
      this.freeRegisters.push(register);
    }

    newLabel(prefix) {
      const label = `_${prefix}_${this.labelCounter}`;
      this.labelCounter += 1;
      return label;
    }

    emit(line) {
      this.assembly.push(line);
    }

    consume(kind, message) {
      if (this.peekKind() !== kind) {
        throw this.error(message);
      }
      return this.advance();
    }

    consumeValue(value) {
      if (!this.matchValue(value)) {
        throw this.error(`expected ${pythonRepr(value)}, got ${pythonRepr(this.peekValue())}`);
      }
    }

    matchValue(value) {
      if (!this.checkValue(value)) {
        return false;
      }
      this.advance();
      return true;
    }

    checkValue(value) {
      return !this.atEnd() && this.peekValue() === value;
    }

    peekKind() {
      return this.atEnd() ? "EOF" : this.tokens[this.pos].kind;
    }

    peekValue() {
      return this.atEnd() ? "" : this.tokens[this.pos].value;
    }

    advance() {
      const token = this.tokens[this.pos];
      this.pos += 1;
      return token;
    }

    atEnd() {
      return this.pos >= this.tokens.length;
    }

    error(message) {
      return new CStyleCompileError(`${message} near token ${this.pos}`);
    }
  }

  function compileC(source, precision = 8) {
    return new StaticCStyleCompiler(precision).compile(source);
  }

  function tokenizeC(source) {
    const cleaned = source.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.split("//", 1)[0]).join("\n");
    const pattern = /(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(==|!=|>=|<=|[+\-*/<>=(){},;])|(\s+)|(.)/y;
    const tokens = [];
    let index = 0;
    while (index < cleaned.length) {
      pattern.lastIndex = index;
      const match = pattern.exec(cleaned);
      if (!match) {
        throw new CStyleCompileError(`unexpected character: ${pythonRepr(cleaned[index])}`);
      }
      index = pattern.lastIndex;
      if (match[1] !== undefined) {
        tokens.push({kind: "NUMBER", value: match[1]});
      } else if (match[2] !== undefined) {
        tokens.push({kind: "ID", value: match[2]});
      } else if (match[3] !== undefined) {
        tokens.push({kind: "OP", value: match[3]});
      } else if (match[5] !== undefined) {
        throw new CStyleCompileError(`unexpected character: ${pythonRepr(match[5])}`);
      }
    }
    return tokens;
  }

  function branchForComparison(operator) {
    const mapping = {
      ">": "EJGTZ",
      "<": "EJLTZ",
      ">=": "EJGEZ",
      "<=": "EJLEZ",
      "==": "EJZ",
      "!=": "EJNZ",
    };
    if (!Object.prototype.hasOwnProperty.call(mapping, operator)) {
      throw new Error(`BAD_OPERAND: unsupported comparison: ${operator}`);
    }
    return mapping[operator];
  }

  function pythonRepr(value) {
    return `'${String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
  }

  function createState(request) {
    const registers = {};
    const tr = {};
    const pointers = {};
    for (let index = 0; index < 16; index += 1) registers[`ER${index}`] = word(0);
    for (let index = 0; index < 8; index += 1) {
      tr[`TR${index}`] = trit([0]);
      pointers[`EP${index}`] = null;
    }
    return {
      precision: request.precision === undefined ? 8 : Number(request.precision),
      maxSteps: request.maxSteps === undefined ? 10000 : Number(request.maxSteps),
      pc: 0,
      tick: 0,
      halted: false,
      steps: 0,
      observations: 0,
      degraded_events: 0,
      refresh_events: 0,
      output: {},
      timeline: [],
      registers,
      tr,
      fields: {},
      pointers,
      snapshots: {},
      nextFieldId: 0,
      sr: new Set(["OK"]),
      pendingFlags: new Set()
    };
  }

  function setRegister(state, name, value, heat, baseTemperature = null, normalized = true) {
    name = registerName(name);
    state.registers[name] = word(Number(value));
    state.registers[name].last_refresh = state.tick;
    if (baseTemperature !== null) {
      state.registers[name].temperature = Number(baseTemperature);
    }
    heatRegister(state, name, heat);
    if (normalized) {
      state.pendingFlags.add("NORMALIZED");
    }
  }

  function heatRegister(state, name, delta) {
    if (!name || !/^ER\d+$/i.test(name)) {
      return;
    }
    name = registerName(name);
    state.registers[name].temperature = Math.max(0, state.registers[name].temperature + delta);
  }

  function getRegister(state, name) {
    return state.registers[registerName(name)];
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
      current_partition: 3,
      q_max: 243,
      min_partition: 3,
      allow_degrade: true,
      guard_band: 0.002,
      health: 1,
      quantized_state: null,
      partition: null,
      last_refresh: 0
    };
  }

  function cloneWord(value) {
    return {...value};
  }

  function expectArgs(op, args, count) {
    if (args.length !== count) fail("BAD_OPERAND", `${op} expects ${count} operands, got ${args.length}`);
  }

  function registerName(name) {
    const upper = String(name || "").toUpperCase();
    if (!/^ER(?:[0-9]|1[0-5])$/.test(upper)) fail("BAD_OPERAND", `expected E register, got ${upper}`);
    return upper;
  }

  function pointerName(name) {
    const upper = String(name || "").toUpperCase();
    if (!/^EP[0-7]$/.test(upper)) fail("BAD_OPERAND", `expected E pointer register, got ${upper}`);
    return upper;
  }

  function getPointer(state, name) {
    const canonical = pointerName(name);
    const fieldName = state.pointers[canonical];
    if (!fieldName) fail("MEMORY_ERROR", `unallocated pointer register: ${canonical}`);
    return {name: canonical, fieldName, field: state.fields[fieldName]};
  }

  function trName(name) {
    const upper = String(name || "").toUpperCase();
    if (!/^TR[0-7]$/.test(upper)) fail("BAD_OPERAND", `expected T register, got ${upper}`);
    return upper;
  }

  function trit(lanes) {
    if (lanes.length < 1 || lanes.length > 27) fail("BAD_OPERAND", `TR register requires 1..27 lanes, got ${lanes.length}`);
    if (lanes.some((lane) => !Number.isInteger(lane))) fail("BAD_OPERAND", "TR lanes must be integers");
    if (lanes.some((lane) => ![-1, 0, 1].includes(lane))) fail("BAD_OPERAND", "TR lanes must be balanced ternary values -1, 0, or 1");
    return {lanes: lanes.slice(), encoding: "balanced"};
  }

  function allocateField(state, pointer, bank, length, mode, exponentOffset = 0) {
    pointer = pointerName(pointer);
    bank = String(bank).toUpperCase();
    if (!Number.isInteger(length) || length <= 0) fail("MEMORY_ERROR", "EALLOC length must be positive");
    mode = String(mode).toUpperCase();
    if (!E_MODES.has(mode)) fail("MODE_ERROR", `unknown E mode: ${mode}`);
    const fieldName = `F${state.nextFieldId}`;
    state.nextFieldId += 1;
    state.pointers[pointer] = fieldName;
    const meta = BANK_META[bank] || BANK_META.WORK;
    const baseTemperature = meta.base_temperature;
    state.fields[fieldName] = {
      bank_id: bank,
      offset: Object.values(state.fields).filter((field) => field.bank_id === bank).reduce((sum, field) => sum + field.cells.length, 0),
      length,
      owner: "kernel",
      permissions: ["change_mode", "observe_continuous", "observe_discrete", "read", "refresh", "snapshot", "thermal_control", "write"],
      mode,
      exponent_offset: exponentOffset,
      sign: 1,
      temperature: baseTemperature,
      noise: 0,
      health: 1,
      min_partition: 3,
      current_partition: 3,
      allow_degrade: true,
      guard_band: meta.base_guard,
      quantized_state: null,
      partition: null,
      refresh_deadline: 64,
      last_refresh: state.tick,
      value: 0,
      cells: Array.from({length}, (_unused, index) => ({index, value: 0, temperature: baseTemperature, noise: 0, health: 1, last_refresh: state.tick}))
    };
    state.fields[fieldName].current_partition = safePartition(baseTemperature, meta.base_guard);
    return fieldName;
  }

  function storeField(state, pointer, value) {
    const {field} = getPointer(state, pointer);
    const span = Math.pow(E, field.exponent_offset + field.length);
    if (Math.abs(value.real) >= span * E) fail("MEMORY_ERROR", `E-word does not fit field ${state.pointers[pointerName(pointer)]} range`);
    field.value = value.real;
    field.sign = value.real < 0 ? -1 : 1;
    field.mode = value.mode;
    field.temperature = Math.max(field.temperature, value.temperature);
    field.noise = value.noise;
    field.health = value.health;
    field.min_partition = value.min_partition;
    field.current_partition = value.current_partition;
    field.allow_degrade = value.allow_degrade;
    field.guard_band = value.guard_band;
    field.quantized_state = value.quantized_state;
    field.partition = value.partition;
    field.last_refresh = state.tick;
    field.cells = field.cells.map((cell, index) => ({
      ...cell,
      value: index === 0 ? value.real : 0,
      temperature: value.temperature,
      noise: value.noise,
      health: value.health
    }));
  }

  function loadField(state, register, pointer) {
    const {field} = getPointer(state, pointer);
    register = registerName(register);
    state.registers[register] = {
      ...word(Number(field.value || 0)),
      mode: field.mode,
      temperature: field.temperature,
      noise: field.noise,
      health: field.health,
      min_partition: field.min_partition,
      current_partition: field.current_partition,
      allow_degrade: field.allow_degrade,
      guard_band: field.guard_band,
      quantized_state: field.quantized_state,
      partition: field.partition,
      last_refresh: field.last_refresh
    };
  }

  function traceTarget(state, target) {
    if (/^EP\d+$/i.test(target)) {
      const pointer = getPointer(state, target);
      const field = pointer.field;
      return `${pointer.name} field=${pointer.fieldName} bank=${field.bank_id} offset=${field.offset} length=${field.length} mode=${field.mode} temp=${field.temperature.toFixed(3)} partition=${field.current_partition}`;
    }
    const name = registerName(target);
    const value = getRegister(state, name);
    return `${name} mode=${value.mode} value=${value.real.toPrecision(12)} real=${Number(value.real).toPrecision(12)} temp=${value.temperature.toFixed(3)} partition=${value.current_partition}`;
  }

  function finalizePayload(state, assembly) {
    const snapshot = snapshotState(state);
    return {
      ok: true,
      schema_version: 1,
      static_fallback: true,
      assembly,
      symbols: {},
      output: state.output,
      halted: state.halted,
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
      score: round(state.steps + state.observations * 12 + maxTemperature * 20 + state.degraded_events * 40 + memoryCells * 0.1 + state.refresh_events * 2, 6)
    };
  }

  function recordEvent(state, op) {
    coolAll(state);
    const beforeTick = state.tick;
    state.tick += 1;
    state.steps += 1;
    state.sr = new Set(["OK", ...state.pendingFlags]);
    state.timeline.push({
      tick: beforeTick,
      op,
      flags: Array.from(state.sr).sort(),
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
        health: value.health,
        min_partition: value.min_partition,
        current_partition: value.current_partition,
        allow_degrade: value.allow_degrade,
        guard_band: value.guard_band,
        q_max: value.q_max,
        quantized_state: value.quantized_state,
        partition: value.partition,
        last_refresh: value.last_refresh,
        digits: digitsFromReal(value.real)
      };
    }
    const tr = {};
    for (const [name, value] of Object.entries(state.tr)) tr[name] = deepClone(value);
    const ep = {};
    for (const [name, fieldName] of Object.entries(state.pointers)) {
      if (!fieldName) continue;
      const field = state.fields[fieldName];
      ep[name] = {bank_id: field.bank_id, offset: field.offset, length: field.length, field_id: fieldName, exponent_offset: field.exponent_offset, mode_hint: field.mode};
    }
    const fields = {};
    for (const [name, field] of Object.entries(state.fields)) {
      fields[name] = deepClone({...field, q_max: safePartition(field.temperature, field.guard_band), refresh_due: state.tick - field.last_refresh >= field.refresh_deadline});
    }
    return {tick: state.tick, sr: Array.from(state.sr).sort(), er, tr, temp: temperatureRegister(state), ep, fields, output: deepClone(state.output)};
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
    if (op === "EJZ") return Math.abs(value) <= 1e-12;
    if (op === "EJNZ") return Math.abs(value) > 1e-12;
    if (op === "EJGTZ") return value > 1e-12;
    if (op === "EJLTZ") return value < -1e-12;
    if (op === "EJGEZ") return value >= -1e-12;
    if (op === "EJLEZ") return value <= 1e-12;
    return false;
  }

  function safePartition(temperature, guardBand = 0.002) {
    const raw = Math.max(3, Math.floor(E / (2 * guardBand * (1 + Math.max(0, temperature)))));
    let allowed = 3;
    for (const step of PARTITIONS) {
      if (step <= raw) allowed = step;
    }
    return allowed;
  }

  function thermalPayload(wordValue) {
    return {
      temperature: wordValue.temperature,
      noise: wordValue.noise,
      q_max: safePartition(wordValue.temperature, wordValue.guard_band),
      current_partition: wordValue.current_partition,
      health: wordValue.health
    };
  }

  function temperatureRegister(state) {
    const nodes = [];
    for (const [name, value] of Object.entries(state.registers).sort()) {
      nodes.push({name, temperature: value.temperature, mass: 1, health: value.health, noise: value.noise, due: state.tick - value.last_refresh >= 64});
    }
    for (const [name, value] of Object.entries(state.fields).sort()) {
      nodes.push({name, temperature: value.temperature, mass: value.length, health: value.health, noise: value.noise, due: state.tick - value.last_refresh >= value.refresh_deadline});
    }
    const totalMass = nodes.reduce((sum, node) => sum + node.mass, 0);
    const totalLoad = nodes.reduce((sum, node) => sum + node.temperature * node.mass, 0);
    const maxTemperature = Math.max(...nodes.map((node) => node.temperature));
    const hottestTarget = nodes.filter((node) => node.temperature === maxTemperature).map((node) => node.name).sort()[0];
    return {
      schema_version: 1,
      tick: state.tick,
      thermal_model: "simple-v0",
      aging_model: "simple-v0",
      max_temperature: maxTemperature,
      mean_temperature: totalLoad / totalMass,
      total_thermal_load: totalLoad,
      register_max: Math.max(...nodes.filter((node) => node.name.startsWith("ER")).map((node) => node.temperature), 0),
      field_max: Math.max(...nodes.filter((node) => node.name.startsWith("F")).map((node) => node.temperature), 0),
      hottest_target: hottestTarget,
      refresh_due_count: nodes.filter((node) => node.due).length,
      min_health: Math.min(...nodes.map((node) => node.health)),
      max_noise: Math.max(...nodes.map((node) => node.noise)),
    };
  }

  function allowedPartition(state, requested, temperature, guardBand, allowDegrade) {
    if (guardBand <= 0) fail("GUARD_BAND_ERROR", "guard band must be positive");
    const maximum = safePartition(temperature, guardBand);
    if (requested <= maximum) return requested;
    if (!allowDegrade) fail("THERMAL_PRECISION_ERROR", `requested partition ${requested} exceeds safe partition ${maximum}`);
    const degraded = PARTITIONS.filter((step) => step <= maximum).slice(-1)[0];
    state.degraded_events += 1;
    state.pendingFlags.add("DEGRADED");
    return degraded;
  }

  function heatField(field, delta) {
    field.temperature += delta;
    for (const cell of field.cells) cell.temperature += delta;
  }

  function refreshWord(state, value) {
    value.temperature = Math.max(0, value.temperature * 0.45 - 0.02);
    value.noise = Math.max(value.guard_band * (1 + value.temperature), 0);
    value.current_partition = Math.min(value.current_partition, safePartition(value.temperature, value.guard_band));
    value.last_refresh = state.tick;
  }

  function refreshField(state, field) {
    field.temperature = Math.max(0, field.temperature * 0.45 - 0.02);
    field.noise = Math.max(field.guard_band * (1 + field.temperature), 0);
    field.current_partition = Math.min(field.current_partition, safePartition(field.temperature, field.guard_band));
    field.last_refresh = state.tick;
    for (const cell of field.cells) {
      cell.temperature = field.temperature;
      cell.noise = field.noise;
      cell.health = field.health;
      cell.last_refresh = state.tick;
    }
  }

  function labelPc(label, labels) {
    if (!Object.prototype.hasOwnProperty.call(labels, label)) fail("BAD_OPERAND", `unknown label: ${label}`);
    return labels[label];
  }

  function nextOutputName(state) {
    let index = 0;
    while (Object.prototype.hasOwnProperty.call(state.output, `OUT${index}`)) index += 1;
    return `OUT${index}`;
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function outputsMatch(output, expected) {
    return Object.entries(expected).every(([name, expectedValue]) => {
      const actual = output[name];
      return typeof actual === "number" && Math.abs(actual - expectedValue) <= 1e-8;
    });
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
    if (state.steps >= state.maxSteps) {
      fail("EXECUTION_LIMIT", `execution exceeded ${state.maxSteps} steps`);
    }
  }

  function coolAll(state) {
    for (const value of Object.values(state.registers)) {
      value.temperature = Math.max(0, value.temperature - 0.005);
      value.q_max = safePartition(value.temperature, value.guard_band);
    }
    for (const field of Object.values(state.fields)) {
      const meta = BANK_META[field.bank_id] || BANK_META.WORK;
      field.temperature = Math.max(meta.base_temperature, field.temperature - meta.cooling_rate);
      for (const cell of field.cells) cell.temperature = Math.max(meta.base_temperature, cell.temperature - meta.cooling_rate);
    }
  }

  function round(value, precision) {
    const places = Number.isFinite(precision) ? Number(precision) : 8;
    const factor = Math.pow(10, places);
    return Math.round(Number(value) * factor) / factor;
  }

  const api = {samples, run, runChallengeSuite, compileC, CStyleCompileError, EPUError, publicOpcodes: () => Array.from(PUBLIC_OPS).sort()};
  global.EBaseStaticRuntime = api;
  if (typeof module !== "undefined") {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
