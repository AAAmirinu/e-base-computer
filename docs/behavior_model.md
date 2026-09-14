# E-base Computer Behavior Model

この文書は、E-base Computer v0.2で再現する挙動を、実装に対応する技術モデルとして
説明します。物理ハードウェアが実在するという主張や、世界観・物語の設定資料では
ありません。同じ入力とモデル指定から同じ結果を得る、コンパイラ実験用の決定的な
シミュレーション契約です。

より厳密な係数・順序・APIは、[EPU Specification](epu_spec.md)、
[Thermal Models](thermal_models.md)、[Aging Models](aging_models.md)を正本とします。

## 1. 計算値と運用状態

E進ワードは符号と疎なE桁列を持ちます。

```text
value = sign * sum(digit[k] * e^k)
0 <= digit[k] < e
```

各EレジスタとEフィールドは、数値に加えて次の運用状態を持ちます。

- `mode`: 連続値、E-word、三値、量子化状態などの表現モード。
- `temperature`: 現在の温度。
- `guard_band`: 状態を区別するための余裕幅。
- `current_partition` / `min_partition`: 現在と要求最低の分割数。
- `noise`: `aging-v1`で決定論的に成長し、観測へ影響する揺らぎ。
- `health`: `aging-v1`で低下し、refreshで上限付き回復する健全性。
- `last_refresh`: 最後にrefreshしたtick。

同じ実数値でも、温度、分割、noise、healthが違えば、後続の量子化、観測、
実行分析、チャレンジスコアは同じになりません。

## 2. 共通命令ライフサイクル

ネイティブ命令と、分岐、`EPRINT`、`EHALT`を含む制御命令は、全38 opcodeで
同じ1命令ライフサイクルを通ります。

1. 命令固有のsemantic effectを実行する。
2. 戻されたE targetへ命令熱を加える。
3. 選択thermal modelの熱交換を行う。
4. 全active nodeを周囲冷却する。
5. 選択aging modelで温度曝露とtarget-local workを反映する。
6. `THERMAL_WARN` / `REFRESH_DUE`などを更新する。
7. tickを1進め、命令前後の状態をtimelineへ記録する。

主なtarget熱コストは次の無次元量です。表にない命令はtarget熱を持たなくても、
共通冷却、aging、due flag、tick、eventの各段階を通ります。

| 命令 | 加熱量 |
| --- | ---: |
| `ECONST`, `EDIGITS` | 0.02 |
| `EADD`, `ESUB`, `ESCALE` | 0.04 |
| `EMUL`, `ECONV` | 0.08 |
| `ESHIFT`, `EDEQ`, `EOBS`, `EPRINT` | 0.03 |
| `EQUANT` | 0.05 |
| `ETSEL`, `ELOAD`, `ESTORE` | 0.02 |
| `EALLOC`, `ETRACE`, `ETHERM` | 0.01 |

`simple-v0`のEレジスタは各cycleで `0.005` 冷却されます。たとえば既存温度を
引き継ぐ乗算結果は `0.08` 加熱された後に `0.005` 冷却され、概ね `0.075` の
純増になります。

## 3. Thermal model

`CR.thermal_model`、CLI、task runtime、Playground requestからモデルを選びます。

- `simple` / `simple-v0`: v0.1互換の独立node冷却。既定値。
- `coupled` / `coupled-v1`: 同一bank内、次にbank間で熱交換してから周囲冷却する
  opt-inモデル。熱交換だけを見れば熱容量で重み付けした総熱量を保存します。

未知のモデルは `THERMAL_MODEL_ERROR` でfail closedになります。係数はschema v1で
機械可読に公開され、結果JSONにも解決済みmodel idとfingerprintを含めます。

## 4. Eメモリbank

Eフィールドの最低温度、guard、tickごとの冷却速度はbankで異なります。

| Bank | 最低温度 | 基本guard | 冷却/cycle | 特徴 |
| --- | ---: | ---: | ---: | --- |
| `WORK` | 0.25 | 0.0060 | 0.015 | 温かい作業領域 |
| `COLD` | 0.05 | 0.0020 | 0.040 | 高分割を扱いやすい低温領域 |
| `ARCHIVE` | 0.10 | 0.0030 | 0.030 | 保存と冷却の中間 |
| `SACRED` | 0.02 | 0.0015 | 0.050 | 最低温・最小guard |

未知のbank名は `WORK` 等級として作られます。1 fieldと1 bankはいずれも最大4096
cellで、過大なallocationは実行前に拒否します。field ownerとcapabilityはtask
runtimeが検証し、他principalのfieldへ無権限でアクセスできません。

## 5. 温度と安全分割数

有限分割は次の五段階だけです。

```text
3, 9, 27, 81, 243
```

温度 `T` と基本guard `g` から安全分割数を求めます。

```text
effective_guard(T) = g * (1 + max(0, T))
raw_q_max(T) = floor(e / (2 * effective_guard(T)))
bounded_q_max(T) = max(3, raw_q_max(T))
q_max(T) = bounded_q_max以下で最大の {3, 9, 27, 81, 243}
```

`EQOS target ; min_partition=243 degrade=allow` は要求精度と降格方針を設定します。

- `degrade=allow`: 安全な分割へ落として続行し、`DEGRADED`を記録する。
- `degrade=deny`: `THERMAL_PRECISION_ERROR`で停止する。

温度が上がると `effective_guard` が広がり、安全に区別できる `q_max` が減ります。
これは浮動小数点の桁数を直接削るのではなく、利用可能な量子化分割数を段階的に
下げるモデルです。現在の公式 `thermal-degrade` サンプルでは、`ETHERM` 観測時の
温度は約 `1.995`、基本guardは `0.002` で、五段階へ丸めた `q_max` は `81` です。
要求した `243` は `81` へ降格し、結果とtimelineに `DEGRADED` が残ります。

## 6. 量子化

`EQUANT ERdst, ERsrc, q` は値を `e` で折り返した `[0, e)` 上の位置へ写し、
実際に許可された `q_actual` 区画の中央を代表値にします。

```text
x = real(ERsrc) mod e
state = floor((x / e) * q_actual)
representative = ((state + 0.5) / q_actual) * e
```

`EDEQ`は代表値を連続modeへ戻し、`ECLAMP`は現在の代表値へ固定します。高温時は
`q_actual`が小さくなり、元の値との差が大きくなります。

## 7. Aging、観測、refresh

`CR.aging_model`はthermal modelと独立に選びます。

- `simple-v0`: 従来互換。通常cycleでnoise/healthを進化させない既定値。
- `aging-v1`: post-cooling温度、命令work、観測、refreshを接続するseed不要の
  決定論的モデル。

`EOBS`と`EPRINT`は共通の観測transitionを使います。既定の
`observer_mode=non_destructive`は元値を残し、`destructive`は明示指定した場合だけ
対象へ破壊的影響を適用します。観測は `OBSERVATION_DIRTY` を立て、命令熱と
チャレンジスコア上の観測コストも持ちます。

`EREFRESH`は値を正規化し、温度とnoiseを次の式で下げ、`aging-v1`のhealthを
公開上限まで小さく回復させます。

```text
T_refreshed = max(0, 0.45 * T - 0.02)
noise = guard_band * (1 + T_refreshed)
```

この更新後に通常のtick冷却も適用され、現在分割は自動的には上がりません。
冷却後に高い分割へ戻すには、プログラムが改めて `EQOS` または `EQUANT` を実行します。
`auto_refresh=false`が互換既定で、`true`ならcycle内でdue targetを
自動保守します。最後のrefreshから64 tickで `REFRESH_DUE`、温度1.0超で
`THERMAL_WARN`を立てます。

## 8. チャレンジと実行分析

公式scoreは小さいほどよく、次を加算します。

```text
score = steps
      + observations * 12
      + degraded_events * 40
      + max_temperature * 20
      + memory_cells * 0.1
      + refresh_events * 2
```

v0.2では制御命令も共通cycleを通るため、公式baselineは `366.6` です。challenge
JSONは `challenge_schema_version=2`、`emulator_version`、suite別`scoring_model`を
持ちます。公式suiteは `official-score-v1`、数値suiteは `numerical-score-v1` です。
provenanceのないv0.1 submissionは有効なlegacy cohortとして読み取れますが、
v0.2 scoreとは直接順位比較しません。

命令数だけを減らして乗算を密集させると、最大温度や降格回数で不利になる場合が
あります。一方、refreshを増やしすぎてもstep数と保守コストが増えます。コンパイラは
命令配置、冷却bank、量子化時点、観測回数を合わせて最適化します。

`analysis`はscoreと独立したschema v1で、opcode/group/flag、観測、分岐、保守、例外、
model usage、temperature/noise/health hotspotを要約します。これはモデル挙動の説明であり、
独立した物理較正の証拠ではありません。

## 9. Python、server、static Playground

Pythonの `EPU`、`EPUEmulator`、task runtime、CLI、ローカルPlaygroundがauthoritative
runtimeです。static Playgroundも全38 opcodeとC-like compilerの共通corpusを通し、
離散状態・出力・制御flow・diagnosticをPythonと照合します。浮動小数点比較は公開した
absolute tolerance `1e-9`を使います。

static Pagesはインストール不要の体験版で、challenge結果に `demo_only=true` を付け、
公式提出JSONのcopyを無効にします。提出とsession/capability挙動はCLIまたはPython
serverで再現してください。

実装と規定文書:

- E進ワード: [`src/ecomputer.py`](../src/ecomputer.py)
- EPU状態・cycle・model: [`src/epu.py`](../src/epu.py)
- 制御flow: [`src/emulator.py`](../src/emulator.py)
- task runtime: [`src/epu_runtime.py`](../src/epu_runtime.py)
- score: [`src/epu_scoring.py`](../src/epu_scoring.py)
- instruction contract: [EPU Instruction Set](epu_instruction_set.md)
- minimal value model: [E-word Model](e_word_model.md)
- static parity: [Static ASM Parity](static_asm_parity_v1.md)
- conformance status: [Conformance Matrix](conformance_matrix.md)
