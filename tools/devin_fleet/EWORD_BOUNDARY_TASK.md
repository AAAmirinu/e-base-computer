# machine限定編集の実測: EWordの基数直前の精度

## 最新結果

2026-09-19、`--eword-edit` を1回実行した。SWE-2 HighのFree表示・期限を
起動前に確認し、normal、stdin非対話、read/exec/MCP等の拒否を維持。
公開ソース全文をprompt内のデータとして渡し、新規scratchの1ファイルだけをWrite許可。
既存role作業ディレクトリ、stdlib PR候補は変更していない。

- model receipt: `/home/fleet/controller-validation/interactive-auth-uy0f_ax6/receipt.json`
- input SHA256: `faa71b4ddc1fa8e34dc0c03dc9d21cc300c61663574e0f086abff999545857c8`
- candidate SHA256: `9a4b52142e99a7acb226c483a9ce78597e37686b1b635405795ebc80ddb5baaf`
- export SHA256: `75ab8262a510ccd00b7d08224ae29adb1bdf64598cd6109cd693303249a5e261`
- returncode=0、許可したWrite 1回のpath/contentと回収bytesが一致、全agentモデル名一致。
- 差分は `isclose(digit, e, rel_tol=0.0, abs_tol=EPSILON)` への1行変更のみ。
- `network_denied_after=true`, `all_vms_stopped=true`, `cleanup_errors=[]`。
- CLIの生出力・認証情報は回収せず、候補はbytesとして保存。認証済みVMでは未実行。
- `machine_eword_edit`等の保守側モックテスト105件成功（0.075秒）。
  重複JSONキー、別モデル/余分tool、リンク/大きすぎる候補は拒否する。

続けて `--validate-eword-edit` を実行し、receiptと候補・fixtureのdigestを固定、
1行以外の変更がないことを検査して別検証環境へ送った。

- derivation: `/home/fleet/controller-validation/eword-repair-171d1d19/derivation.json`
- snapshot manifest SHA256: `3359b3323af085e7498e541322edfd24f332b8067c50f9129240ef6ff2cd3658`
- dispatch: `/home/fleet/controller-validation/dispatch-6d20171f1f9f41f697132cacbecee4f4/dispatch.json`
- 174テストすべて成功、skip/expected failureなし、9.052秒、Node22.23.2。
- fixtureでは期待失敗指定を廃止し、符号2種×指数3種×境界オフセット3種と
  正規化再適用を追加。ホスト/外側WSLではソースを実行していない。
- 検証コンテナ・全VM・管理サービスの停止を確認。

これは1件の実修正パイプラインの成功であり、完全隔離認定・10並列モデル運転・
停電復帰・継続スケジューラの合格ではない。`production_admitted=false`,
`validation_passed=false`, `full_isolation_accepted=false` を維持。
候補は未commit/未公開。実行予約マーカーを消した再試行はしない。
Fable MCPの最新票は既存の `not_run` で、今回の外部監査合格ではない。

## 確定した入力と範囲

- 公開main: `616ad6b343a58651eba4310123ab267cd74fa2b7`。
- `src/ecomputer.py` の `EWord.normalize` と専用回帰テストだけを対象とする。
- 独立したstdlib PR候補の6ファイルや既存role作業は変更しない。
- 入力 `EWord.from_digits({0: e - 1e-9})` は既にdigit範囲内だが、
  入力との `rel_tol=1e-12, abs_tol=0.0` の一致テストが失敗する。
- 静的原因: `isclose(digit, e, abs_tol=EPSILON)` に既定の相対許容差
  `1e-9` も適用され、絶対EPSILONより広い範囲を繰り上げる。
- 修正案は基数比較の `rel_tol=0.0`。モデルは契約と影響を確認して提案する。
  EPSILON全体、ゼロ切捨て、表現範囲、他レイヤーの仕様変更はしない。

## 再現証拠（修正合格ではない）

`prepare_eword_baseline.py` は固定済み公開main+stdlibスナップショットから
stdlib追加6ファイルを除き、回帰テスト1ファイルだけを加える。
候補コードのimport/実行は行わない。

- snapshot: `/home/fleet/controller-validation/eword-baseline-xxlcbs8p`
- manifest SHA256: `47810d95844b90f04844cf85ad8a42a62f91e4c0157beeb9a19836dc12c4f2ea`
- receipt: `/home/fleet/controller-validation/dispatch-02e9557907e2433e9cefadda67341b44/dispatch.json`
- 116入力ファイル、172テスト、171成功・expected failure 1、skipなし、8.824秒。
- 失敗をexpectedFailureで明記した再現用fixtureであり、修正済みと扱わない。
  失敗したassertionの生トレースはこの集約票には含まれない。
- 既存の固定イメージ、非root、通信なし、認証情報なしの検証コンテナで実行。
- コンテナ停止・検証VM停止・ランチャーによる全11VM停止と管理サービス停止確認。
- `validation_passed=false` / `full_isolation_accepted=false` を維持。

## 当該試行に適用した実行条件

当該試行は既存ファイル書込み/シェル拒否試験とは別の一意な予約を使用した。
この文書を本番登録や、次の試行の予約として流用しない。

1. 認証済みmachineだけを使用し、モデルカタログのSWE-2 High Freeと期限を再確認。
2. 公開ソースを隔離scratchへ渡し、限定ファイルツールだけを許可。
   shell/MCP/ネットワーク取得・認証ファイル読取り・設定書換えを許可しない。
3. 候補は不活性なbytesとして回収し、呼出対象・モデル・入力/出力digestを確認。
4. 認証済みmachine、Windowsホスト、外側WSLでは候補やテストを実行しない。
5. 別スナップショットでexpectedFailureを外し、追加の境界テストと既存全テストを
   認証情報なし検証環境で実行。想定外成功のbaselineを合格として流用しない。
6. 通信拒否復旧・全停止・未解決実行の確認をしてから次の試行へ進む。

10並列・継続運転・PR公開の承認ゲートは、この再現成功では解除しない。
