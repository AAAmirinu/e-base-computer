# Devin認証の引継ぎ（machineログイン操作完了）

## CLI statusインターフェース確認（2026-09-20）

固定保守入口 `launch_machine_auth.py --inspect-auth-interface` でmachineのみを
既存ネットワーク拒否のまま起動し、`--version` と `auth status --help` を実行。
CLIは3000.6.2、binary SHA256は
`9926e1e6e0f3071398759efd1414609a8a54762d08a01bb301f4407d1caccf5a`。
status helpに表示されたlong optionは `--help` のみ。JSON出力optionは観測されない。
バイナリ静的文字列に `Not logged in` と `Logged in as` を確認したが、後者は
login用文字列の可能性もあり、status成功形式やサーバー認証の証明には使わない。

初回処理はsbx起動通知がJSONに先行したため解析失敗。元receiptを変更せず、
保存出力を別途再解析した。CLI/VMは再実行していない。
証拠 `/home/fleet/controller-validation/auth-interface-v10meoxq/interface-analysis.json`、
元出力SHA256 `49e58a44ffed33c93319510307ba0f8bdec113accb5484a583ef9b51827a6e1b`。
launcherが全11VM停止を確認してservice停止。別systemctl読取りでも
inactive/dead/MainPID=0。認証情報・認証ログの直接読取り、通信変更、モデル実行なし。
CLI内部初期化のcredential読取り有無までは検証していない。
起動通知の固定1行のみを許容するparserへ修正し、実行前にも状態票を保存する。
parser8件を含むpure/mock回帰97件が専用WSLで成功（0.174秒）。
parserは診断結果の読取り専用であり、本番認証admissionには接続していない。

公式 [Commands](https://docs.devin.ai/cli/reference/commands) はauth statusを掲載するが、
成功出力schema/終了コード契約は記載しない。
[Troubleshooting](https://docs.devin.ai/cli/troubleshooting) はtraceログの秘密情報混入を
注意喚起しているため、この調査ではtrace/HTTPヘッダー取得を使わない。
次に必要なのは、値を返さないstatus形状観測と、ローカル認証表示・実サーバー利用を
区別した本番admission。今回の結果もauthentication_verified=false。

## 最新状態

担当別の入口を実装済み。本人が操作する非記録端末でのみ
`launch_machine_auth.py --login-role coordinator` のように起動できる。
対応は登録済み10担当の固定名・UUIDのみ。任意UUIDやコマンドは指定できない。
実際に9担当のログイン端末を開く前に、ユーザーがブラウザ認証に対応できるか確認中。
通信許可・ログインはまだ行っていない。トークンは専用端末だけへ直接入力する。

中断後の閉鎖専用入口 `--recover-role coordinator` も追加した。
実機証拠：`/home/fleet/controller-validation/network-recovery-_472fd_j/receipt.json`。
coordinator UUID一致、既存拒否を変更せず確認、全11VM停止、管理サービス停止。
同じ固定担当指定を他の9担当にも使えるが、本人認証を自動化するものではない。

2026-09-19、全10担当のCLI auth statusをネットワーク拒否のまま1台ずつ実測した。
証拠：専用WSLの `/home/fleet/controller-validation/auth-inventory-pf97d_w0/receipt.json`。
machineは `unclassified`（終了コード0、成功分類ではない）。
coordinator/toolchain/kernel/stdlib/storage/services/applications/devtools/assuranceの
9担当はすべて `not_logged_in`。全11VMと管理サービスの停止を確認済み。
生の認証出力を外部保存せず、認証ファイルを読取り・複製していない。
machineには別途SWE-2実応答の証拠があるが、このオフライン分類だけで認証済みとは判断しない。
10並列モデル利用には残る9担当の本人によるログインが必要。
6件のLinuxモックテストで分類スキーマ、生出力拒否、途中失敗時停止、全台の順次処理を確認。
固定入口 `launch_machine_auth.py --auth-inventory` はログインやモデル実行を行わない。

認証後のモデル利用実測は [CLI_READINESS.md](CLI_READINESS.md) を参照。
SWE-2のFree表示と無ツールの1回推論を確認済み。10並列本番運用は未開始。

2026-09-19、ユーザーがmachine VMの認証成功を報告した。
非秘密状態票 `/home/fleet/controller-validation/interactive-auth-pu57niv7/receipt.json`
でも `login_exit_code=0`, `phase=closed`, `network_denied_after=true`,
`all_vms_stopped=true`, `cleanup_errors=[]`, `model_executed=false` を確認した。
その後の読み取り専用実機確認でも、machine限定の編集可能なnetwork deny `**`
（ID `1fd42eb8-8bb7-43c3-aaf0-407775af732e`）が存在し、一時拒否8件は残っていない。
全11VM停止と管理サービス停止も再確認済み。
認証情報の中身は取得していない。後続でmachineのSWE-2利用・Free表示を確認した。
auth status出力の独立した成功分類と10並列モデル運用はまだ検証していない。
以下は過去の診断・手順であり、最新状態はこの節を優先する。

2026-09-19、隔離されたmachine担当VM内で実測した結果は `not_logged_in`。
CLI終了コード0でも認証済みとは扱わない。Dockerログインとは別の状態である。
証拠：専用WSLの `/home/fleet/controller-validation/auth-status-87u5t3wh/status.log`。
確認後は全11VMと管理サービスの停止を確認済み。

ユーザーの再開指示後、machine VM内のインストール済みCLIで
`auth login --help` を実行し、`--force-manual-token-flow` の対応を確認した。
証拠：`/home/fleet/controller-validation/auth-status-8bfhecr0/status.log`。
これはヘルプ表示のみで、ログインやモデル実行は開始していない。
ヘルプ確認後の全11VM停止も確認済み。認証先に限定した一時通信許可について
ユーザーから認証先限定の一時通信許可を取得済み。

2026-09-19 18:44 JST、ユーザー操作用の非記録端末を開いた。
ヘルパーのモックテスト5件は成功。ただし実機では通信ルール準備中に停止し、
状態票に `login_exit_code` はなく、ログイン実行には到達していない。
状態票は `phase=closed`, `network_denied_after=true`,
`all_vms_stopped=true`, `cleanup_errors=[]`。認証成功ではない。
端末の秘密入力は取得していない。ユーザー提供の例外は
`Temporary restriction identity unclear`。読み取り専用kitルールのID変動と、
複数宛先のdeny操作が8件の編集可能ルールを生成する挙動に未対応だった。
識別処理を変更し、既存の編集可能ルールと非編集可能ルールの内容を保存しながら、
今回追加したmachine限定denyのみを回収するよう修正した。
全面拒否を維持した実機検証結果：
`/home/fleet/controller-validation/interactive-auth-1_c08wpy/receipt.json`。
`policy_check_passed=true`, `network_denied_after=true`,
`all_vms_stopped=true`, `cleanup_errors=[]`。管理サービス停止も確認済み。
この検証は認証成功ではない。

## 公式手順とこの構成での選択肢

[公式コマンド資料](https://docs.devin.ai/cli/reference/commands)では、
`devin auth login` と、リモート端末向けの `--force-manual-token-flow` が案内されている。
後者はトークンを手動入力する方式であり、ブラウザのループバック接続を
この隔離構成で利用できると仮定する必要がない。ただし、インストール済み版での
オプション対応と、入力内容を記録しない対話端末の接続は実行前に確認する。

ログイン操作を行う場合は対象VM内のCLIを使う。Windowsや外側WSLにログインして
認証ファイルをコピーする方法は採用しない。トークンはチャット、コマンド引数、
ログ、Git管理ファイルへ貼り付けず、本人が対象の対話入力へ直接入力する。
認証ファイルの内容を読む必要はない。

## 実行前に必要なこと

1. ユーザーがブラウザ認証・必要時の直接入力に対応できることを確認する。
2. 対象VMだけを保守操作として起動し、固定の隔離された入口から接続する。
3. CLIのヘルプで対応オプションを確認する。ログイン用の通信が必要なら、
   実際の接続先を確認したうえで対象VMに限定して扱い、全体の拒否設定を解除しない。
4. 秘密入力を記録しない対話端末が用意できなければ、そこで止める。
5. 完了後は生出力を抑制した認証確認を行う。不明な出力は成功扱いにしない。
6. 一時通信許可を変更した場合は元に戻し、VMと管理サービスの停止を検証する。

この文書はログイン操作・通信許可・モデル起動を実行した証拠ではない。
認証できても、SWE-2の利用可否・無料キャンペーンの適用・同時実行枠・承認モードは
別に実測確認が必要。Enterprise向け認証資料の料金説明を、ユーザーのプランや
キャンペーン条件へそのまま適用しない。

[公式認証資料](https://docs.devin.ai/cli/enterprise/devin-auth)は認証ファイルを
機密として扱うよう説明している。ファイルのコピーが一般に案内されていても、
本構成では隔離境界を越える認証情報のコピーを行わない。
