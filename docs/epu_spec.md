# EPU詳細仕様 v0

## 1. 目的

この文書は、プログラム上で動作する **EPUエミュレーター** を作るための
最初の詳細仕様です。

ここでのEPUは、成熟したE進コンピューターの中核にある
**E Processing Unit** です。通常CPUやOSから命令を受け取り、Eセル列、
E進ワード、連続状態、離散モードを処理します。

v0の目的は、すべてのSF設定を一度に再現することではありません。
まず、次を実装できる程度に仕様を固定します。

- E進ワードの算術。
- Eレジスタ。
- Eメモリ。
- 温度と精度の簡易モデル。
- 離散モードへの量子化。
- Eリフレッシュ。
- 例外と状態フラグ。
- 簡単なアセンブリ風プログラム。

## 2. 設計方針

EPUエミュレーターは、現実の物理を完全に再現するものではありません。
理想素子を仮定した上で、作中世界の技術的な振る舞いを一貫して模擬します。

設計方針:

- 算術はできるだけ決定的にする。
- 温度や劣化は、再現可能な簡易モデルとして扱う。
- Eセルの値はPythonでは浮動小数で表す。
- EPUの状態は人間が観察しやすい構造にする。
- 将来のOS、コンパイラ、ファイルシステムが呼び出せる境界を作る。

## 3. 全体構造

EPUは次の4層で構成されます。

```text
制御面:
  命令デコード、権限確認、例外処理、状態フラグ管理

算術面:
  E進ワード算術、正規化、畳み込み、対数シフト

場管理面:
  Eメモリ、E場、Eポインタ、モード切替、スナップショット

熱管理面:
  温度、ガードバンド、許可分割数、Eリフレッシュ
```

エミュレーター上では、これらを1つの `EPU` クラスとして実装してよいですが、
仕様上は分けて考えます。

## 4. 基本データ型

### 4.1 ECell

Eセルは、EPUの最小物理単位です。

保持する情報:

```text
value:        0 <= value < e の連続値
temperature: そのセルの温度
noise:       現在推定される揺らぎ
health:      0.0から1.0の健全性
last_refresh: 最後にEリフレッシュされた時刻
```

v0では、`temperature`, `noise`, `health` は簡易メタデータです。
算術値そのものは `value` で保持します。

### 4.2 EWord

E進ワードは、既存実装と同じく次の形です。

```text
sign:   +1 または -1
digits: { exponent -> digit }
```

各 `digit` は `[0, e)` に正規化されます。

v0では、EWordは疎な辞書として扱います。
将来、物理Eセル列をより強く模擬する場合、連続したセル配列へ変更できます。

### 4.3 EField

E場は、Eメモリ上に確保された連続状態です。

保持する情報:

```text
field_id
cells
owner
mode
exponent_offset
min_partition
current_partition
guard_band
temperature
refresh_deadline
permissions
```

E場は、単なる配列ではなく、解釈モード、温度、権限、保存状態を持つ資源です。

### 4.4 EPointer

Eポインタは、Eメモリ上の領域を指します。

```text
bank_id
offset
length
exponent_offset
mode_hint
```

普通のポインタと違い、指数オフセットとモードヒントを含みます。
同じセル列でも、スケールや解釈が違えば別の意味になります。

## 5. モード

EPUは、Eセル列を複数のモードで解釈します。

```text
CONTINUOUS
  連続値の列として扱う。

EWORD
  E進ワードとして扱う。

TRIT
  3値論理として扱う。

PACKED_TRIT
  9値、27値、81値など、三値複数桁を1セルに詰める。

COEFFICIENT
  指数基底や物理モデルの係数列として扱う。

OBSERVED
  通常CPUへ渡すために観測済みの値として扱う。
```

`EMODE` 命令でモードを切り替えます。
ただし、温度や権限によって切り替えが拒否されることがあります。

## 6. レジスタ

v0のEPUは、次のレジスタを持ちます。

```text
ER0..ER15
  Eレジスタ。EWordまたはEField参照を保持する。

TR0..TR7
  三値レジスタ。-1, 0, +1 または 0, 1, 2 の短い列を保持する。

EP0..EP7
  Eポインタレジスタ。Eメモリ上の領域を指す。

SR
  状態レジスタ。

CR
  制御レジスタ。

TEMP
  EPU全体の熱状態を表す読み取り専用レジスタ。

TICK
  エミュレーター上の論理時刻。
```

### 6.1 SR 状態フラグ

`SR` は次のフラグを持ちます。

```text
OK
NORMALIZED
QUANTIZED
DEGRADED
REFRESH_DUE
THERMAL_WARN
GUARD_WARN
OBSERVATION_DIRTY
EXCEPTION
```

命令実行後、EPUは `SR` を更新します。

### 6.2 CR 制御フラグ

`CR` は次の設定を持ちます。

```text
auto_normalize
auto_refresh
allow_degrade
observer_mode
thermal_model
exception_policy
```

エミュレーターでは、まず `auto_normalize = true` を既定にします。

## 7. Eメモリ

Eメモリは、Eセルのバンクとして表現します。

```text
bank_id -> ECell[]
```

各バンクは品質等級を持ちます。

```text
WORK
  作業用。高速だが揺らぎやすい。

COLD
  冷却済み。高分割モードに向く。

ARCHIVE
  長期保存用。低速だが参照セルと冗長性が多い。

SACRED
  重要なE場専用。強い保護と高い冷却優先度を持つ。
```

v0の実装では、バンク等級は温度と既定ガードバンドに影響するだけでよいです。

## 8. 命令形式

v0では、人間が書きやすいアセンブリ風の命令形式を採用します。

```text
OPCODE operand0, operand1, operand2 ; option=value
```

例:

```text
ECONST ER0, 12.5
ECONST ER1, 4.25
EADD ER2, ER0, ER1
ENORM ER2
EOBS R0, ER2 ; precision=6
```

エミュレーター内部では、次のような構造へ変換してもよいです。

```text
{
  "op": "EADD",
  "args": ["ER2", "ER0", "ER1"],
  "options": {}
}
```

## 9. 実行サイクル

各命令は、次の順序で実行されます。

```text
1. デコード
2. オペランド解決
3. モード確認
4. 温度とガードバンド確認
5. 命令実行
6. 必要なら正規化
7. 熱状態更新
8. 状態フラグ更新
9. 例外確認
10. TICKを進める
```

これにより、算術命令でも熱や観測の影響を持たせられます。

## 10. 命令セット

### 10.1 データ移動

```text
ECONST dst, number
```

通常の実数をEWordへ変換して `dst` に入れます。

```text
EDIGITS dst, exponent:digit ...
```

指数と桁を直接指定してEWordを作ります。

```text
EMOV dst, src
```

EレジスタまたはEポインタをコピーします。

```text
EALLOC EPn, bank, length ; mode=EWORD
```

Eメモリを確保し、Eポインタレジスタへ入れます。

```text
ELOAD ERn, EPn
ESTORE EPn, ERn
```

EメモリとEレジスタ間で値を移動します。

### 10.2 E進算術

```text
EADD dst, a, b
ESUB dst, a, b
EMUL dst, a, b
ECONV dst, a, b
```

`EADD`, `ESUB`, `EMUL` はEWord算術です。
`ECONV` は畳み込みを明示する命令で、v0では `EMUL` と同じ結果でもよいです。

```text
ESHIFT dst, src, n
```

指数を `n` だけずらします。

```text
ESCALE dst, src, factor
```

通常の実数係数を掛けます。必要なら正規化します。

```text
ENORM target
```

Eキャリーを伝播し、EWordを正規化します。

### 10.3 モードと量子化

```text
EMODE target, mode
```

Eセル列またはEレジスタの解釈モードを変更します。

```text
EQUANT dst, src, q
```

`src` の連続値を `q` 分割の離散状態へ写します。
温度上 `q` が危険な場合、`allow_degrade` が有効なら低い分割数へ降格します。

```text
EDEQ dst, src
```

離散状態をEセル内の代表値へ戻します。

```text
ECLAMP target
```

離散状態が境界に近すぎる場合、安全域の中央へ寄せます。

### 10.4 観測

```text
EOBS dst, src ; precision=n
```

E進値を通常CPU側の数値へ変換します。
観測により `OBSERVATION_DIRTY` が立つことがあります。

```text
ETRACE target
```

Eセル列の値、温度、モード、ガードバンドを診断出力します。
エミュレーター用のデバッグ命令です。

### 10.5 熱と保守

```text
ETHERM dst, target
```

温度、揺らぎ、現在許可される最大分割数を読みます。

```text
EQOS target ; min_partition=27 cooling=high degrade=deny
```

E場またはEレジスタに必要な精度条件を設定します。

```text
EREFRESH target
```

Eリフレッシュを行います。
v0では次を実行します。

```text
温度を少し下げる
noiseを更新する
EWordなら正規化する
分割数が危険なら降格する
last_refreshを更新する
REFRESH_DUEを消す
```

```text
ESCRUB bank
```

Eメモリバンク全体を巡回し、必要なE場に `EREFRESH` を行います。

### 10.6 スナップショット

```text
ESNAP name, target
```

E場またはEレジスタをスナップショットとして保存します。
スナップショットには値だけでなく、温度、モード、精度、正規化状態を含めます。

```text
ERESTORE target, name
```

スナップショットを復元します。
許容誤差を超える場合は `RESTORE_ERROR` を出します。

## 11. 熱モデル v0

v0では、熱モデルを単純にします。

各E場は温度 `T` を持ちます。

```text
命令実行後:
  T += heat_cost(op)

各tick後:
  T -= cooling_rate(bank)
```

温度から安全分割数を求めます。

```text
guard(T) = base_guard * (1 + T)
q_max(T) = floor(e / (2 * guard(T)))
```

実装では、`q_max` を三値階段へ丸めます。

```text
3, 9, 27, 81, 243
```

要求分割数が `q_max` を超える場合:

- `allow_degrade = true` なら降格して `DEGRADED` を立てる。
- `allow_degrade = false` なら `THERMAL_PRECISION_ERROR` を出す。

## 12. 例外

EPU例外は、普通のプログラム例外とE進特有の状態異常に分かれます。

```text
BAD_OPCODE
BAD_OPERAND
MODE_ERROR
PERMISSION_ERROR
THERMAL_PRECISION_ERROR
GUARD_BAND_ERROR
NORMALIZATION_OVERFLOW
OBSERVATION_ERROR
REFRESH_OVERDUE
RESTORE_ERROR
MEMORY_ERROR
```

例外発生時の動作は `CR.exception_policy` で決まります。

```text
HALT
  停止する。

WARN
  SRにEXCEPTIONを立てて続行する。

DEGRADE
  可能なら分割数や精度を落として続行する。
```

## 13. 権限

EPUは、OSから呼ばれることを想定します。
v0エミュレーターでも、簡易権限を持たせます。

権限:

```text
read
write
observe_continuous
observe_discrete
change_mode
refresh
snapshot
thermal_control
```

これにより、後で簡易OSを作るときに、E場ごとの観測権限を模擬できます。

## 14. コンパイラから見たEPU

将来の簡易コンパイラは、次のような抽象操作をEPU命令へ変換します。

```text
let a: EContinuous = 12.5
let b: EContinuous = 4.25
let c = a * b
observe c
```

変換例:

```text
ECONST ER0, 12.5
ECONST ER1, 4.25
EMUL ER2, ER0, ER1
ENORM ER2
EOBS R0, ER2
```

離散モードを含む場合:

```text
let state: EPackedTrit<27> = quantize(signal)
```

変換例:

```text
EQUANT ER1, ER0, 27
EMODE ER1, PACKED_TRIT
```

## 15. エミュレーター実装計画

実装は段階的に進めます。

### v0.1 EPU算術

- `EWord` を再利用する。
- `ER0..ER15` を実装する。
- `ECONST`, `EDIGITS`, `EADD`, `EMUL`, `ESHIFT`, `ENORM`, `EOBS` を実装する。
- アセンブリ風プログラムを実行できるようにする。

### v0.2 Eメモリ

- `ECell`, `EField`, `EPointer` を実装する。
- `EALLOC`, `ELOAD`, `ESTORE` を実装する。
- E場のモードを保持する。

### v0.3 量子化と熱

- `EQUANT`, `EDEQ`, `ECLAMP` を実装する。
- 簡易温度モデルを追加する。
- `ETHERM`, `EQOS` を実装する。

### v0.4 保守と保存

- `EREFRESH`, `ESCRUB` を実装する。
- `ESNAP`, `ERESTORE` を実装する。
- Eリフレッシュ周期と例外を追加する。

### v0.5 簡易OSとコンパイラ

- E場の所有者と権限を管理する簡易OSを作る。
- 小さな高級言語からEPUアセンブリへ変換するコンパイラを作る。

## 16. 最小サンプル

v0.1で動かす最小プログラム:

```text
ECONST ER0, 12.5
ECONST ER1, 4.25
EMUL ER2, ER0, ER1
ENORM ER2
ESHIFT ER3, ER2, 1
EOBS OUT0, ER3 ; precision=8
```

期待される意味:

```text
ER2 = 12.5 * 4.25
ER3 = e * ER2
OUT0 = 通常数値として観測されたER3
```

## 17. 仕様上の割り切り

v0では、次をまだ完全には扱いません。

- 真の連続値の完全保存。
- 物理的な観測破壊の厳密な再現。
- Eセル間の局所干渉。
- 高度な微分積分用の指数基底変換。
- 実OSとのプロセス分離。
- 暗号的な観測ログ。

これらは、EPUエミュレーターが動き始めてから順に追加します。

## 18. 設定としての意味

この仕様により、EPUは単なる「すごいアナログ装置」ではなく、
命令セット、状態、例外、メモリ、熱、権限を持つ計算資源になります。

作中では、通常CPUがEPUへ命令を発行し、OSがE場を管理し、コンパイラが
人間の書いたE進プログラムをEPU命令へ落とします。

一方で、EPUの内部には、調律、観測、リフレッシュ、降格、意味のずれといった
古いE進アナログ文化の痕跡が残ります。

