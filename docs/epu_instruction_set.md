# EPU Instruction Set

EPUアセンブリは、E進ワード、Eメモリ、熱、観測、量子化を扱うための小さな命令セットです。
機械可読な同じ情報は次で取得できます。

```powershell
ebase spec --json
```

全命令は、制御フロー命令を含めて、意味作用、発熱、冷却、期限フラグ、tick、
イベント記録の共通ライフサイクルを通ります。Task Runtimeから実行する場合の
owner/capability境界は [runtime_v0.md](runtime_v0.md) を参照してください。

## レジスタとメモリ

- `ER0..ER15`: Eレジスタ。連続E桁、温度、量子化状態、分割数を持ちます。
- `EP0..EP7`: Eポインタ。`EALLOC` で確保したEフィールドを指します。
- `WORK`: 既定の作業用バンク。
- `COLD`: 冷却が速いバンク。
- `ARCHIVE`: 保存寄りの中温バンク。
- `SACRED`: 低温・低guardのバンク。

1つのEフィールドと1つのバンクは、それぞれ最大 `4096` cellです。`EALLOC` は
この上限を超える要求を、cellやfieldを部分的に追加する前に `MEMORY_ERROR` で
拒否します。

量子化の分割候補は `3, 9, 27, 81, 243` です。温度が高いほど安全な最大分割数
`q_max` が下がり、`degrade=allow` の場合は `DEGRADED` とともに低い分割へ落ちます。
これ以外の分割指定は `BAD_OPERAND` です。計算過程は
[Behavior Model](behavior_model.md) を参照してください。

## 命令グループ

### Eワード

- `ECONST ERdst, real`: 実数をE桁列へ変換してロードします。
- `EDIGITS ERdst, power:digit, ...`: 明示した `e^power` 桁からEワードを作ります。
- `EMOV dst, src`: EレジスタまたはEポインタをコピーします。
- `ENORM ERtarget`: Eキャリーを適用し、連続桁を正規化します。

### 算術

- `EADD ERdst, ERa, ERb`: Eワード加算。
- `ESUB ERdst, ERa, ERb`: Eワード減算。
- `EMUL ERdst, ERa, ERb`: E桁畳み込みによる乗算。
- `ECONV ERdst, ERa, ERb`: 畳み込み名を明示した乗算alias。
- `ESHIFT ERdst, ERsrc, power`: `e^power` だけ桁指数をずらします。
- `ESCALE ERdst, ERsrc, factor`: 実数倍率をかけてEワードへ戻します。

### Eメモリ

- `EALLOC EPdst, bank, length ; mode=EWORD exponent_offset=0`: Eフィールドを確保します。
- `ELOAD ERdst, EPsrc`: EフィールドからEワードを復元します。
- `ESTORE EPdst, ERsrc`: EワードをEフィールドへ格納します。
- `EMODE target, mode`: レジスタまたはフィールドの解釈モードを変えます。

有限floatとして表現できない値、非有限値、不正なE桁や対応指数範囲外のEワードは
`NUMERIC_ERROR` です。構文・オペランド・分割数などの不正は `BAD_OPERAND`、
field/bank容量やstore範囲の違反は `MEMORY_ERROR` として区別されます。

### 量子化と熱

- `EQOS target ; min_partition=243 degrade=allow`: 必要分割数と劣化方針を指定します。
- `EQUANT ERdst, ERsrc, partition`: E値を有限分割へ量子化します。
- `EDEQ ERdst, ERsrc`: 量子化代表値を連続値として読み戻します。
- `ECLAMP ERtarget`: 現在の量子化代表値へ固定します。
- `ETHERM name, target`: 温度、noise、`q_max`、分割数を出力します。
- `ETRIT TRdst, ...`: balanced ternary lane列をTRレジスタへロードします。
- `ETCMP TRdst, ERa, ERb`: E値をepsilon付きで比較し `-1/0/+1` を生成します。
- `ETSEL ERdst, TRcond, ERneg, ERzero, ERpos`: trit符号でE値を選択します。
- `ETEMP name`: 読み取り専用TEMP集約診断を出力します。
- `EREFRESH target`: 正規化しつつ冷却・noise更新します。
- `ESCRUB bank`: バンク内のフィールドをまとめてリフレッシュします。

### 観測とトレース

- `EOBS name, ERsrc ; precision=8`: 観測値を指定名で出力します。
- `EPRINT ERsrc ; precision=8`: C風コンパイラ用に次の `OUTn` へ出力します。
- `ETRACE target`: レジスタ/フィールドの説明文字列を `TRACE` に出します。

### スナップショット

- `ESNAP name, target`: レジスタまたはフィールド状態を保存します。
- `ERESTORE target, name`: 保存した状態を復元します。

### 制御フロー

制御フローは `EPUEmulator` が処理する上位命令です。

- `label:`: ラベル定義。
- `EJMP label`: 無条件ジャンプ。
- `EJZ ERsrc, label`: 0ならジャンプ。
- `EJNZ ERsrc, label`: 0でなければジャンプ。
- `EJGTZ ERsrc, label`: 正ならジャンプ。
- `EJLTZ ERsrc, label`: 負ならジャンプ。
- `EJGEZ ERsrc, label`: 0以上ならジャンプ。
- `EJLEZ ERsrc, label`: 0以下ならジャンプ。
- `EHALT`: 実行停止。

## イベントと可視化

各命令の前後状態は `timeline()` に記録され、Playgroundでは温度タイムライン、
E Digit Ladder、E Field Map、Eventsとして表示されます。主なフラグは次の通りです。

- `NORMALIZED`: Eキャリーまたはリフレッシュで正規化された。
- `QUANTIZED`: 有限分割へ量子化された。
- `DEGRADED`: 熱により要求分割より低い安全分割へ落ちた。
- `OBSERVATION_DIRTY`: 観測により外部出力が発生した。
- `THERMAL_WARN`: 温度が警告域に入った。
- `REFRESH_DUE`: リフレッシュ期限を過ぎた。

コンパイラや最適化器を作る場合は、`steps` だけでなく、`max_temperature`,
`degraded_events`, `observations`, `memory_cells`, `refresh_events` も見てください。
