# C風簡易コンパイラ

`src/cstyle_compiler.py` は、小さなC風言語を `EPUEmulator` 用のEPUアセンブリへ
変換します。目的は、EPU命令を人間が直接書かなくても、変数、式、分岐、ループを
含む小さなプログラムを動かせるようにすることです。

## 対応する構文

```c
let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

print(acc);
```

宣言キーワードは `let`, `float`, `double`, `e` を同じ意味で扱います。
式は数値リテラル、変数、括弧、単項マイナス、`+`, `-`, `*` に対応します。
条件式は `>`, `<`, `>=`, `<=`, `==`, `!=` を使えます。
行末までの `//` コメントと、UTF-8ファイル先頭のBOM (`U+FEFF`) も受理します。

宣言の初期値が式から生成された一時レジスタにある場合、そのレジスタを変数へ
昇格します。このため不要な `EMOV` と発熱を避け、16本のEレジスタすべてを
変数として利用できます。17本目の同時生存変数は明示的なコンパイルエラーです。

`print(expr);` と `observe(expr);` は、実行時に観測値を `OUT0`, `OUT1` ...
へ順番に出力します。内部的には高級言語用の疑似命令 `EPRINT` を発行し、
`EPUEmulator` が実行順の出力番号へ変換します。低レベルの既存命令
`EOBS name, ERn ; precision=n` は従来どおり利用できます。

## エミュレーター拡張

`src/emulator.py` は既存の `EPU` の上に、次を追加します。

- ラベル `label:`
- 無条件分岐 `EJMP label`
- 条件分岐 `EJZ`, `EJNZ`, `EJGTZ`, `EJLTZ`, `EJGEZ`, `EJLEZ`
- 停止命令 `EHALT`
- 実行ステップ上限による無限ループ防止
- C風言語向けの実行順出力 `EPRINT ERn ; precision=n`

低レベル命令はこれまで通り `EPU.step()` に委譲されるため、既存のEレジスタ、
Eメモリ、熱モデル、量子化、スナップショット、イベントログはそのまま使われます。

## 実行例

```powershell
python .\examples\cstyle_demo.py
```

`python` が PATH にない環境では、ローカルのPython実行ファイルを直接指定します。

```powershell
py .\examples\cstyle_demo.py
```

テストは既存テストと合わせて次で実行します。

```powershell
python -m unittest discover -s tests
```

`tests/test_compiler_differential.py` は固定seedで入れ子の分岐・ループを生成し、
コンパイラやEPUアセンブリを使わない独立オラクルと実行結果を比較します。

## 対応外の構文とエラー

このコンパイラはCそのものではありません。関数、配列、文字列、ポインタ、構造体、
`for`, `do`, `switch`, `break`, `continue`, `return`、`/`, `%`, `++`, `--`、
論理演算子には対応しません。暗黙の変数宣言と同名再宣言も許可しません。
未知の文字、未宣言変数、対応外の演算子、終端の欠落、16本を超える同時生存変数は
`CStyleCompileError` としてコンパイル時に拒否します。実行時の無限ループは
`max_steps` により `EXECUTION_LIMIT` で停止します。

括弧・単項演算子・ブロックを処理系の再帰上限まで深くネストした入力は、生の
`RecursionError` を外へ漏らさず、`source nesting is too deep` という
`CStyleCompileError` に変換します。

主な診断は次のとおりです。

- `unknown variable`: 宣言前の変数を使っています。
- `out of E registers`: 変数または同時に必要な中間値が多すぎます。
- `source nesting is too deep`: 括弧・単項演算子・ブロックのネストが深すぎます。
- `NUMERIC_ERROR`: 非有限値または有限浮動小数点範囲外の値です。
- `EXECUTION_LIMIT`: `while` が終わらないか、設定したstep上限を超えました。

コンパイル結果と実行結果は次で確認できます。

```powershell
ebase compile .\program.cbase
ebase run .\program.cbase --json
```

生成assemblyはEPUの熱、量子化、観測規則に従います。命令ごとの意味は
[EPU Instruction Set](epu_instruction_set.md) を参照してください。
