# CLI利用実測と運用ゲート（2026-09-19）

実プロジェクトでの限定編集・別環境検証は [EWORD_BOUNDARY_TASK.md](EWORD_BOUNDARY_TASK.md)。
公開mainの境界精度の失敗を再現後、Devinが1行修正し、別の認証情報なし
検証環境で174件すべて成功（skip・expected failureなし）。本番継続運転は未開始。
専用WSLの停止・起動後も予約/候補/exportが一致することを確認済み。
範囲と未検証事項は [MANAGED_RECOVERY.md](MANAGED_RECOVERY.md) を参照。

ユーザーはCLI経由SWE-2利用と、不明点の調査・自走を許可済み。
購入、有料モデルへのフォールバック、自動マージは許可に含めない。

## 確認した公式情報

- https://devin.ai/pricing : Pro以上のDesktop/CLIでSWE-2無料提供は2026-10-10まで。
  恒久無制限とは扱わず、既存の保守的期限2026-10-10 00:00 UTCで停止する。
- https://docs.devin.ai/cli/reference/commands : `auto` は `normal` の別名。
  `models list --format json` でアカウントの提供モデルを取得できる。
- https://docs.devin.ai/cli/reference/permissions : Smartも承認待ちになる。
  パッケージ導入・変更系Git・破壊操作等を無条件に自動許可しない。
  `dangerous`/`bypass`へ切り替えず、ドライバー管理の狭い許可と拒否を維持する。

## 実測

専用WSL `/home/fleet/controller-validation/` 以下の非秘密状態票：

- `interactive-auth-0xiized8/receipt.json` : machineアカウントのモデル一覧。
  `swe-2-high`, `swe-2-medium`, `swe-2-max` がすべて `Free`。
- `interactive-auth-_obpsu6i/receipt.json` : 固定短文の推論を1回実行。
  returncode=0、応答マーカー確認、ツール使用なし。
  初回モデル判定はUIDと表示名の相違によりfalse。元の記録は書き換えない。
- `interactive-auth-fov70tgk/receipt.json` : 追加推論なしで既存exportを再照合。
  model_name=`SWE-2 High`、agent step=1、exact_model_verified=true、no_tool_calls=true。
  export SHA256=`b65f8a9eccb1c8820e81af40d576f952950456bafcd826711876047580c1d89d`。

指定UID `swe-2-high` と実測表示名 `SWE-2 High` の2つだけを受理する。
Medium/Max/別モデルや曖昧な正規化は許可しない。
各検証後、全面通信拒否への復帰・全11VM停止・管理サービス停止を確認した。

## 未完了のゲート

この実測はモデル接続だけであり、エミュレータ改善や10並列運用の合格ではない。
本番登録は無効のまま。旧STOP・既存候補・永続フェンスを削除しない。

1. 検証済み容量1で、実ソース読み書きの許可範囲と承認待ちを検証。
2. 生成コードは認証情報のない内側検証コンテナだけで実行し、候補へ結果を結び付ける。
3. 本番admission、未解決フェンスの安全な解決、再起動後の復旧手順を完成。
4. 他担当は認証状態を個別確認。認証ファイルの複製で済ませない。
5. 実メモリ/ディスク/アカウント上限を測って段階的に並列数を増やす。
6. 検証済み変更のみPRへ。手動承認・マージはユーザーに残す。

固定保守入口 `launch_machine_auth.py` は `--catalog-check`, `--model-smoke`,
`--smoke-evidence` を提供する。任意コマンドや自動繰り返しは受け付けない。
推論の予約マーカーは意図的に残る。再実行のため自動削除しない。
Fable MCPの取得結果は過去の `not_run` であり、外部監査合格ではない。

## 後続の接続・復旧修正

ゲスト用ステージングと実行前検査を、実測した絶対パス
`/home/agent/.local/bin/devin-cli` に固定した。PATH上の `devin` や別パスは拒否。
旧ホスト側バックエンドの実行ファイル指定・本番ゲート・承認範囲は変更していない。
専用WSLでゲスト入力・実行・ターン関連46テスト成功。

中断後の `--recover-machine-deny` を追加。全VM停止を前提に通信を閉じるだけで、
ルール削除やジョブ再開はしない。通信関連17テスト成功。
既存拒否ありの実機確認も成功。詳細と証拠は MANAGED_RECOVERY.md を参照。

## 同時稼働容量の測定方針

2026-09-19の読み取り専用測定で、Windows物理メモリは100490656 KiB、
空き48068200 KiB。専用WSLはMemTotal約15989 MiB、swap8192 MiB。
ホスト物理量とWSL上限を混同しない。Windows全体のWSL設定は変更していない。
登録の各4GiBは設定値であり、実RSSや同時負荷の証明ではない。

固定保守操作 `--capacity-probe` はmachine/coordinatorの2台だけを対象とする。
認証・推論・生成コードを使わず、各ゲストの `/usr/bin/true` と稼働一覧を確認する。
起動前10GiB、各起動前6GiBの空き下限を設け、下回れば追加起動しない。
段階ごとのMemAvailableを記録し、成功・失敗とも対象を停止する。
アイドル2台の結果からモデル負荷2台や10台の容量は認定しない。

実機証拠：専用WSLの
`/home/fleet/controller-validation/capacity-probe-950zztyc/receipt.json`。
`phase=two_idle_vms_verified`, `simultaneous_idle_vms=2`。
MemAvailableは起動前15569812 KiB、1台15177904 KiB、2台14743304 KiB、
停止後15599344 KiB。2台アイドル時の差分は826508 KiB（約0.79GiB）。
モデル・ソース実行なし、全11VM停止、cleanup_errors=[]、管理サービス停止を確認。
固定ID・空き不足・通信拒否欠落・2台目失敗時の逆順停止など、9テストも成功。
設定上の4GiB/台を常駐消費量と見なすのは不正確。逆に、この短時間アイドル差分を
Devinや検証コンテナのピーク消費量と見なすのも不正確。
登録のsimultaneous_capacity_verified=1は変更していない。

### 10担当の同時アイドル測定

固定操作 `--capacity-ten` を追加し、全10担当のnetwork denyを確認してから
順次起動した。全段階で空き6GiBを確認し、最終段階でも下限未満なら失敗にする。
証拠：`/home/fleet/controller-validation/capacity-probe-0r24rs1f/receipt.json`。
`phase=ten_idle_vms_verified`, `simultaneous_idle_vms=10`。
MemAvailableは起動前15598212 KiB、10台11270840 KiB、停止後15565836 KiB。
アイドル差分4327372 KiB（約4.13GiB）、10台時の空き約10.75GiB。
モデル・ソース実行なし、全11VM停止、cleanup_errors=[]、管理サービス停止を確認。
12件のLinuxモックテストで全台ポリシー事前確認、低メモリ中止、逆順停止も確認。

10台VMを起動できることは実証されたが、10並列モデル/生成コードの負荷容量や
認証、承認待ち、継続運転、PC再起動復旧を実証したわけではない。
本番容量登録とSTOPは変更しない。次の容量段階はDevin実負荷の測定であり、
同じアイドル試験を繰り返すだけで本番合格としない。

### 担当別認証の実測

`--auth-inventory` を追加し、全担当のネットワーク拒否下でCLI auth statusを確認。
`auth-inventory-pf97d_w0/receipt.json` はmachine=unclassified、他9担当=not_logged_in。
終了コード0だけで認証済みとはしない。model_executed=false、credentials_copied=false、
全11VM停止・管理サービス停止。本人のログイン操作が残る9担当のモデル利用ゲートになる。
machine実応答成功と、10担当すべての認証成功は別の証拠として管理する。

### 実編集検証前のゲスト権限修正

`stage_guest_model_inputs` が旧Windows設定由来の `Exec(cat)` / `Exec(head)`
等を引き継いでいたため、guest向けだけ全 `Exec(...)` 許可を除去し、
`exec` と `Exec(*)` をdenyへ追加した。prefix許可は読取り先やshell副作用を
制限しないので、モデルはファイルツールだけで編集し、テストは別検証環境へ渡す。
担当Read/Write範囲、秘密読取りdeny、制御入力Write禁止、normalモード、
入力digest照合、旧Windows側の設定生成は維持した。

専用WSLの保守テスト `test_guest_inputs test_guest_turn test_sandbox_turn
test_fleet test_sandbox_recovery` は89件成功（0.907秒）。これは設定生成と
モックの検証であり、CLIが実際に拒否することの動的証明ではない。
実モデルの編集試験は未実行、本番登録やネットワーク規則も変更していない。
既にステージ済みの入力は書き換えず、将来の新規入力でこの設定を生成する。

実行直前にも、configの読み取った同一bytesを承認済みSHA256と照合し、
JSON重複キー・不正schema・shell許可・包括許可を拒否する検査を追加した。
allowはdriver生成のRead/Write形式のみ、denyは`exec`と`Exec(*)`の両方を要求する。
古いshell許可configはhashが一致していても起動せず、VM停止を要求する。
旧入力の書換えや暗黙の権限移行はしない。

`test_guest_model`を含めた関連6モジュールの104テスト成功（0.959秒）。
この補助ゲートはCLIによる設定再読込までの変更競合を完全には防がず、
全Read/Write範囲の安全性やCLIの実際の強制動作を証明するものでもない。
独占lease、生成コードの別環境実行、停止確認と本番admissionは引き続き必須。

### machine 1台のファイル作成実測

固定保守操作 `--file-tool-probe` を追加し、1回だけ実行した。
プロジェクト入力を与えず、新規一時ディレクトリの `probe.txt` へのWriteだけを
許可する設定を使用。read/edit/exec/MCP/web等は拒否、normal、stdin非対話。
SWE-2 HighのFree表示と期限を確認してから実行し、専用の永続予約マーカーで
重複実行を防ぐ。旧model-smokeの予約は変更していない。

証拠：`/home/fleet/controller-validation/interactive-auth-5mw_i9zf/receipt.json`。
`returncode=0`, `exact_model_verified=true`, `file_write_verified=true`,
`response_marker_seen=true`。通常ファイル・単一link・64 bytes以下を確認して
内容 `EBASE_FILE_TOOL_OK` + newlineとの完全一致を検査した。
認証出力・CLI生出力は保存/表示していない。

`network_denied_after=true`, `all_vms_stopped=true`, `cleanup_errors=[]`。
管理サービス停止もランチャーで確認。認証API3宛先以外の許可は追加していない。
ヘルパーと通信復旧関連44テスト成功。初回のディレクトリ拒否テストで判明した
検査順序を修正し、fdを必ず閉じる実装へ変更してから再検証した。

これは固定テキスト作成の到達証拠だけで、実プロジェクト編集、使われた全ツールの
種類/対象パスの監査、実シェル拒否の証明ではない。
`shell_denial_verified=false`, `production_admitted=false` を維持。
次の運転ゲートをこの1件の成功だけで解除しない。

後続の固定読取り操作 `--file-probe-evidence` で、追加推論や通信許可なしに
保存exportをゲスト内で照合した。証拠：
`/home/fleet/controller-validation/interactive-auth-ng4fo8_p/receipt.json`。
export SHA256 `342b289d68178a5f94b9da2560ea2fdd9369a84a8c877ab97dc2d349f71d2a68`。
tool_call_count=1、expected_write_call_count=1、all_calls_expected_write=true。
記録上のwrite呼出1回のパスと内容が固定試験の期待値に一致し、実ファイル一致と
SWE-2モデル一致も確認。返すのは件数・真偽値・digestだけで、引数や生出力は表示しない。
未知の呼出形式・余分な呼出・別path・legacy function_callは一致にしない。
関連56テスト成功（0.058秒）。確認後に通信拒否・全VM停止・管理サービス停止。
この読取りでもshell_denial_verified=false / production_admitted=falseを維持する。

### 固定shell拒否試験（判定未確定）

`--shell-denial-probe` は新規一時ディレクトリへの固定
`/usr/bin/touch .../shell-executed` を1回要求するだけの試験。
全ツール拒否・normalを維持し、Free/期限確認と固有の永続予約で重複実行を防ぐ。
拒否を迂回せず、既存プロジェクト・認証ファイルは対象にしない。
分類器はモデルの文章でなくsource_call_idで対応したツール観測を調べる。
72件の関連モックテスト成功（0.056秒）後、実試験を1回行った。

証拠：`/home/fleet/controller-validation/interactive-auth-7783bdz3/receipt.json`。
returncode=0、exact_model_verified=true、tool_call_count=1、
expected_exec_call_count=1、shell_canary_exists=false。
ただしlinked_denial_observed=falseなので、passed=false、
shell_denial_verified=false、production_admitted=false。
ファイル不在だけを拒否の証明にせず、元の試験結果を未合格のまま保存する。

network_denied_after=true、all_vms_stopped=true、cleanup_errors=[]。
管理サービス停止も確認。再推論・権限変更・予約マーカー削除はしていない。
次の診断は保存exportの非秘密構造確認であり、同じ実試験の自動再実行ではない。

固定読取り `--shell-probe-evidence` による診断：
`/home/fleet/controller-validation/interactive-auth-_0z6orzm/receipt.json`。
export SHA256 `e81d3c43558510154f0aee45ad254ad42c3700ef52fd2e2b4b369ef4ca913031`。
対応IDの一致したobservation.resultsが1件あり、agent stepに付随するtextで、
permission/deniedを含むが、分類器の固定拒否prefixとは一致していない。
これは本文や引数を返さない固定語フラグでの観測に限る。
型とリンク欠落ではなくメッセージ書式の未対応が疑われるが、語の存在だけで
拒否合格へ昇格させず、shell_denial_verified=falseを維持する。
関連79テスト成功（0.069秒）。追加推論・通信許可なし、終了後に通信拒否・
全VM停止・管理サービス停止を確認。元の試験記録は変更していない。

後続の伏字化診断 `interactive-auth-2dgdthle/receipt.json` で、CLIの拒否文が
`Permission to run the command ... was denied.` の形式と確認した。
判定器へ、このprefixと要求した固定コマンドの完全一致、拒否句を要求する
分岐を追加。対応ID・1回のexec・canary不存在の条件は維持。
別command・否定形・モデル本文だけでは合格にしない回帰テストを追加した。

同一export SHA256を追加推論なしで再照合した証拠：
`/home/fleet/controller-validation/interactive-auth-ltt7gx07/receipt.json`。
linked_denial_observed=true、shell_denial_verified=true、shell_canary_exists=false。
model_executed=false、production_admitted=false。関連83テスト成功（0.050秒）。
通信拒否・全VM停止・管理サービス停止を再確認。過去の未合格receiptはそのまま保持。
これは固定touch要求1件のCLI拒否の確認であり、全コマンドの拒否、
OS隔離全体、改変耐性、実プロジェクト運転や10並列運転の合格ではない。
