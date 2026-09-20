# 専用VMの1担当・1ターン接続

## coordinator認証・モデル実測（2026-09-20）

可視Windows Terminalでcoordinatorを個別ログイン。最初のCodex内PTY試行は入力不能だったため
Ctrl+Cで中断し、Cleanup complete/service停止を確認してから可視端末で再試行した。
auth inventory `/home/fleet/controller-validation/auth-inventory-v_lfit7k` でcoordinatorは
not_logged_inからunclassifiedへ変化。これは肯定証明ではないため担当別固定model smoke入口を追加。
固定LOGIN_ROLES以外や余剰引数を拒否し、既存machine_cli_smokeを選択担当だけで再利用する。
入口関連26テスト成功（0.008秒）。

実機証拠 `/home/fleet/controller-validation/interactive-auth-yqebbkt6`:
returncode=0、response_marker_seen=true、exact_model_verified=true、no_tool_calls=true、passed=true。
SWE-2 Highの固定短文1回だけでproject入力なし。raw output suppressed。
Cleanup complete、全VM停止、管理service停止。候補registryのactivationは未実施。
toolchain/kernel/stdlib/storage/services/applications/devtools/assuranceの8担当はnot_logged_in。
machine/coordinatorはinventory上unclassifiedだが、それぞれ別の実モデル証拠がある。
残るactivation blockersは8担当認証、Normal権限付き実turn、full turn、予期せぬ再起動復旧。
Fable最新はhistorical not_runで監査合格ではない。

## 本番登録候補の一回限り準備（2026-09-20）

production_registration_prepare/entryと管理launcherのprepare/inspectを追加。
固定run production-registration-preparation-v1を排他的に作り、source registryとcandidateを
O_EXCL/O_NOFOLLOW+fsyncで保存し、commit.jsonを最後に一度だけ書く。途中停止runは
再開・削除・再利用しない。launcherは11 VM停止確認から子終了・最終停止確認まで同じ
global lockを保持するよう修正。registryはraw bytesとstatを前後照合する。
専用rootはproduction-<32hex>直下の空cycles/operations/model-turn-fencesだけを許可。
関連40テスト成功（0.027秒）。

実機prepare成功:
- controller_root=/home/fleet/controller-validation/production-8ef6dc7526b249889ec0c5b3e1764d22
- migration_epoch=3f30015c-e26b-4b09-b741-dc59c1d0769c
- candidate_sha256=7721e6c83db493406ea71a3e0e965d4cdc287a13aa1679dbe67d3259d75fb682
- source_sha256=afd5e5f94691c2237cde2219e114fbc66ad95acff57f7be87b0663756874c9bf

別の管理起動によるinspectも同値で成功。active sandbox-registryは
production_enabled=falseのまま。候補runはstatus/source/candidate/commitの4ファイル、
production rootは空の3管理directoryのみ。各操作後に全VM停止をlauncherが検査し、
service inactive/dead/MainPID=0を別readで確認。通信・モデル・activationは未実施。
この候補は消費済み一回限りで、再prepareしない。次はactivation前readinessと
既存STOP/fence/permission/authの明示的な受入判定が必要。Fableはhistorical not_run。

## 本番登録候補の非破壊生成（2026-09-20）

production_registration_candidate.compose/validateを追加。現行の旧検証登録を
厳密schema（EBase-Sandboxes/fleet/2 CPU/4g、容量1、10 roleのid/name）として読み、
既存objectを変更せずにbackend=sandbox、専用production-<32hex> root、canonical UUID epoch、
固定validation image、全roleの固定image digestを持つ候補へ変換する。
schema/capacityはboolをintとして受け付けず、role ID重複や余剰fieldも拒否する。

初回テストでTrue==1によるschema型の見逃しを検出しexact intへ修正。
次に実機登録がbackend未付与の旧schemaであることを非秘密要約で確認し、旧field集合を
一意に受理して候補側へbackendを追加する移行形へ修正した。実機登録からの非破壊合成に成功し、
candidate keys、10 roles、capacity=1、production=true、全image pinを確認。
関連36テスト成功（0.021秒）。実registryはproduction_enabled=falseのままで、
候補の保存・root作成・fence作成・activation・VM/model実行は未実施。
登録fieldを埋めるだけでは受入にならず、次は一回限りのcandidate準備とreadiness検査が必要。
Fable最新はhistorical not_runで監査合格ではない。

## 管理CLI接続（2026-09-20）

launch_machine_auth.py --registered-turn-once <32桁hex> を接続。
不正引数はservice起動前に拒否し、管理namespace内のregistered_turn_entry.pyへ
--onceと固定IDだけを渡す。入力loader→固定adapter実行を既存signal cleanup内で実行。
任意パス、任意callback、resume、自動再試行は提供しない。成功時の標準出力は
invocation_returnedという呼出終了票であり、候補受入/監査合格や公開の証明ではない。
失敗時は終了票を出さず例外を伝播し、既存journalと停止処理へ委ねる。
新規4件と入力/接続/guard/単発処理の計32件成功（0.023秒、実VM/modelなし）。
production_enabled=falseの登録は変更していない。運転入力準備、本番条件の受入、
実一巡検証は未実施。CLI追加だけで継続オーケストレーターが稼働したとは扱わない。
Fable取得はhistorical not_run。

## 運転入力loader（2026-09-20）

registered_turn_input.load(identity)を追加。controller直下turn-inputs/<32桁hex>の
request.jsonとparent.bundleをbounded/nofollow読取し、固定registryと照合する。
本番rootはcontroller直下production-<32桁hex>に限定、cyclesとprojectはその内部。
厳密schema/type/ref/SHA、重複JSON/nonfinite拒否、STOP/既存cycle拒否を行う。
返却前にregistry/request/bundleを再読し、内容変更を拒否。読込は予約や実行ではない。
既存実行側の排他・登録再照合・exclusive mkdirは引き続き必須。同UID攻撃の完全な
競合耐性はこの二重読込だけでは証明しない。親bundle内部は実行せず後段の隔離検証へ渡す。
新規5件と既存接続/guard/単発処理の28件成功（0.021秒、実VM/モデルなし）。
固定管理CLIへの接続と本番登録は未実施。Fableはhistorical not_run。

## 固定adapter接続入口（2026-09-20）

registered_one_turn.runを追加。既存run_registered_one_turnへ、容量1のSandboxRuntime、
sandbox_validation_adapter.validate、親bundleを束縛したcandidate adapterを固定接続する。
callerから任意のruntime/検証/本番guardを渡す入口ではない。既存本番登録が必須で、
登録の作成・権限拡大・STOP解除・自動再試行・公開は行わない。
親bundleのbytes上限とSHAを起動前に確認し、内容のGit検査は既存credential-free検証へ委ねる。
固定接続3件と既存guard/単発pipelineを合わせ23テスト成功（0.016秒、model/VMはmock）。
実機一巡やschedulerの動作証拠ではない。次に信頼済み運転入力のロードとCLI接続、
本番登録の受入条件、coordinatorへの課題/結果受渡しを接続する必要がある。

以下の歴史節にある「モデルadmission未実装」「Git制限未実装」は当時の状態。
現コードにはregistered_turn_guards/model_turn_admission/guest_git_read_policyが存在する。
実装の存在と本番受入は区別する。最新MCP正常経路実測はMCP_DENIAL_ACCEPTANCE.md参照。

`sandbox_one_turn.run_one_turn` は単発の運転API。
本番起動CLI・scheduler・自動再送・PR送信ではない。

1. 明示したproduction登録/private root/role/sequenceと全adapterを検査。
2. runtimeのglobal lock下で既存 `run_guest_model_phase` を呼び、runtimeを閉じる。
3. 保存済みcapture/turn/snapshotを読み直し、別validator adapterを呼ぶ。
   dispatch/stdoutを保存して元証拠を `bind_result` で再照合。
4. 同じsnapshotのbuild/import adapterを呼び、build/import/bundleを保存。
   runtimeを再取得し全VM停止の通常admissionを通して、`record_candidate` へ渡す。

モデル担当runtimeを保持したまま別validatorのglobal lockを取りに行かない。
adapterには成功boolではなくraw evidence bytesを要求する。候補保存時にも
turn・検証・build・import・bundleの全照合を行う。

## 停止と保存

- `cycle_directory` は専用root下の新規directory。既存cycleへ再実行しない。
- `cycle.json` に各段階を記録し、例外時は `held` と中断段階・例外型だけを保存。
- validator戻り後は `validation-result/`、build/import戻り後は `candidate-result/`
  に元証拠を保存し、journalへSHA256を記録。
- 各次段階の前にSTOP確認。モデル途中中断は既存model/runtimeの停止責任を維持。
- 元turn fence、途中出力、candidate-reviewは自動削除しない。
- `pending_review` になっても公開・merge・fence解除・次ターン再開は許可しない。
- 保存障害/電源断で古いjournalが残る場合がある。最新phaseだけで再送しない。

## adapter契約と現状

- `runtime_factory`: 同じ登録/rootと共通global lockを使うSandboxRuntimeを生成。
- `admission`: 無料モデル、権限、容量、期限、通信範囲などを検証する本番関数。
  auth statusの肯定表示は必須とせず、利用可否は一回の実モデル応答で確定する（末尾参照）。
  signatureは `(runtime, role, settings, *, stage, repo, prepared, timeout)`。
  initialではrepo/preparedなし、before_prepareでは有効な同role leaseを渡してGit読取前に確認、
  before_modelでは同leaseとstaged config/prompt等のpreparedを渡す。
  before_inspectionでも新しいinspection lease上のGit読取前に確認する。
  timeoutはターンと無料期限の残り秒。callback内で同roleのleaseを再取得しない。
- `validate(snapshot_directory, capture_path, turn_path, registration)`:
  `dispatch_raw`, `stdout_raw`, `validator_id`, `image_id` を返す。
- `build_and_import(binding, evidence)`:
  `build_raw`, `import_raw`, `bundle` を返す。

後二者はそれぞれ資格情報なし隔離環境の実行と停止に責任を持つ。
検証は `sandbox_validation_adapter.validate` から既存隔離dispatcherへ接続済み。
管理namespace・明示production/image登録・保存済みturnを要求し、排他lock取得後にも
登録の一致を再確認する。停止を含む実出力を再照合し、不確実な結果は再送しない。
新Git imageの保守用flagと登録済み本番用flagは分離している。
build/importは `sandbox_candidate_adapter.build_and_import` を登録・親bundle/SHA/refで
partial束縛して任意turn契約へ接続できる。固定stdlib保守driverの予約は引き続き別管理。
入力組立は `candidate_packet.prepare_build/prepare_import` に共通化済み。
snapshot/base/refを明示し、snapshot/tree、bundle SHA・サイズ、候補metadata、
信頼済みmoduleの厳密な名前・byte上限、最終packet上限を確認する。
moduleの真正性は名前検査では証明できず、保護されたcontroller由来であることをcallerが担保する。
親bundleのGit object/ref検査は引き続き資格情報なし内側containerでのみ行う。
固定stdlib経路も同関数を使用するが、既存実行予約を解除・再実行しない。
`candidate_container_run.execute(packet, work, admission=...)` は任意候補用の
共通実行primitive。専用namespace・global lock・11VM停止・validator blanket denyを要求し、
固定imageの既存GUEST/INNERを使用する。新規attempt directoryを永続予約とし、
入力SHA、元stdout/stderr、停止結果を保存する。失敗時も予約は残す。
登録/fence/STOPを検査するadmission関数は必須で、lock取得後とVM実行直前に呼ぶ。
signal handlerとpolicyの一時変更は復元し、timeout/割込みでもVM停止確認を試みる。
返却は停止済みの元guest結果であり、candidate受入や本番turnの承認ではない。
packet内moduleは実行されるため、モデルの出力を直接packetとして渡してはいけない。
候補adapterは `candidate_turn_admission.make_admission` で保存済み登録/STOP/予約/
snapshot/capture/turnを再照合し、構築後の期待値変更を拒否する。
build/importの試行先はepoch+operation+stageから固定し、再起動・同ターン再送でも
既存directoryを上書きしない。元ログと停止receiptのSHAを確認して候補証拠を保存し、
最後に `bind_turn_candidate` で全結果を再照合する。公開・fence解除は行わない。
モデル実行用admissionと本番CLI登録は未完成で、欠落adapterを省略する既定実装はない。
したがってAPI追加を本番一巡・10並列運転の実証とは扱わない。

## 検証

専用WSLで完全mockの単発接続・既存モデル段階・候補保存の59テスト成功（0.065秒）。
validate/build中はmodel runtimeが閉じていること、成功時のreview保存、モデル失敗時の
後続未呼出、検証失敗、STOP、途中例外、既存cycle拒否、adapter欠落を確認。
初回は保存段階追加後の古いテスト期待値1件が失敗し、`validation_recorded` と
元証拠の保存を確認する期待へ修正して再試験した。実VM/model/Gitは起動していない。

検証adapter追加後、同じ群とadapter契約12件の計71テスト成功（0.074秒）。
dispatcherはmock、結果の純粋照合は実関数を使用。登録変更、未登録image、停止未確認、
observer欠落/重複、実行例外と成功票の矛盾を拒否することを確認。
lock内の登録再照合分岐自体の競合注入テストは未実施。

変更したdispatcherの固定stdlib保守経路も実隔離コンテナで再検証した。
証拠: `/home/fleet/controller-validation/dispatch-99093cbd5b1a4f79ac409e6e01f82a28/dispatch.json`。
203件成功（4.253秒）、skipなし、container/VM停止、管理service inactive/dead/MainPID=0。
この保守実測にはturn bindingがなく、本番adapterの一巡実証には含めない。
`validation_passed=false`・production未登録の状態を維持している。

候補入力共通化後: packet/inner入口/tree/候補証拠/単発ターンの59件成功（0.042秒）。
異なるsnapshot/base/refの受入と改竄・危険ref・module・サイズ拒否を確認。
既存実候補 `stdlib-candidate-as9h24h6` と固定snapshotをデータとして読み、
build packet 1883446 bytes / import packet 2533482 bytes、121ファイル、
tree `cf35cb8b8152686c71e29c940fe3d6242c7c1872` の互換性を確認した。
この確認ではGit・VM・モデルを起動していない。共通化後の実build/importは未実施。

共通実行器追加後: lifecycle12件を含むpacket/inner入口/候補証拠/単発ターン/
validator adapterの計76件成功（0.068秒）。VM/subprocess/signal/lockはmock、
証拠ファイルはprivate temporary directoryへ実保存して検査した。
timeout、KeyboardInterrupt、壊れたJSON、停止・停止後inventory失敗、admission拒否、
境界不一致で成功を返さず、元証拠・予約・handler/policy復元を確認。
この時点で共通実行器による実VM試験は未実施。

候補adapter/turn admission追加後: 関連80件成功（0.079秒）。runnerはmock、
候補/検証証拠binderとprivate一時ファイルは実処理し、異なるbuild/import container、
同turnの試行先固定・再送拒否、停止/hash/metadata不整合を確認。
初回はテスト補助メソッド名 `run` がunittest APIと衝突して起動失敗し、
`run_candidate` へ改名して再実行した。
packetのJSON sortによってINNER moduleの依存順が壊れる不具合をreviewで発見し、
receiver → tree → builderの固定順へ修正。合成moduleのみのbuild/import2テストでも確認。
この新adapter経路での実VM build/import・モデルを含む本番一巡は未実施。

## 共通実行器の実隔離試験

`launch_machine_auth.py --verify-common-candidate-import` は固定保守試験。
既存 `stdlib-candidate-as9h24h6` のSHA固定bundleを新しいcredential-free containerへ
再取込するだけで、モデル・新規commit・本番turnを実行しない。一回限りの固定予約を残す。

初回は専用controller directoryが755で、private root検査によりVM/予約作成前に拒否。
fleet所有・symlinkでない・試行予約不存在を確認し、当該directoryのみ700へ厳格化した。
再実行では121ファイルとcommit/parent/tree/bundle一致、checkout/source実行なしで成功。

証拠directory:
`/home/fleet/controller-validation/candidate-attempt-f7a0c7658bb85238cf61fcb6d4ff8b74`

- container: `bab83280fdf6dbc919d7a61daea6920ac3a2671f3ccadfcbd7ddf7a0ba13a2fe`
- runner receipt SHA256: `5b18e8868afd25ff79b174ca0dbb89668efb4ff364e45984e068c208b6123786`
- stdout SHA256: `e00b7290d890b575997c0579063778fd37e4d559d8c55b7ce03fcc76b8e0ef93`
- 保存済みhashを別readで再照合。all_vms_stopped=true、service inactive/dead/MainPID=0。
- production_enabled=false、turn_bound=false、published=falseを維持。

共通runner/INNERの実import経路は確認済みだが、新adapterのbuild→import全体と
モデルを含む本番一巡・10セッション並行運転は未実証。保守成功で本番予約を解除しない。

### 共通build/import全経路（2026-09-20）

`run_roundtrip` を本番adapterと保守probeで共有し、従来の本番予約hash入力
`epoch:operation_id:mode` は維持した。抽出後のmock回帰80件成功（0.078秒）。
固定保守action `--verify-common-candidate-roundtrip` で実生成→独立再取込に成功。

- build証拠: `/home/fleet/controller-validation/candidate-attempt-608becdcc7ac3a1cd599dc9b760c37f8`
- import/proof: `/home/fleet/controller-validation/candidate-attempt-da7e3e16793249303859bd3adcf13b13`
- commit: `b9ad3cd1b7ca2ce59a0ffeac65a031b226731e3f`
- tree: `cf35cb8b8152686c71e29c940fe3d6242c7c1872`
- bundle SHA256: `64d995cfab9c83333da34694c0ffdffeecb0a938f320a02059a4f3cec54a66dc`
- build receipt SHA256: `9f42b2b1ad837088b07a4561f7092a1e47c3ddeba7ddc0e8b4b7ec72491a7e17`
- import receipt SHA256: `8a6044151fda0b7e08c8ef532ee0dbf57ea23e814c7478025e04b109e2114747`

203テスト成功済みの固定snapshotに対し、121ファイルとparent/tree/bundleを実照合。
元validation・build・importの3containerが異なることを実binderが検査した。
保存済みcandidate/runner/stdout/bundleも別readで再照合、全VM停止記録と
service inactive/dead/MainPID=0を確認。production_enabled=falseを維持。
これは共通生成・再取込機構の実測であり、本番turn admission、モデルを含む一巡、
10担当継続運転、再起動途中復旧の実証ではない。公開・fence解除は行っていない。

## モデル側の残ゲート（2026-09-20）

GuestRepositoryのcontroller Gitは現状環境/configを継承するため、読取gitでも
fsmonitor/filter等を介したコード実行を排除できていない。モデルのExec denyとは別問題。
before_prepare/before_inspectionへの確認口は追加したが、安全なGit境界の実装・実測は未完。
auth status probeはnot_logged_in/unknown分類のみで肯定的な認証証拠にはならない。
実catalog取得・認証・有効policy・容量を含む本番admissionは引き続き未完成。

guest promptは全Exec禁止・file toolsのみ・別資格情報なしvalidatorで検証する説明へ修正。
legacy host promptの読取りshell説明とは分離した。
公式permissions資料（https://docs.devin.ai/cli/reference/permissions）も確認した。
Smartは不確実な操作でpromptし、Normal+明示scopeでも上位組織ask/denyは残り得るため、
無人運転で承認待ちが発生しないという保証には使わない。自動権限拡大は実装しない。

段階別API/prompt修正後、model phase/guest staging/単発ターン/candidate adapter/
candidate admissionの計69テスト成功（0.084秒）。準備前・検査前の拒否で後続Git/モデル/
captureを呼ばず、lease停止とfence保持を確認。すべてmockで実モデルは起動していない。

### モデル処理のGit読取り経路

モデル準備と出力検査の両leaseで `restrict_git_to_model_reads()` を設定する。
そのleaseのGitは `git_read` に切り替わり、HEAD読取・tracked一覧・untracked一覧・
変更名一覧の4種類の厳密argvだけを許可する。保守sync等の従来Git APIは別経路のまま。

guest側では実directoryの.git、固定HOME、GIT/LD/XDG制御変数不在を要求。
固定 `/usr/bin/git` と最小環境でconfigをbounded/privateに列挙し、fresh core4項目と
user.name/email・remote.origin data以外を拒否する。include先は `--no-includes` で
読まず、そのdirective自体を拒否する。設定変更、hook/signature無効化は行わない。
gitlinkを含むindexは拒否し、diffではexternal diff/textconv/submodule traversalを抑止。
参考: https://git-scm.com/docs/git-config 、 https://git-scm.com/docs/git-diff 。

純粋policy8件・ルーティング追加1件を含む回帰74件成功（0.074秒）。
有効設定列挙と実Gitの間の同UIDによる改変まで防ぐOS境界ではない。
preflight時間制限は既存controller timeoutとVM全停止に依存する。
実Gitでの悪意あるfilter/fsmonitor設定・canary・timeout試験は未実施。
これだけで本番admissionや認証VMの完全隔離を受入済みとはしない。

### 実Gitによる合成境界試験（2026-09-20）

固定action `--verify-git-read-policy` をcredential-free/network-none validation
containerで実行し成功。実 `_GUEST_CODE` のgit_read分岐を子プロセスで呼び、
正常4argvのHEAD/追跡/未追跡/差分名を期待bytesまで照合した。
正常commit後のfresh repositoryに各設定を追加し、filter.clean、filter.process、
fsmonitor、diff.external、diff.textconv、include.path、commit.gpgsignの7種を拒否。
canary不存在と書込みpositive controlを確認。include先FIFOもtimeoutに至らず拒否した。
署名設定の拒否は確認したが、読取試験なので署名実行の遮断試験とは扱わない。

- 証拠: `/home/fleet/controller-validation/git-capability-yootqky3/receipt.json`
- receipt SHA256: `ffa0350dcad8f7f37949e87064e437897998938ea93e0441a913fe42b3c96e17`
- container: `957c4aa2db7e6437902243f30ccd126853233e6d055d195d89bd61c21f712337`
- closed、container_stopped=true、all_vms_stopped=trueを保存後別readで確認。
- service inactive/dead/MainPID=0。モデル・実プロジェクトコードは実行していない。

残る境界試験: 環境変数注入、gitlink、.git symlink、出力上限/timeout時の停止。
この試験は認証VMの実設定の受入や同UID改変競合への耐性を証明しない。

### 追加の実Git境界ケース（2026-09-20）

同actionの拡張版を新規credential-free containerで実行し成功。
正常4読取り・危険設定7拒否を再確認したうえで、GIT_CONFIG_COUNT注入、LD_BIND_NOW、
XDG_CONFIG_HOME、HOME不一致の4環境ケースを拒否。同rootの通常HEAD成功も確認。
既存合成commitから作ったgitlink160000、fresh repo内だけでリンク化した.git、
HEAD出力limit8、70KiBのuser.nameも空データの拒否応答を確認した。
大容量設定拒否は確認できたが、実測だけで収集中制限と収集後検査の違いまでは主張しない。

- 証拠: `/home/fleet/controller-validation/git-capability-_wtxy_i1/receipt.json`
- SHA256: `dcc7b31ccbff0e83e61091f7b753daa4e949eaaf59c98f86124094de4ea955b6`
- container: `4ac66b96891ef043e8fa84fd92cdda01439ac119240d83e6696eb03ec05e0811`
- 保存結果別read、全VM停止、service inactive/dead/MainPID=0確認済み。
- timeout_cleanup_verified=false。外側controller timeoutによる実停止試験は別途必要。

### 外側controllerによる実timeout停止（2026-09-20）

固定action `--verify-git-read-timeout` で新しい一回限りの試行を実施。
資格情報なしcontainer内の合成repoの.git/configをFIFO化し、実 `_GUEST_CODE` の
git_readを起動。Popenの子/proc exe/argv/sleep状態を確認したGitの識別情報を
外側logへ直接flushし、実行30秒期限に達したSandboxControllerがVMを停止した。
例外理由がexecution timed outであることを検査し、別原因のfenceは成功扱いしない。
続くexecuteは起動前に拒否され、再送logは作られなかった。VM再開はしていない。

- 証拠: `/home/fleet/controller-validation/git-read-timeout-v1/receipt.json`
- receipt SHA256: `29a10e5a33b606d7f4f978e53d494338b5f230eb95ba37e6cd86e731584b6fba`
- blocked.log SHA256: `c37184a2cf2b6fe3a2101606ef29fbf637c1786d6f4e61aa7156aaf54407cfbc`
- container: `a1f9f1389a795ca80e9470ff2099a6df278096f5a46024e24b098e728e5da56d`
- Git PID15/start_ticks279を期限前の外側logで観測。
- timeout_stop_verified、timeout_observed、execution_fenced、retry_rejected_before_spawn、
  all_vms_stoppedを保存後別readで確認。STOP保持、service inactive/dead/MainPID=0。

確認したのは外側VM停止であり、container内の正常cleanup終了ではない。
モデル・実プロジェクトコード・認証VMを使わず、本番turn/fleet復旧の受入には含めない。

### 無料カタログ確認の共通化（2026-09-20）

`model_catalog_policy.require_free_model` は swe-2-high / Free の一意な組合せ、
成功終了、UTC期限、JSON重複キー・非有限定数、入力サイズを検査する。
legacy fleet.catalog_checkにも同じ判定を適用。有料モデルへのfallbackなし。
`sandbox_catalog_probe.check_catalog` は既存GuestRepositoryのleaseだけを使い、
固定CLI models listを20秒または残り期限以内で実行するための部品。
stdout/stderrは合計1MiB以内で私的に読み、外側には判定とdigestだけを返す。
実行・結果検証の失敗はcontroller.stop。実行前の引数・期限・source拒否時は
呼出し元が所有するleaseの退出停止を維持すること。

専用WSLでpure/mock 89件成功（0.200秒）。カタログ15件、probe11件と
既存guest turn/model、sandbox turn/one-turnの回帰を含む。
実CLIカタログ照会・通信許可・モデル起動はこの検証では行っていない。
catalog_verifiedはauthentication_verifiedを意味しない。本番admissionへの
接続、認証の正の証拠、必要通信先の絞込みは未完了。STOP・本番登録は変更なし。

### auth statusを本番必須ゲートから分離（2026-09-20）

machineの通信拒否下の形状診断は13行/rc0、既知見出し7種類すべて0件。
`/home/fleet/controller-validation/auth-shape-tjz5sy22/receipt.json` に保存。
raw出力・アカウント値は返さず、全11VM停止・service inactive/dead/MainPID=0確認。
auth statusの曖昧な表示を追加推測して本番ゲートにすることはやめる。
この診断はauthentication_verified=falseのまま保持する。

本番設計は以下を満たす一回の実呼出しでその時点の利用可否を検証する。

- 同一lease・CLI経路で直前のFreeカタログ、期限、固定モデル、権限、通信範囲を検査。
- 未認証・承認待ち・timeout・export不備は既存停止/fence保持。自動再送・権限拡大なし。
- 終了コードだけでなく、新規export、モデル一致、session identityを検証。
- 成功は当該担当・当該呼出しに限定。他担当や将来の認証成功を意味しない。
- 既知の未ログイン9担当は本人認証待ちとして起動対象から外す。モデル試行をログイン
  代替にせず、認証後も残存fenceを自動解除しない。

既存モデルphaseの一回実行・stale export拒否・停止設計と整合する方針であり、
この変更だけで本番admission実装/本番登録を完了したものではない。
形状診断は後続修正でstdout/stderrを別々に集計するようにした（実機再実行なし）。
pure/mock107件成功（0.205秒）。元の実測は修正前の診断として保持。

### モデルadmissionの接続部（2026-09-20）

`model_turn_admission.make_admission` が登録・担当entry・settingsをコピーして固定し、
一回のturn専用callbackを返す。initial→before_prepare→before_model→before_inspectionを
順番に一度ずつ要求し、どの検査失敗もそのcallbackを閉じる。
現在のmanaged namespace、ロック使用中、entered runtime、登録のディスク照合、
private root、STOP、期限、固定fence bytes、VM UUID/同一leaseを検査する。
ロック使用中のprobeだけで自プロセスの所有は証明できないため、runtimeのentered状態も
要求する。これは信頼済みcontrollerの誤用検査であり敵対プロセスの完全隔離証明ではない。

before_modelでは担当の `guest_permission_config` とstage済みJSONを完全一致で照合し、
prompt digestと同leaseのlive Free catalogを確認する。guest policy生成を共通関数へ
抽出したが、legacy policyは変更していない。

実環境境界・通信policyの検査関数は必須引数で、欠落時の既定許可はない。
関数は成功時None、失敗時raise。Falseを返した検査を成功として無視しない。
その本番検査関数および起動CLIへの接続はまだ未完了であり、本接続部だけでは運転不可。
production登録・STOP・ネットワークは変更していない。
新admission14件・guest policy6件を含むpure/mock回帰127件が専用WSLで成功
（0.214秒）。実runtime/GuestRepositoryとprivate一時registry/fenceを使い、VM通信・
namespace・catalogはmock。実モデルを含む本番一巡の証拠ではない。

### 読取り専用の実効network検査（2026-09-20）

`model_network_admission.check_network` をmodel admissionのnetwork_check引数として
使用できる。initial/before_prepare/before_inspectionはdeny **を要求し、before_modelは
api.devin.ai:443、app.devin.ai:443、server.codeium.com:443の3件だけを許可する構造を要求。
固定kit11接続先からの追加・wildcard許可・未知scopeを拒否し、11接続先と負例5件の
実効policy checkを共有期限内に照合する。前後のルールsemantic digestも一致が必要。
kit表示IDの変化は除外するがeditable IDは保持する。resource配列順の変化も停止側。
sbx policy ls/checkのみで、許可追加/削除やVM実行は行わない。

固定入口 `launch_machine_auth.py --verify-model-network-closed` で現machine閉鎖を実測。
- 証拠 `/home/fleet/controller-validation/model-network-closed-ogkivfkr/receipt.json`
- SHA256 `33790891ed6efe3cc8e8f3a0a56e413c0e754d4207b014d699cdd295e8440c4e`
- 16接続先拒否、ルール前後一致、全11VM停止、network_changed/model_executed=false。
- 保存票を別readで再確認。service inactive/dead/MainPID=0。

15追加を含むpure/mock回帰142件成功（0.243秒）。3接続先限定の開放状態はmockのみで、
今回通信許可を変更していない。ネットワークpacketの能動疎通テストではない。
許可・復元のライフサイクル接続、実VM境界検査、本番一巡、10並列運転は残る。

### 通信windowと復元の工程接続（2026-09-20）

`model_network_window.model_network_window` は既存production runtime・同一active lease・
共通lock下でのみ使えるcontext manager。private新規directoryにnetwork-window.jsonを
書き、closed確認→追加の8接続先deny→既存/新規ルールidentity照合→opening保存→
元のdeny **削除→3接続先限定確認→open保存の順でbodyを許す。
元deny削除がtimeout等で結果不明でもfinallyは必ずdeny **を追加し、閉鎖を照合する。
成功時closed、閉鎖不明時inspection_requiredを保存してVMstop。生の認証情報なし。

run_one_turn/run_guest_model_phaseへ明示的なnetwork_scope引数を追加した。
準備後、before_model admissionと実モデル1回の周囲だけにwindowを置き、閉鎖後に
lease終了と別leaseのinspectionへ進む。scope省略時は通信ルール変更なしであり、
閉鎖中のproduction network checkerはモデル起動を拒否する。

新しいwindow10件と工程接続3件を含むpure/mock155件成功（0.276秒）。
stateful mockの規則を実validate_rules/check_networkで検査し、rm適用後応答喪失、
追加失敗、vendor変化、body例外、閉鎖失敗、STOP/期限、既存directory再利用拒否を確認。
今回は実policy変更やVM/モデル起動はしていない。

残る制約：追加した制限ルールは復元時にも残すため、安全な整理/再利用は別途必要。
bodyの時間制限はモデルcallerが担当する。SIGKILL/電源断ではfinallyが動かないため、
journal走査と閉鎖専用復旧、再開前gate、signal取扱いを接続するまで本番有効化しない。
現登録production=falseとSTOPは維持。実VM境界検査と本番一巡も未完了。

### 再開前の未閉鎖network記録gate（2026-09-20）

`network_restart_guard.inspect_windows` はprivate model-turn-fencesから最大10担当の
固定run/network-window/network-window.jsonのみを検査する。未知entry、壊れたfence、
世代/VM不一致、root外path、symlink、部分JSON、未閉鎖phase、曖昧boolを拒否する。
window保存先も同じfenceで照合するため、別directoryに開放記録を隠せない。

production SandboxRuntime.__enter__で全VM停止確認後・enteredにする前にgateを実行。
closed記録も現実効network checkを通さなければ受け入れない。windowなしは
not_openedとして返すが、role()は別途VMresume前に現在の全通信拒否を要求する。
その検査に失敗したruntimeは再利用不可。maintenance production=falseはこのgateの
代替経路ではなく、引き続き固定保守操作専用である。

実行予約に結びつける4追加、記録gate8件、runtime接続2件を含む関連180pure/mockが
専用WSLで成功（0.304秒）。古いclosed記録で現在の許可を上書きできないこと、
未閉鎖状態のVMresume前拒否を確認。VM/モデル/通信変更は未実行。

閉鎖専用復旧後の独立証拠保存とgateへの接続はまだ未実装。未閉鎖/破損記録は勝手に
closedへ書換えず、STOPやmodel fenceも解除しない。実PC再起動の受入証拠ではない。

### 元記録を保持する通信閉鎖復旧証拠（2026-09-20）

`network_recovery_record` は元fence bytes・元window bytesのSHA256とrole/VM/epoch/
operation identityに結びついた固定schemaを定義する。成功証拠でもautomatic_resume、
model_fence_released、stop_removedはfalse。元windowが部分JSONでも、そのbytesを
保存したまま閉鎖復旧を記録できる。元fenceは有効な登録と照合できることが必要。

restart guardは固定window/recovery/recovery.jsonが存在すると厳密に照合する。
存在する復旧記録が壊れている場合、古いclosed windowへfallbackしない。
一致した証拠もrecovered_closedという閉鎖専用状態であり、現実効network checkを
省略しない。元記録変更・bool偽装・重複JSON・現在の許可は受入拒否。
この照合段階までのpure/mock回帰184件成功（0.301秒）。

`recover_model_network.recover` は専用managed namespace・共通lock・固定production登録で
使用する閉鎖専用API。runtimeは構築だけでenterせず、未閉鎖gateを迂回したVM再開は
行わない。role fenceで指定したwindow/recoveryを排他作成し、pending証拠を先に保存。
全11登録VMの停止確認→当該roleにdeny **だけ追加→実効閉鎖確認→全台停止再確認→
登録/fence/window bytes不変確認の後にclosed_recovery証拠を保存する。
失敗はinspection_requiredで保持し、同じ試行directoryへの自動再送を拒否する。

記録ファイル欠落は空bytesと見なさず拒否。元の空/部分ファイルが実在する場合のみ
hashで結びつける。元journal/STOP/fenceは変更せず、許可追加・ルール削除・VM起動なし。
このAPIを呼ぶ運用CLI、signal取り扱い、実クラッシュ/PC再起動試験は別途必要。
復元API12件を含むpure/mock回帰196件が専用WSLで成功（0.367秒）。
成功証拠を実inspect_windowsがrecovered_closedとして照合できる結合確認も含む。
実ネットワーク復元・production登録変更はしていない。

### 固定復旧CLI接続（2026-09-20）

`launch_machine_auth.py --recover-model-network <固定担当>` を
recover_model_network.py --roleへ接続。ROOTのregistry以外のpath/UUID指定は不可。
managed namespaceのfleetとして実行し、全VM停止確認・service終了は既存launcherが担当。
helperはSIGINT/TERM/HUPをKeyboardInterruptへ渡し、既存handlerをfinallyで復元する。

現在のproduction=falseでmachine入口を実測し、通信操作前に
Explicit production role registration requiredで拒否された。
前後registry SHA256は同一の
`afd5e5f94691c2237cde2219e114fbc66ad95acff57f7be87b0663756874c9bf`。
launcherの全11VM停止確認、別systemctl読取りinactive/dead/MainPID=0を確認。
これは未登録時の拒否試験であり、復旧成功や実クラッシュ耐性の受入ではない。
8追加を含むpure/mock204件成功（0.370秒）。手順はMANAGED_RECOVERY.mdへ追加。

### 実コントローラー子プロセスのSIGKILL（2026-09-20）

test_network_process_crashの2ケースを専用WSLで実行し成功（0.224秒）。
実model_network_windowに、privateファイルへ状態を保存するfake transportを接続。
open保存後、およびrm適用後/open保存前のopeningでreadyを確認し、親が所有する
Popen handleだけをkill/waitした。終了コードは正確に-SIGKILLであることを検査。
実プロセスのfinallyが動かず、模擬policyは3接続先開放のまま残ることを確認した。

実inspect_windowsは未閉鎖記録を拒否。その後、実recover_model_networkをfake
transportで呼び、同じ一時lockの再取得、全拒否、recovered_closed照合、元fence/
window bytesとSTOP保持を確認。全LinuxTransport参照は起動拒否stubに置換し、
本番lock/registry/VM/CLI/通信は触れていない。

これは実プロセス終了とディスク記録の試験だが、ネットワークとVM在庫はmockである。
Docker VM障害、PC再起動、起動中のDevinジョブ復旧を受入済みとはしない。
残作業の整理はPRODUCTION_GATES.mdを参照。
既存204件との結合回帰は206件成功（0.624秒）。本番設定・通信許可は変更なし。

### toolchain担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでtoolchain担当へ個別ログインした。認証状態を他VMからコピーせず、
担当VMだけを対象にした。最初の固定確認2回はモデル実行前のcatalog取得が20秒で
TimeoutExpiredとなったが、いずれもnetwork_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]で閉鎖した。

冷間・認証直後のcatalog取得に備え、machine_cli_smoke.py と保守catalog診断の
上限を20秒から60秒へ変更した。通信許可先、推論90秒上限、モデル、Normal mode、
tool deny、one-shot markerの条件は変更していない。単体8件成功後に専用controllerへ
反映した。

修正後の証拠は
/home/fleet/controller-validation/interactive-auth-fv_0vdoa/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力していない。cleanup後に
管理service停止を報告した。これはtoolchain担当の保守スモーク合格であり、
本番登録有効化や全10担当認証完了を意味しない。

### kernel担当の個別認証・再認証・固定SWE-2確認（2026-09-20）

kernel担当の初回login receiptはlogin_exit_code=0、terminal_recorded=false、
network_denied_after=true、all_vms_stopped=true、cleanup_errors=[]だった。
ただし固定確認は2回とも60秒のcatalog段階でTimeoutExpiredとなり、model_executed=false。
各回ともcleanupを完了し、追加のclosed-network log診断ではTLS/DNS/proxy/auth拒否、
401/403、entitlement、quota、connection errorの検出は0だった。

同じ確認を繰り返さず、可視Windows Terminalでkernelだけを再認証した。再認証receiptは
/home/fleet/controller-validation/interactive-auth-6om6l_94/receipt.json、
login_exit_code=0、通信再遮断・全VM停止・cleanup errorなし。

再認証後の固定確認証拠は
/home/fleet/controller-validation/interactive-auth-2d5v4432/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはkernel担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### assurance担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでassurance担当へ個別ログインした。認証状態のコピーは行わず、
login receiptは
/home/fleet/controller-validation/interactive-auth-0fb3h9mr/receipt.json。
login_exit_code=0、terminal_recorded=false、network_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]を確認した。

offline auth分類はreturncode=0、status=unclassifiedであり、これ単独を認証成功の
根拠にはしない。固定確認証拠は
/home/fleet/controller-validation/interactive-auth-b0yw92dx/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これで固定10担当すべてに個別の
fixed SWE-2 maintenance smoke成功証拠が揃った。本番readinessへの厳密な証拠接続、
normal permission turn、本番一巡、実PC再起動受入は別ゲートである。

### devtools担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでdevtools担当へ個別ログインした。認証状態のコピーは行わず、
login receiptは
/home/fleet/controller-validation/interactive-auth-c0ysvo0q/receipt.json。
login_exit_code=0、terminal_recorded=false、network_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]を確認した。

offline auth分類はreturncode=0、status=unclassifiedであり、これ単独を認証成功の
根拠にはしない。固定確認証拠は
/home/fleet/controller-validation/interactive-auth-_1b6_q4a/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはdevtools担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### applications担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでapplications担当へ個別ログインした。認証状態のコピーは行わず、
login receiptは
/home/fleet/controller-validation/interactive-auth-s9rdj3y5/receipt.json。
login_exit_code=0、terminal_recorded=false、network_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]を確認した。

offline auth分類はreturncode=0、status=unclassifiedであり、これ単独を認証成功の
根拠にはしない。固定確認証拠は
/home/fleet/controller-validation/interactive-auth-5kh5xet3/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはapplications担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### services担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでservices担当へ個別ログインした。認証状態のコピーは行わず、
login receiptは
/home/fleet/controller-validation/interactive-auth-pvug8fm3/receipt.json。
login_exit_code=0、terminal_recorded=false、network_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]を確認した。

offline auth分類はreturncode=0、status=unclassifiedであり、これ単独を認証成功の
根拠にはしない。固定確認証拠は
/home/fleet/controller-validation/interactive-auth-hal_pb83/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはservices担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### storage担当の個別認証・再確認・固定SWE-2確認（2026-09-20）

storage担当の初回login receiptはlogin_exit_code=0、terminal_recorded=false、
network_denied_after=true、all_vms_stopped=true、cleanup_errors=[]だった。
固定確認は2回ともモデル実行前の60秒catalog段階でTimeoutExpiredとなり、
各回とも通信再遮断・全VM停止・管理service停止を完了した。

可視Windows Terminalでstorageだけの認証を再確認したところ、CLIは既にログイン済みと
表示して正常終了した。receiptは
/home/fleet/controller-validation/interactive-auth-o2c18z1i/receipt.json、
login_exit_code=0、通信再遮断・全VM停止・cleanup errorなし。

その後の固定確認証拠は
/home/fleet/controller-validation/interactive-auth-ey2tj5ma/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはstorage担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### stdlib担当の個別認証・固定SWE-2確認（2026-09-20）

可視Windows Terminalでstdlib担当へ個別ログインした。認証状態のコピーは行わず、
login receiptは
/home/fleet/controller-validation/interactive-auth-i7hq_18q/receipt.json。
login_exit_code=0、terminal_recorded=false、network_denied_after=true、
all_vms_stopped=true、cleanup_errors=[]を確認した。

offline auth分類はreturncode=0、status=unclassifiedであり、これ単独を認証成功の
根拠にはしない。固定確認証拠は
/home/fleet/controller-validation/interactive-auth-x9swufrp/receipt.json。
returncode=0、response_marker_seen=true、exact_model_verified=true、
no_tool_calls=true、passed=true。raw outputは保存・出力せず、終了後に通信再遮断、
全VM停止、管理service停止を完了した。これはstdlib担当単独の保守スモーク合格であり、
本番登録有効化や全担当認証完了を意味しない。

### candidate-bound認証・Normal権限readiness（2026-09-20）

全10担当の実receiptを文書記述ではなくraw bytesから再検証し、
production-role-authentication-v1/manifest.jsonへ一回限りで束縛した。
candidate SHA256は
7721e6c83db493406ea71a3e0e965d4cdc287a13aa1679dbe67d3259d75fb682、
migration epochは3f30015c-e26b-4b09-b741-dc59c1d0769c、
manifest SHA256は
93c9563900cb5d3159816dca577468e9e7c1b5e69695476231e42d3a03d75e3c。

coordinator/toolchain/kernel/stdlib/storage/services/applications/devtools/assuranceの9担当は
fixed_smoke_receipt。machineは既存one-shot markerが再実行をFileExistsErrorで拒否したため
削除せず、保存済みexportを保守検査し、SWE-2 High、agent step 1、exact model、
no tool calls、export SHA256を再確認したlegacy_export_attestationとして明示的に区別した。
旧証拠には現行receiptのreturncode/response markerがないため、同強度とは主張しない。

Normal modeの単一write実測receiptと独立inspection receiptも
production-normal-permission-v1/manifest.jsonへcandidate/epoch/machine ID/name/imageへ束縛。
tool call 1、expected write 1、file write verified、production_admitted=false。
manifest SHA256は
5cd9b266979722534111ea7ace91c89149c6d98f3d4216005743305fda828a8e。

新規aggregate/readiness対象テスト9件成功。実readinessで10担当すべて
network_denied=true、host_boundary_verified=true、all_vms_stopped=true。
role_authentication.verified=true、normal_permission_turn.verified=true。
active registryは変更せずactivated=false、activation_ready=false。
残るblockerはfull_turn_not_verifiedとunexpected_reboot_recovery_not_verifiedの2つ。
Fable最新はhistorical preflightのnot_runであり、外部監査合格ではない。
