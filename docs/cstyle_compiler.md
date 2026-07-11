# C-like compiler

`ebase compile` と Playground の C-like モードは、教育用の小さな C 風言語を
EPU アセンブリへ変換します。Python や JavaScript を実行する機能ではありません。

## 使える構文

```c
let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

if (acc >= 120) {
    print(acc);
} else {
    print(0);
}
```

- 宣言: `let`, `float`, `double`, `e`
- 代入: `name = expression;`
- 出力: `print(expression);` または `observe(expression);`
- 制御構文: `if/else`, `while`
- 比較: `>`, `<`, `>=`, `<=`, `==`, `!=`
- 式: 数値、変数、括弧、単項マイナス、`+`, `-`, `*`
- コメント: 行末までの `//`

Windows のエディタが付与する UTF-8 BOM は先頭にあっても受け入れます。

## 生成される EPU プログラム

`print(expr);` と `observe(expr);` は、実行時に観測値を `OUT0`, `OUT1` ... へ
順番に出力します。コンパイラは高級言語用の疑似命令 `EPRINT` を出し、
`EPUEmulator` が実行順の出力番号へ変換します。低レベルの
`EOBS name, ERn ; precision=n` もアセンブリでは引き続き使えます。

`EPUEmulator` は通常の EPU 命令に加え、ラベル、`EJMP`、条件分岐、`EHALT`、
実行ステップ上限を扱います。E レジスタ、E メモリ、熱、量子化、スナップショット、
イベント timeline は低レベル EPU と同じ規則で実行されます。

## 使えない構文

The C-like compiler is intentionally small. The following are **not supported**:

- 関数、配列、文字列、ポインタ、構造体
- `for`, `do`, `switch`, `break`, `continue`, `return`
- `/`, `%`, `++`, `--`, 論理演算子
- 暗黙の変数宣言や同じ名前の再宣言

除算は現在の EPU 命令セットに含まれないため、コンパイルエラーになります。
16 本の E レジスタを超える変数・中間値を必要とするプログラムもエラーになります。

## エラーの読み方

- `unknown variable`: 宣言前の変数を使っています。
- `out of E registers`: 変数または同時に必要な中間値が多すぎます。
- `source nesting is too deep`: 括弧・単項演算子・ブロックのネストを浅くしてください。
- `NUMERIC_ERROR`: 非有限値や Python の有限浮動小数点範囲を超える値を使っています。
- `EXECUTION_LIMIT`: `while` が終わらないか、設定したステップ上限を超えました。

コンパイル結果を確認するには次を使います。

```powershell
ebase compile .\program.cbase
ebase run .\program.cbase --json
```

生成されたアセンブリは EPU の熱、量子化、観測の規則に従って実行されます。命令ごとの
意味は [EPU instruction set](epu_instruction_set.md) を参照してください。
