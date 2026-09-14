# Metadata propagation contract v1

EPU の値メタデータ伝播は `src/epu_metadata.py` の
`metadata_contract_payload()` で機械可読に公開されます。schema version は `1` です。
`ebase spec --json` では `metadata_contract` として同じ payload を取得できます。

対象フィールドは `mode`, `temperature`, `noise`, `health`,
`min_partition`, `current_partition`, `allow_degrade`, `guard_band`,
`quantized_state`, `partition`, `last_refresh` です。owner、permissions、bank、offset、
length は field の権限・配置情報であり、値メタデータの copy/restore 対象には含めません。
payload の `runtime_snapshot_surfaces` は runtime JSON で監査可能でなければならない key を
列挙します。field surface は11個の値メタデータに `refresh_deadline` を加え、
`last_refresh` と deadline の双方から freshness/due 判定を再計算できます。

## Two distinct phases

各規則の `fields` は命令の意味効果直後を定義します。その後、全命令に共通する cycle が
次の順で適用されます。

1. semantic effect
2. returned E-target heat
3. thermal exchange and global ambient cooling
4. global temperature aging and returned E-target stress aging
5. due flags
6. tick
7. event

したがって `ETRACE` や `ETHERM` は値メタデータを直接書き換えませんが、実行 cycle
そのものは無料ではなく、対象の heat/aging と全体の冷却は発生します。`ETEMP` は E-value
を対象に取らない mass-weighted aggregate です。観測モードが `non_destructive` の
`EOBS`/`EPRINT` は意味効果として noise/health を保存し、`destructive` のときだけ
versioned aging model の観測係数で更新します。未知の観測モードは output を書く前に
`MODE_ERROR` で停止します。

aging-v1 は全 ER/field に post-cooling temperature exposure を適用し、その上で命令が
返した ER/field target にだけ instruction stress を加えます。contract test は全38命令の
実 dispatch event、`INSTRUCTION_HEAT`、`INSTRUCTION_STRESS` を照合し、cycle_effects の
宣言漏れを検出します。

## Classification of all 38 opcodes

| Class | Opcodes | Contract |
|---|---|---|
| reset | `ECONST`, `EDIGITS`, `ETRIT` | CONST/DIGITS は fresh ER metadata に置換。ETRIT は TR のみを初期化し E metadata は保存。 |
| copy | `EMOV`, `ELOAD`, `ESTORE`, `ETSEL`, `ESNAP`, `ERESTORE` | source/field/selected source/snapshot の明示された全 metadata を copy。field restore は authority と geometry を保存。 |
| aggregate | `EADD`, `ESUB`, `EMUL`, `ECONV`, `ETCMP`, `ETEMP`, `ETRACE`, `ETHERM`, `ESCRUB` | 算術は worst-case reducer、診断は read aggregate、scrub は bank 内 field の refresh aggregate。 |
| derive | `EALLOC`, `ESHIFT`, `ESCALE`, `EMODE`, `EQOS`, `EQUANT`, `EDEQ`, `EOBS`, `EPRINT`, `EREFRESH` | bank default、変換、QoS、量子化、観測、refresh の規則から導出。 |
| preserve | `ENORM`, `ECLAMP`, `EJMP`, `EJZ`, `EJNZ`, `EJGTZ`, `EJLTZ`, `EJGEZ`, `EJLEZ`, `EHALT` | metadata を直接変更しない。branch read の cycle aging は別 phase。 |

分類は主効果を示します。フィールド単位の正確な action は JSON payload を正とします。

## Important reducers and invalidation rules

- 二項算術は temperature/noise/min_partition/guard_band を `max`、health と
  current_partition を `min`、allow_degrade を論理 AND で集約します。結果は EWORD となり、
  quantized_state/partition は無効化します。
- `ESHIFT`/`ESCALE` は wear と QoS を copy しますが値が変わるため quantized state を
  無効化します。
- `EQUANT` は actual partition と quantized state を導出します。`EDEQ` は環境/QoS を
  copy し、mode を CONTINUOUS にして discrete state を消去します。
- `ENORM` は refresh ではないため `last_refresh` を更新しません。
- `EREFRESH`/`ESCRUB` だけが refresh transform として temperature/noise/health、
  current_partition、last_refresh を更新します。
- `ERESTORE` は保存した last_refresh を含む値メタデータを復元します。壊れた snapshot は
  書き戻し前に `RESTORE_ERROR` となり、field cells を部分更新しません。

## Drift gate

`validate_metadata_contract(public_opcodes)` は public ISA と規則集合の差、未知 class、
field 欠落、未知 action を検出して fail closed します。新命令の追加時は instruction spec、
metadata rule、success/failure opcode conformance、metadata behavior test を同時に更新する必要があります。
