# 検証snapshotとcommit treeの照合

`snapshot_git_tree.py` はcanonical manifestとSHA-256 blobsを検証した上で、
Git SHA-1形式のtree IDを純粋計算する。プロジェクトコードやGitは実行しない。
通常ファイルmode 100644/100755、UTF-8パス、生bytesをそのまま用いる。
ディレクトリmodeは40000、各階層でdirectory名に比較用 `/` を付けてbyte sortする。
Git object形式の参照: https://git-scm.com/book/en/v2/Git-Internals-Git-Objects

`verify_commit_tree` は信頼済みGitから得た特定commitのobject format/tree IDを照合する。
SHA-256 repoやtree不一致は拒否。比較対象はworking treeやindexだけではなく、
最終commitのtreeでなければならない。

## 実データ確認

- 検証snapshot: `6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff`
- 検証実績: 新Git imageで121files、203tests成功。
- 候補commit: `7d0e065378030c83f66675ff942d920f44f1ba8c`
- repo: `.ai/devin-fleet-run/pr-stdlib-main`
- 実repo object format: `sha1`
- snapshot計算とcommit実測の双方:
  `cf35cb8b8152686c71e29c940fe3d6242c7c1872`

snapshot計算は専用WSLの管理コードで実行。commit実測は所有者コンテキストの
read-only `git rev-parse`。通常sandboxでは所有権確認で拒否されたため、設定を
書換えずread-only操作だけを承認付きで行った。commit/push/hook設定変更は無し。

45純粋テスト成功（0.010秒）: tree計算7件、snapshot入力、dispatch結果、turn結果binding。
空tree、既知blob、directory並び、UTF-8、生binary、mode/改行/path変更、異なるformatを確認。

## 組込みと残り

`validation_snapshot_dispatch.py` は新規dispatch journalに `expected_git_tree` を保存する。
過去の証拠は改変しない。今回の既存commitとの照合はこの文書の実測記録であり、
過去dispatchにこの項目が保存されていたとは扱わない。

tree照合は親commit、作者、署名、テスト合格、bundle由来、Git実行時の副作用を
証明しない。SHA-256 manifest/blob検証も引き続き必要。自動commit作成、bundle回収、
turn確定とfence解消への接続はまだ未完成。production_accepted/committedはfalse。

## 親を保持した隔離candidate builder（実運転未確認）

`container_candidate_commit.py` を追加。呼出し先は境界確認済みの資格情報なし
コンテナのみ。UID65532、container marker、限定environmentを事前確認するが、
これだけで隔離を保証しない。外側driverのimage/config/boundary確認は必須。

digest固定parent bundleと検証snapshotからfresh `/work/candidate`を作る。
通常のGit init後に、既定4項目だけのeffective configとsample hooksを確認し、
未知のtemplate設定（hooksPath/fsmonitor/filter等）なら拒否する。hookや署名設定を
無効化しない。checkoutせず親objectをfetchし、fresh indexだけをreset --mixed、
add後と通常commit後のtree、唯一の親、clean状態を確認してbundleを返す。
Git出力の1MiB検査は取得後の上限判定であり、取得中のメモリ上限ではない。
実行時は既存コンテナのmemory/pids/time制限とfinally停止が必要。

親bundle準備済み（外部送信なし、既存ref/tree変更なし）:

- ローカル `.ai/validation-parent-main-v1.bundle`
- ref `refs/heads/fleet/integration`
- parent `616ad6b343a58651eba4310123ab267cd74fa2b7`
- bytes `474030`
- SHA256 `fa7c9186279947622c9cf3e9f60d1b28e8881aa0305392516009abd4463f8078`

29純粋テスト成功（0.006秒）。設定の拒否、外側UIDでの実行拒否、snapshot/tree照合。
このbuilderによる実candidate commitは未実行。親bundleの専用WSL移送、隔離container
への入力、bundleのbounded回収、停止と結果のdurable bindingが次の実装対象。
既存のstdlib候補commitの公開許可待ちは、このローカル準備とは別のまま。

## 隔離candidate作成と外側回収の実測

固定driver `run_stdlib_candidate.py` と保守入口 `--build-stdlib-candidate` を追加。
固定203件合格のdispatch/stdout照合、入力bundleのSHA256、全VM停止、通信拒否、
排他lock、一度だけのdurable予約を満たしてから実行する。
SIGINT/SIGTERM/SIGHUPはcleanupへ移行し、VM停止失敗でもreceipt保存を試みる。
SIGKILL/電源断でfinally実行は保証できないため、予約は自動解消しない。

53純粋テスト成功（0.010秒）、管理driver/埋込プログラムの構文確認、
固定入力packet 1879980bytesのdigest照合後に、一度の実行が成功した。

- 証拠directory: `/home/fleet/controller-validation/stdlib-candidate-as9h24h6`
- receipt phase: `candidate_recovered`
- 新commit: `88e295f7f71a4241a3ca65e99ac5aebcec903d20`
- 唯一の親: `616ad6b343a58651eba4310123ab267cd74fa2b7`
- tree: `cf35cb8b8152686c71e29c940fe3d6242c7c1872`
- snapshot: `6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff`
- 新bundle: 同directoryの `candidate.bundle`、487184bytes
- bundle SHA256: `9b89d4a565bb650d66962cf1b5af7efe2219c3ab90d455412170f446aafb2406`
- 合格dispatchのSHA256: `e2d2484fc6e5757b2c6dbee99d29e76f29436247ba04d4d966e4f4af30b0698c`
- コンテナ: `43730ef3ef988298c007617dc8cf8904276a5875a5ab3eb087c13f513795ba87`
- image: `sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4`

コンテナ境界観測、コンテナ停止、全11VM停止、管理サービス停止を確認。
外側へ保存したbundleの実ファイルを再読込みしてサイズ/SHA256も確認した。
通信開放、hostでのproject実行、既存tree更新、公開は行っていない。

このcommitは同じ内容を隔離経路で新規作成したもので、先のローカル候補
`7d0e065...`を上書きしていない。親/tree一致は確認済みだが、回収bundleの
別の新規containerへのimport照合は未実施。turn/fence/scheduler接続も未完成。

## 回収bundleの別コンテナimport照合（上記未実施項目を実施）

固定入口 `--verify-stdlib-candidate-import` を追加。回収元receiptのSHA256、
固定commit/bundle digest、元の合格dispatchを結合し、新規containerのfresh repoへ
bundleをimportする。checkoutせず、Git objectから全ファイルを直接読み出す。

- 証拠: `/home/fleet/controller-validation/stdlib-import-_7gqahb2/receipt.json`
- phase: `import_verified`
- 回収元receipt SHA256: `2241058772c409fd47360951e0fd49ce0623ae389095d9163a47e2f645f6f872`
- 別container ID: `9c8bdb6e3cf847312c35805ac3f6530d29ef5267bfcefe8b86b58865bf8d46a0`
- commit `88e295f7f71a4241a3ca65e99ac5aebcec903d20`、唯一の親、treeが一致。
- bundleにはこのcommitを指す `refs/heads/candidate` だけがあることを確認。
- 121全path集合・各blobサイズ/SHA256が検証snapshotと一致。
- `checked_out=false`、`source_executed=false`、`published=false`。
- コンテナ境界観測、コンテナ停止、全11VM停止、管理サービス停止を確認。
- 実行前55純粋テスト成功（0.015秒）と構文検証。独立レビュー実施。

これで、この固定stdlib候補について「検証snapshot→隔離通常commit→bundle回収→
別コンテナimportで内容照合」の経路は実測済み。任意turnへの一般化、再起動を跨ぐ
turn/fence確定、継続scheduler、本番admissionはまだ未完成。

## 証拠連結の機械検証

`candidate_evidence_binding.bind_candidate` を追加。固定パスに依存しない純粋関数で、
protectedなcontroller所有の証拠bytesを呼出し元から渡す契約。
snapshotのSHA256/treeを再計算し、dispatchと実stdout、buildのdispatch SHA256、
importのbuild receipt SHA256、回収bundle本体を照合する。
検証・作成・importが別containerであること、各停止記録、image、親、tree、
commit、file countも確認。重複JSON keyやbool/int取り違えを拒否する。

`check_stdlib_candidate_evidence.py` で既存実データを読取り検証済み:
`/home/fleet/controller-validation/candidate-binding-vzirxjxf/receipt.json`。
203件のcommand成功と121filesのcandidate import照合を同一bundleへ連結できた。
VM起動、通信、Git実行、元receipt変更、fence解除はしていない。

返却値は明示的に `turn_bound=false`、`runtime_state_observed=false`、
`review_required=true`、`production_accepted=false`、`resume_available=false`。
検証コマンド成功と、意味的なテスト合格・運転再開の権限は区別する。

独立作成テストと異常nested値テストを含む40件成功（0.016秒）。
最終版による実証拠の再照合も成功:
`/home/fleet/controller-validation/candidate-binding-een32ryn/receipt.json`。

## モデルturnとの接続

`bind_turn_candidate` は `load_turn_binding` で検証済みのbindingと現登録を受け取り、
担当role/VM/epochの一致を確認する。`bind_result` と `bind_candidate` を元の
dispatch/stdout/snapshot/build/import/bundle bytesから再実行し、同じturnの候補だけを結ぶ。
事前計算されたsummaryだけを信頼しない。未知role、異なる登録世代、別VM、保守用
dispatch、失敗した検証を拒否する。

成功しても `fence_release_authorized=false`、`resume_available=false` のまま。
現時点の専用WSL registryはproduction無効、migration_epoch/controller_root未登録、
実stdlib dispatchにはturn_evidenceがないため、この保守証拠を通常turnへ昇格させない。
登録/過去dispatchを書換えてこの条件を満たしたように見せることも行わない。

独立追加の6turn接続テストを含む46件成功（0.018秒）。
実registry/dispatchのread-only確認でも、上記未登録・保守証拠状態を確認した。
本番turnの実モデル→候補完了までのend-to-end試験は未実施。

## Durableなレビュー待ち記録

`candidate_review_store.record_candidate` は信頼済みcontrollerのglobal lock下で使用する。
現登録root、turn/candidateの全証拠、未解決fenceのoperation/epoch/role/sequence/VMを照合。
`candidate-review/<operation>/` を排他的に作り、bundle、dispatch/stdout/build/import、
content-addressed source snapshotをfsyncしてから最後に `candidate.json` を保存する。
途中障害時はdirectoryを残すため、同じoperationへの再試行は既存出力を上書きせず拒否。

`inspect_candidate` は保存した証拠から全bindingを再計算し、元fenceのSHA256も確認する。
partial record、archive破損、fence変更は要調査として拒否する。どちらもfenceを削除せず、
VM/モデル/Gitを起動せず、PRを公開・mergeせず、運転再開を許可しない。
本番ターンの成果を保存するAPIであり、現在の保守候補を本番turnと偽って登録しない。

専用WSLのprivate一時ディレクトリで48件成功（0.030秒）。内14件は新storeの
保存・再読込・write/fsync障害・重複・symlink・fence変更検知。実binderと実reserve_turnを
使った合成証拠の保存→inspect統合も含む。本番recordの作成やfence解除は未実施。
