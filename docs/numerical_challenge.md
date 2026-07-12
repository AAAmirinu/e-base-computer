# Numerical Compiler Challenge

数値計算部門は、EPU向けコード生成の計算精度と決定論的な実行コストを比較します。
現在の実装はPython `float`を最終変換に使うため、任意精度計算ではなくbinary64範囲での
数値安定性競争です。

## 実行

```powershell
ebase challenge --suite numerical --json
ebase challenge --suite numerical --assembly-dir .\generated-assembly --json
```

外部コンパイラは次のファイルを生成します。

- `numerical-polynomial.epu`: 混合符号多項式のHorner評価。
- `numerical-cancellation.epu`: 大きな近接値から小さな差を回収する計算。
- `numerical-recurrence.epu`: 誤差に敏感なlogistic recurrence。

ファイルがない課題には組み込みbaselineを使います。固定入力なので、定数畳み込みや
式の並べ替えもコンパイラ最適化として扱えます。

## 測定値

各課題は12桁で観測し、次をJSONへ記録します。

- `absolute_error`: 参照値との最大絶対誤差。
- `relative_error`: 参照値との最大相対誤差。
- `accuracy_digits`: `-log10(relative_error)` を0から15へ制限した目安。
- `score`: steps、温度、観測、メモリなどの従来performance score。
- `error_penalty`: `min(1,000,000, relative_error * 1,000,000)`。
- `numerical_score`: performance scoreとerror penaltyの合計。

正解条件は絶対誤差または相対誤差が `5e-8` 以下であることです。壁時計時間は実行環境の
影響を受けるため順位には使わず、速度はEPUの `steps` で比較します。

## 順位

数値部門の順位表は、単一の重みだけで精度と速度を混ぜないよう次の順で比較します。

1. 有効で全課題が正解している提出。
2. 最大相対誤差が小さい提出。
3. 合計stepsが少ない提出。
4. `numerical_score` が小さい提出。
5. 生成アセンブリ行数が少ない提出。

`numerical_score` は改善の目安とPlayground表示に使います。精度と速度の一方だけに偏った
最適化も分析できるよう、元の指標はすべてJSONへ残します。

## Playground

Challenge suiteで `Numerical suite` を選ぶと、課題ごとの有効桁、相対誤差、steps、
performance score、numerical scoreを表で比較できます。GitHub Pagesのstatic fallbackは
デモ用です。提出JSONはCLIまたはローカルPythonサーバで生成してください。
