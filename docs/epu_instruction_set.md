# EPU Instruction Set

EPUアセンブリは、E進ワード、Eメモリ、熱、観測、量子化を扱うための小さな命令セットです。
機械可読な同じ情報は次で取得できます。

```powershell
ebase spec --json
```

## レジスタとメモリ

- `ER0..ER15`: Eレジスタ。連続E桁、温度、量子化状態、分割数を持ちます。
- `EP0..EP7`: Eポインタ。`EALLOC` で確保したEフィールドを指します。
- `WORK`: 既定の作業用バンク。
- `COLD`: 冷却が速いバンク。
- `ARCHIVE`: 保存寄りの中温バンク。
- `SACRED`: 低温・低guardのバンク。

量子化に指定できる分割数は `3, 9, 27, 81, 243` のいずれかです。それ以外は
`BAD_OPERAND` になります。温度が高いほど安全な最大分割数
`q_max` が下がり、`degrade=allow` の場合は `DEGRADED` とともに低い分割へ落ちます。
熱と精度低下の計算過程は [Behavior Model](behavior_model.md) を参照してください。

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

- `EALLOC EPdst, bank, length ; mode=EWORD exponent_offset=0`: Eフィールドを確保します。v0エミュレーターでは
  1フィールドは最大4096セル、1バンクは合計最大4096セルです。
- `ELOAD ERdst, EPsrc`: EフィールドからEワードを復元します。
- `ESTORE EPdst, ERsrc`: EワードをEフィールドへ格納します。
- `EMODE target, mode`: レジスタまたはフィールドの解釈モードを変えます。

### 量子化と熱

- `EQOS target ; min_partition=243 degrade=allow`: 必要分割数と劣化方針を指定します。
- `EQUANT ERdst, ERsrc, partition`: E値を有限分割へ量子化します。
- `EDEQ ERdst, ERsrc`: 量子化代表値を連続値として読み戻します。
- `ECLAMP ERtarget`: 現在の量子化代表値へ固定します。
- `ETHERM name, target`: 温度、noise、`q_max`、分割数を出力します。
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
