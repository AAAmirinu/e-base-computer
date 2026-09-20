# E-base SWE-2 fleet

## 現在の入口：専用VM移行中（2026-09-19）

**下に残すWindows版の `Start` / `Resume` / `--cycles 0` は旧構成の記録です。
現在の専用VM運用の再開手順として実行しないでください。**
`VM_MIGRATION.md` の初期調査結果も時点付きの履歴であり、現状一覧ではありません。

現在は専用WSL `EBase-Sandboxes` 配下の担当別Docker Sandboxesを使用します。
認証済み担当VMで生成コードのテストを実行せず、別の認証情報なし検証コンテナへ渡します。
自動運転はまだ有効化していません。直近確認では管理サービス停止、
`production_enabled=false`、検証済み同時容量1、旧STOPありです。
10台の同時アイドル起動成功を、10並列Devin運転の合格とは扱いません。

目的別の現行資料：

- [CLI実測と未完了ゲート](CLI_READINESS.md)：無料モデル確認、容量、認証と実運転の区別。
- [担当別認証の引継ぎ](AUTH_HANDOFF.md)：本人が操作する非記録端末。トークンをチャットへ貼らない。
- [中断後の安全な通信復帰](MANAGED_RECOVERY.md)：通信を閉じる操作はジョブの再開ではない。
- [ターン復旧記録](TURN_RECOVERY_RECORDS.md)：途中状態・永続フェンス・セッションID復元の限界。
- [単発ターン接続](ONE_TURN_PIPELINE.md)：モデルからレビュー待ち保存までのAPIと、未接続の本番adapter。
- [PR候補と公開承認待ち](STDLIB_MAIN_PR.md)：main基準203テスト成功、公開送信は未実施。

残る9担当のログインは本人操作が必要です。PR公開には確認済み6ファイルと公開先への承認を待っています。
これらが済んでも本番admission、実ソース編集時の権限、負荷容量、実再起動・中断復旧の検証は別途必要です。
STOP・フェンスを削除して進めたり、認証ファイルを他担当へ複製したりしないでください。
PC再起動だけで自動再開したと判断せず、まず実プロセスと永続記録を確認します。

---

## 以下は旧Windowsバックエンドの仕様・操作記録

Devin CLIのSWE-2 Highを統括1＋専門9で運転する、ローカル研究開発用の実行基盤。
公開v0.2.0から開始し、guest上で動く計算・言語・OS相当基盤・ライブラリ・保存・サービス・アプリを育てる。
職責は`roles.json`、長期目標と証拠の規則は`CHARTER.md`に定義する。

## 実行の仕組み

各担当は独立したGitコピーとDevinセッションを持ち、次のサイクルでは同じセッションIDをresumeする。
最大10枠を並列に動かし、統括は前回までの報告・候補diffから次の課題と統合候補を選ぶ。
したがって初回は計画と実装、次回以降に前回候補のレビュー・統合が進む。
外側のPythonはモデルを呼んで判断しない。SWE-2統括の判断を検証して実行する。

担当の編集→所有パス検査→unittest→ローカル候補コミット→統括によるdiffレビュー→
別の統合コピーでmergeとfull publication audit→ローカルintegrationをfast-forward、の順。
失敗した編集、候補ブランチ、統合コピーは保存する。公開push、PR、main更新、Releaseは行わない。
共有パッケージ定義等の未割当パス変更は、統括が具体案をまとめ人間へ引き継ぐ。

## 操作

この端末の初期化済みfleetは、リポジトリ直下から操作する。
StartとResumeはウィンドウを表示せず継続運転する。認証・追加インストール・自動公開は行わない。

```powershell
./tools/devin_fleet/fleet.ps1 Status
./tools/devin_fleet/fleet.ps1 Start
./tools/devin_fleet/fleet.ps1 Drain
./tools/devin_fleet/fleet.ps1 StopAndWait
./tools/devin_fleet/fleet.ps1 Resume
```

| 操作 | 用途 |
| --- | --- |
| `Status` | 保存状態と実行ロック、停止理由、保留担当を確認する |
| `Start` | 停止フラグ等がない状態から継続運転を開始する |
| `Resume` | 保存状態を復旧し、停止フラグを解除して再開する。保留担当の権限は変更しない |
| `RunOnce` | 有限の1反復を実行する |
| `Drain` | 現在の反復と統合ゲートを終えてから停止する。計画した再起動の前に使う |
| `Stop` | 進行中のCLI・テスト・監査の停止を要求する。要求受付は停止完了ではない |
| `StopAndWait` | 停止を要求し、runnerの終了を待って確認する |

通常のPC再起動は、`Drain`→`Status`で停止確認→再起動→`Status`→`Resume`の順にする。
すぐ止めたい場合は`StopAndWait`を使う。待機がタイムアウトした場合は停止完了と扱わず、状態とログを確認する。
予期しない再起動後も、まず`Status`で復旧状態・error・保留担当を確認してから`Resume`する。
OS自動起動は登録していない。PC停止、スリープ、ログアウト中の作業継続は保証しない。

`Resume`は完了済みの報告・候補・Devinセッションを引き継ぐ。送信中のモデル応答そのものを
巻き戻して再生する保証はなく、未完了のターンは保存された編集と直前の証拠から進め直す。
破損したJSONやGitの不整合を修復できない場合は、原本を残して停止する。
保存されたPID番号だけでは稼働と判定せず、OSのglobal lockとrunner leaseを確認する。
runnerの強制終了では子プロセスが残る場合がある。起動前に既存Devinを検出した場合は
重複起動を拒否し、無関係なプロセスを自動終了しない。対象の実行ファイル・コマンドラインを確認してから対処する。
生成テストが子を残して先に終了する場合の完全回収も保証しない。runnerだけを強制終了した後は、
Devinだけでなくテスト用Python等の残存も確認する。PC自体の再起動とは異なるため、通常はStopAndWaitを使う。

実際にインストールされたPythonとDevinの絶対パスを指定する。初期化は既存rootを上書きしない。

```powershell
python tools/devin_fleet/fleet.py init --root .ai/devin-fleet-run --source C:/path/to/clean-release-clone --devin C:/path/to/devin.exe
python tools/devin_fleet/fleet.py run --root .ai/devin-fleet-run --cycles 1
python tools/devin_fleet/fleet.py run --root .ai/devin-fleet-run --cycles 0
python tools/devin_fleet/fleet.py status --root .ai/devin-fleet-run
python tools/devin_fleet/fleet.py stop --root .ai/devin-fleet-run
```

`--cycles 0`はチェックポイントを繰り返す。STOP/DRAINファイルの手動操作よりwrapperの操作を使う。
pausedではstateのerrorと各担当のrunログを調べ、原因を解消してから再開する。
実行中のプロセスを別のrunnerで置き換えない。

## コマンド承認と保留担当

CLIには`--permission-mode normal`を明示する。この版の`auto`はNormalの別名であり、
Smartではない。全承認のBypass/Dangerousも使用しない。Normalに役別の書き込み許可と
限定的なコマンドprefix許可を組み合わせ、追加agent・MCP・web等はdenyする。

Smartは別モードで、高速モデルが安全性を判断する。判断できない場合や、インストール・
変更を伴うGit操作・破壊操作等では通常の承認へ戻るため、無停止運転の保証にならない。
このfleetではSmartの判断や自動承認範囲拡大に依存しない。

非対話CLIが権限確認で終了したときは、同じセッション・同じ固定権限で最大2回、
許可済みfile toolだけを使う継続を指示する。拒否された操作を自動承認しない。
未解決の要求は`runs/<round>/<role>/permission-request-N.json`へ記録し、
driver側の`holds/<role>.json`と`state.json`の`blocked_roles`へ永続化する。
古いstateバックアップから復旧してもhold正本を再生する。専門担当だけが保留なら他担当は進行できる。
統括が保留の場合は全体を停止する。単なる`Resume`で保留担当の権限を広げたり解除したりしない。

保留担当の対処手順:

1. `Status`で担当名と要求ファイルを確認し、`StopAndWait`で安全に停止する。
2. 要求された操作、対象ファイル、必要な理由、`roles.json`の所有範囲を確認する。
   「何に困っているか」と「既存の許可された手段で解決できるか」を判断する。
3. 必要なら課題や依存調整方針を修正し、次のようにその担当を再試行する。

```powershell
./tools/devin_fleet/fleet.ps1 Resume -RetryRole storage
```

これは再試行の指定であり、要求されたコマンドの承認でも、所有範囲・権限の拡大でもない。
同じ要求が再発する場合は手順や担当分担を見直す。根本的に追加権限が必要なら、
影響するデータと操作を明示した別の判断として扱い、無限再試行で回避しない。

## 上限と未保証事項

- `swe-2-high`を毎回指定。catalogのFree表示とexport内のagent stepのmodel_nameを確認。
- 公式キャンペーンは2026-10-10まで。タイムゾーン未指定のため、保守的に10-10 00:00 UTCで停止。
- 1回30分、10同時枠、保存領域5 GiBを既定上限にする。model/catalog/CLI異常時は停止し有料fallbackしない。
- 同じWindows上に既存devin.exeがある場合、10枠起動を拒否。アカウントの別PCやDesktop利用までは検出しない。
- Linux向けにも既存`devin`/`devin.exe`のプロセス名検査を追加。取得失敗・不正な一覧は停止する。
  改名されたプロセスや他PCは検出できず、実Linuxでの動作確認はVM準備後に行う。
- このnative Windows構成はOS sandboxを使用していない。`Exec(ls)`、`Exec(cat)`等は
  コマンドprefix許可であって、読み取り対象や副作用をOSが限定するものではない。
  例えば範囲外のファイル読み取りやリダイレクトまで安全だとは保証しない。
  `Read(担当/**)`も排他的な読み取り制限ではなく、Normalではread-only操作が既定で自動承認される。
  資格情報用denyや所有パス検査だけで、ホスト全体が安全・秘密情報へ到達不能とは説明できない。
- 生成されたテスト、import、publication auditはローカルPythonで動き、DevinのCLI承認対象外である。
  CLIのコマンド承認と、生成コードの実行隔離は別問題として扱う。
  長期無人運転の隔離を強めるには、秘密情報を置かない専用VMや低権限の専用ユーザーを推奨する。
  このfleetにはその環境作成・移行・ネットワーク遮断を設定していない。
- 正式な課金情報はDevin側が管理する。exportチェックは実行後であり、将来の課金変更を事前保証するものではない。
- キャッシュ等を含む保存データは自動削除しない。ディスク上限到達時は整理方針の判断を待つ。
- 自動テストは実ブラウザーの目視受入や実測校正の代替ではない。該当する変更は未確認範囲を残す。

## 状態と検証

`state.json`には各担当報告・session ID・候補・統合commit、`runs/<cycle>/<role>/`には
プロンプト、CLI出力、export、実テストログを保存する。`.fleet/`は担当ごとの永続メモと受信箱。
モデルが書いたcommit/tests_passed等の権威的なフィールドは採用せず、runnerが実行結果から設定する。
runnerロックに加え、既存CLIプロセスを調べて親の異常終了後の重複起動を防ぐ。
完了した担当ごとに状態をatomicに保存し、バックアップと破損原本を復旧の証拠として残す。
コミット直後の異常終了はtreeと親commitを照合した受領票から復旧する。
integrationの実際のGit履歴と統合journalを照合し、統合直後・状態保存前の停止も復旧対象とする。
途中停止しても、直前の検証済み報告とテスト失敗の詳細をcheckpointsに残し、再開時に復元する。
担当に未統合候補がある場合も、次の反復で他担当の統合済み変更を取り込む。
Git競合は編集を保持して停止する。構文上の所有権分離だけで衝突がなくなるとは仮定しない。
統合に失敗・却下された候補の子孫を開発していた場合は、cleanな作業木に限り旧ブランチとdiffを保存し、
最新の統合版から修正用ブランチを始める。却下内容を自動再適用せず、担当が理由を読んで修正する。
統括の役割表・計画文書・統合失敗理由も毎反復で配布する。
過去の稼働記録は現在の稼働状態の証明ではない。例えば2026-09-15の初期検証では
Devin親プロセスにACP子プロセスが付く構成を確認したが、現在のセッション数は`Status`と実プロセスで確認する。
Fable MCPはpreflightのみ使用し、外部ライブ監査は未実行である。ローカルテスト成功を外部監査承認とは扱わない。

単体検証:

```powershell
python -m unittest discover -s tools/devin_fleet -p 'test_*.py' -v
```

## 参照（2026-09-15確認）

- [Devin pricing](https://devin.ai/pricing) — Desktop/CLI向けSWE-2無料期間
- [CLI commands](https://docs.devin.ai/cli/reference/commands) — normal/auto・resume・export
- [CLI permissions](https://docs.devin.ai/cli/reference/permissions) — Smartと固定規則、OS sandboxの区別
- インストール済みCLI 3000.10.21のhelpとmodels list、実exportでSWE-2 Highを確認
