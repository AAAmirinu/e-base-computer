# E-base Computer Behavior Model

この文書は、E-base Computer エミュレーターで再現される挙動を、実装に対応する
技術モデルとして説明します。物理ハードウェアが実在するという主張や、世界観・物語の
設定資料ではありません。同じ入力から同じ結果を得られる、コンパイラ実験用の決定的な
シミュレーション契約です。

## 1. 計算値と運用状態

E進ワードは、符号と疎なE桁列を持ちます。

```text
value = sign * sum(digit[k] * e^k)
0 <= digit[k] < e
```

通常の数値だけでなく、各レジスタやEフィールドは次の運用状態を持ちます。

- `temperature`: 現在の温度。
- `guard_band`: 状態を区別するために必要な余裕幅。
- `current_partition`: 現在使っている有限分割数。
- `min_partition`: プログラムが要求する最低分割数。
- `noise`: リフレッシュ時に更新される推定揺らぎ。
- `health`: 将来の劣化モデル用の健全性。v0では通常 `1.0` のままです。
- `last_refresh`: 最後にリフレッシュしたtick。

したがって、同じ実数値を持つ二つのE進ワードでも、温度や分割状態が違えば、後続の
量子化やスコアは同じになりません。

## 2. 1命令で起きること

低レベルの `EPU.step()` は、概ね次の順で状態を更新します。

1. 命令をデコードし、E進演算・メモリ操作・量子化・観測を行う。
2. 命令の対象へ `heat_cost(op)` を加える。
3. レジスタとEメモリを1tick分冷却する。
4. `THERMAL_WARN` や `REFRESH_DUE` を更新する。
5. 命令前後の状態を `timeline()` に記録する。

主な熱コストは次のとおりです。値は物理単位ではなく、v0モデル内の無次元量です。

| 命令 | 加熱量 |
| --- | ---: |
| `ECONST`, `EDIGITS` | 0.02 |
| `EADD`, `ESUB` | 0.04 |
| `EMUL`, `ECONV` | 0.08 |
| `ESHIFT` | 0.03 |
| `ESCALE` | 0.04 |
| `EQUANT` | 0.05 |
| `EDEQ` | 0.03 |
| `EOBS` | 0.03 |
| `EALLOC`, `ETRACE`, `ETHERM` | 0.01 |
| `ELOAD`, `ESTORE` | 0.02 |

Eレジスタは低レベル命令ごとに `0.005` 冷却されます。たとえば、既存温度を引き継いだ
乗算結果には `0.08` が加わり、そのtickの終わりに `0.005` が引かれるため、概ね
`0.075` の純増になります。

ラベル、分岐、`EHALT`、コンパイラ用の `EPRINT` は上位の `EPUEmulator` が扱います。
これらもstep数とtimelineには含まれますが、v0では低レベルの熱コスト表を適用しません。
ISAレベルで観測熱を含めて比較したい場合は `EOBS` を使います。

## 3. Eメモリバンク

Eフィールドの最低温度、ガードバンド、tickごとの冷却速度はバンクで異なります。

| バンク | 最低温度 | 基本guard | 冷却/tick | 用途上の特徴 |
| --- | ---: | ---: | ---: | --- |
| `WORK` | 0.25 | 0.0060 | 0.015 | 温かく、細かい分割を維持しにくい作業領域 |
| `COLD` | 0.05 | 0.0020 | 0.040 | 高分割を扱いやすい低温領域 |
| `ARCHIVE` | 0.10 | 0.0030 | 0.030 | 保存と冷却の中間 |
| `SACRED` | 0.02 | 0.0015 | 0.050 | 最も低温でguardが小さい領域 |

未知のバンク名は `WORK` 等級として作られます。v0では1フィールドと1バンクの双方を
最大4096セルに制限しています。

## 4. 温度から安全分割数を求める

分割数は、連続な `[0, e)` を有限状態へ写す細かさです。v0で使える分割は次の五段階だけです。

```text
3, 9, 27, 81, 243
```

温度 `T` と基本ガードバンド `g` から、安全分割数を次のように求めます。

```text
effective_guard(T) = g * (1 + max(0, T))
raw_q_max(T) = floor(e / (2 * effective_guard(T)))
bounded_q_max(T) = max(3, raw_q_max(T))
q_max(T) = bounded_q_max以下で最大の {3, 9, 27, 81, 243}
```

温度が上がると `effective_guard` が広がり、互いに区別できる状態数 `q_max` が減ります。
これが、このエミュレーターにおける「熱による精度低下」です。浮動小数点の桁数を直接
減らすのではなく、安全に使える量子化分割数を段階的に下げます。

`EQOS target ; min_partition=243 degrade=allow` は要求精度と降格方針を設定します。
要求が `q_max` を超えた場合の挙動は次の二つです。

- `degrade=allow`: 安全な分割へ落として続行し、`DEGRADED` を立てる。
- `degrade=deny`: `THERMAL_PRECISION_ERROR` で停止する。

公式 `thermal-degrade` サンプルでは、反復乗算で温度が約 `2.15` まで上がります。
基本guardが `0.002` のレジスタでは生の上限が約 `215` となるため、五段階へ丸めた
`q_max` は `81` です。要求した `243` は `81` へ降格し、結果とtimelineに
`DEGRADED` が残ります。

## 5. 量子化で値がどう変わるか

`EQUANT ERdst, ERsrc, q` は、値を `e` で折り返した `[0, e)` 上の位置へ写し、
実際に許可された分割数 `q_actual` の区画へ入れます。

```text
x = real(ERsrc) mod e
state = floor((x / e) * q_actual)
representative = ((state + 0.5) / q_actual) * e
```

出力レジスタは区画中央の `representative` を保持します。`EDEQ` はこの代表値を連続
モードとして読み戻し、`ECLAMP` は現在の代表値へ固定します。高温時は `q_actual` が
小さくなるため区画が広がり、元の値との差が大きくなります。

## 6. 観測とリフレッシュ

`EOBS` はE進ワードを通常の数値へ丸めて外部出力し、`OBSERVATION_DIRTY` を立てます。
既定の `observer_mode` は `non_destructive` なので、観測だけで元の値を消しません。
ただし低レベル観測には熱コストがあり、チャレンジスコアでも観測回数がコストになります。

`EREFRESH` は値を正規化し、レジスタ温度を次の式で大きく下げます。

```text
T_refreshed = max(0, 0.45 * T - 0.02)
noise = guard_band * (1 + T_refreshed)
```

その後、通常のtick冷却も適用されます。リフレッシュは現在分割を自動的に上げ直しません。
冷却後に高い分割を使うには、プログラムが改めて `EQOS` や `EQUANT` を実行します。
最後のリフレッシュから64tick経過すると `REFRESH_DUE`、温度が `1.0` を超えると
`THERMAL_WARN` が立ちます。

## 7. コンパイラ最適化への影響

公式スコアは小さいほどよく、次を加算します。

```text
score = steps
      + observations * 12
      + degraded_events * 40
      + max_temperature * 20
      + memory_cells * 0.1
      + refresh_events * 2
```

このため、命令数だけを減らして乗算を密集させると、最大温度や降格回数で不利になる場合が
あります。一方、リフレッシュを増やしすぎてもstep数と保守コストが増えます。コンパイラは
命令配置、冷却バンク、量子化の時点、観測回数を一緒に最適化できます。

## 8. 公式実装と静的Playground

Python の `EPU`, `EPUEmulator`, CLI、ローカル Playground が公式チャレンジの
authoritative runtimeです。GitHub Pages の `static fallback` はブラウザだけで遊ぶための
簡略実装で、熱しきい値やスコアが近似です。静的版のJSONは公式提出には使いません。

実装と対応する入口:

- E進ワード: [`src/ecomputer.py`](../src/ecomputer.py)
- EPU状態・熱・量子化: [`src/epu.py`](../src/epu.py)
- 分岐と実行上限: [`src/emulator.py`](../src/emulator.py)
- スコア: [`src/epu_scoring.py`](../src/epu_scoring.py)
- 命令一覧: [EPU Instruction Set](epu_instruction_set.md)
- 最小表現モデル: [E-word Model](e_word_model.md)
