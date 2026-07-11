# Compiler Starter

This folder gives challenge participants a working external-compiler loop.
It emits the official baseline EPU assembly into a `generated-assembly/`
directory so you can edit or replace one file at a time.

```powershell
python .\examples\compiler_starter\emit_baseline_assembly.py --output .\generated-assembly
python -m epu_cli challenge --assembly-dir .\generated-assembly --json
```

If the `ebase` console script is on `PATH`, the scoring command can also be:

```powershell
ebase challenge --assembly-dir .\generated-assembly --json
```

The generated files are:

```text
factorial.epu
e-ladder.epu
cold-memory.epu
thermal-degrade.epu
branching.epu
```

To participate with an external compiler, make your compiler write the same
filenames into the output directory, then run the same `--assembly-dir` command.
Missing files fall back to the built-in baseline, which is useful while you are
optimizing one challenge at a time.

Safe things to modify:

- The generated `.epu` files.
- Your own external compiler or compiler fork.
- Labels, instruction choices, register allocation, memory use, and refresh strategy.

Do not modify these for official submissions:

- `src/epu_challenge.py` expected outputs or challenge slugs.
- `src/epu_scoring.py` scoring rules.
- Emulator instruction behavior.
- JSON results after scoring.
