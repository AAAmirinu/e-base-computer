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
