# Static ASM parity v1

The static Playground's `runAsm` implements the same 38 public opcodes exposed
by `ebase spec --json`. The executable Python EPU and `epu_spec.INSTRUCTIONS`
are the normative contract; the JavaScript runtime is a deterministic browser
implementation of that contract, not a second specification.

`tests/data/asm38_cross_runtime_corpus.json` is schema version 1. It contains
one successful dispatch case for every public opcode and representative
fail-closed cases for opcode, operand, register, pointer, mode, ternary,
quantization, restore, label, and execution-limit diagnostics.

The parity gate compares:

- the exact 38-opcode set, executed opcode sequence, halt state, step count,
  and program counter;
- named output values and textual trace output exactly;
- TR lanes, modes, partitions, quantized states, pointer/field identity,
  flags, and refresh metadata exactly;
- Python `EPUError` name, code, and complete message exactly;
- register real values with absolute tolerance `1e-9`;
- temperature, noise, health, guard-band, TEMP aggregate, and field-cell
  floating-point values with absolute tolerance `1e-9` and zero relative
  tolerance.

The tolerance only admits host floating-point representation differences. It
does not permit a different discrete state, output rounding, error diagnostic,
or control-flow result.

Run the gate with:

```powershell
python -m unittest tests.test_static_asm38_parity
```

The existing static C-like compiler parity and official challenge smoke remain
separate gates. Their accepted total remains `366.6`.
