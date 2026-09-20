# MCP拒否の単発受入試験

## Params互換版の実機正常経路成功（2026-09-20）

params専用lifecycle/entryと管理launcherのprepare/inspect/onceを接続。
controller回帰491件（6.010秒）と追加入口3件（0.003秒）が成功。
実機準備mcp-prepare-n5zsbomp、独立再検査mcp-prepared-state-_c_0dvpzとも
9入力・未実行を確認、通信変更なし、全VM停止・管理service停止で終了した。

単発実行: /home/fleet/controller-validation/mcp-params-control-lifecycle-_ccj1_tp
phase=complete、returncode=0、timed_out=false、exact_model_verified=true。
controlはcalls=2/results=2、exact_requests/linked_results/sequence/schema=true、
marker=true、linked_success=true、audit_call_count=1、audit_call_after_list=true、
consistent=true。新版で初めて正常echo応答が監査記録と一致した。
この結果だけで旧失敗の実要求や原因を断定しない。拒否ルール検証は別問題。

nonce=4855a11afbc8f430798dbae562742a08
work=/tmp/e-base-mcp-probe-ayf9y9an
reservation_sha256=cc8d9dc936d2e4f94606b5c4edb5440bd23ccf33c3eb7d1a79f453ef8cff3b92
export_sha256=6f10381c369df5ffb8a54f7006563999d710c9f5e64545b3a1b2930b81ff3293
audit_sha256=e8f3629d04569e0dccb6b9ff369517d8770ce59f3d97b5cfb5b1229a89d82331
supervision_sha256=34efbe3d9255a457c6ebdea4bb8cae9ab0de1739a300a80a9eaa6518d38a0109
stop_receipt_sha256=7c9ada0c91223f0c8d2cbd99d4b47bfe9cb71111d0eb84f302857adfd332c9cd

all_vms_stopped=true、inspection_vm_stopped=true、managed service停止、exit=0。
mcp-echo-params-live-v1/network-window/network-window.jsonの閉鎖記録は
phase=closed/network_denied_after=true/automatic_resume=false。この予約は消費済みで再利用禁止。
passed/permission_denial_accepted/production_admittedは意図どおりfalse。
binding内のexpected_call_observed=falseは旧拒否用判定で、正常controlの成否は
上記control証拠で評価する。Fableはhistorical not_run。10並列/常時運用や実再起動、
拒否ルールの最終受入は依然未達であり、この成功を本番許可に読み替えない。

## Params互換版の通信予約と再起動ゲート（2026-09-20）

独立したmcp-echo-params-live-v1通信予約を追加。既存予約を保持したままrestart検査へ
追加し、固定machine・capacity=1・非本番・global lock・最大300秒の既存制約を継承。
許可先は既存catalog_access範囲のままで、任意接続先や本番通信には拡張していない。
実通信や新予約作成は未実施。実行lifecycleとlauncherの接続は次の作業。

信頼済み合成controller回帰486件成功（6.053秒、network suiteは探索条件で重複）。
新版の正常終了/再入拒否、例外時と期限切れの拒否復元、本番モードの予約前拒否、
部分予約によるrestart停止を検証。旧予約を含む全13パスの検査順も確認。
独立レビューを反映し、テストから実予約を読まないよう新版定数も一時パスへ置換。
Fable取得結果はhistorical not_runであり監査合格ではない。実PC再起動の受入証拠ではない。

## Params互換版のguest状態分離（2026-09-20）

guest_mcp_prepare/inspect/wildcardへ独立PARAMS_CONTROL_STATE
(/home/agent/.local/state/e-base-mcp-echo-params-v1)と専用準備/検査/実行bootstrapを追加。
prepare.STATEは依存moduleのimport前に束縛する。収集2箇所も同じ状態を参照し、
結果は既存controlの厳格な証拠schemaを使用する。compatibleとparamsの同時指定や
非bool、sequenceなしは拒否する。旧stateの定数と旧入力builderは変更していない。

専用WSL内の信頼済みcontroller回帰477件成功（5.829秒）。新規5件で固定stateの
独立性、builder必須とサイズ、検査先、bootstrap束縛順序/収集先、曖昧な指定の拒否を確認。
既存fresh-process試験へparams版を追加し、正常、旧入力、入力改変、hold欠落、
launch存在、再入の6条件を実ファイルで検証した（合成データ、CLI/モデル/通信なし）。
独立レビューでimport時のSTATE固定を確認。Fable最新取得はhistorical not_run。
実機の新state作成・network予約・launcher入口は未実施で、本番許可ではない。

## Params互換版の独立入力生成（2026-09-20）

mcp_params_control_sourceを追加し、controller所有のcontrol/ID adapter/params adapter
の3ソースから独立した入力builderを構成。固定importの一意性を検証して除去し、
隔離moduleのid_inputsへ供給済みadapterを束縛する。guest側の同名moduleは読み込まず、
sys.modulesも変更しない。各ソースと合成結果は16KiB以内に制限しcompileする。
既存mcp_compatible_control_sourceと消費済みprofileは変更していない。

専用WSL内の信頼済みcontroller回帰472件成功（5.655秒）。新規4件では独立した
準備/再検査の入力一致、2入口の一致、fixture/runnerだけの変更と新hashの一意性、
同名module遮断、依存importの欠落/重複、サイズ上限を検証した。
初回のテストデータは既存の非空server制約に違反したため修正して再実行した。
サブエージェントの読み取りレビューで阻害事項なし。Fable最新取得は過去のnot_runで、
外部監査合格ではない。今回の作業でモデル実行・通信開放・実行profile追加はしていない。
新版のlive検証には独立した未消費state/network予約と入口の実装・検証が必要。

## 標準tools/call envelopeの互換性修正（2026-09-20）

公式MCP2025-11-25 schemaでCallToolRequestParams.argumentsはoptional、
RequestParams._metaもoptionalであることを確認:
https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2025-11-25/schema.ts
既存ID互換版は引数省略や_meta付きの有効なecho要求も-32602にすることを合成再現。
保存ログの実要求がこれだったとは未確認であり、根本原因とは断定しない。

mcp_fixture_paramsを別版adapterとして追加。name=echo、arguments省略または空dict、
optional _meta dictのみ許可。metadataはASCII JSON化で1024bytes以内、非有限数や
serialization失敗は拒否。値は返答・監査に反射しない。
非空/非dict引数、null metadata、未知key/task、別toolは引き続き拒否。
元ID互換adapterを適用後、paramsガードとrunnerのfixture digestだけを更新する。
旧fixture/旧profile/保存証跡/権限設定は不変。

省略引数・progress metadataの成功、無効値拒否、ping継続、旧入力保全を検証。
統合468 tests成功（5.617秒）。並行review実施、Fable latestは過去not_runのみ。
新adapterは実試行へ未接続、VM/モデル/通信窓は今回未実行。

## 固定項目によるJSONログ分類（2026-09-20）

compatible_log_summaryへ固定JSON項目message/msg/code/methodの分類を追加。
fixture文字列を含む64KiB以内の行だけをparseし、重複keyを拒否。
fields/error/cause/dataだけ深さ4・node64以内で走査し、任意項目値は返さない。
source文字列だけの一致、非JSON、重複JSONを分離。関連14 tests成功（0.029秒）。
並行reviewで入力/出力制限を確認。同じイベントの別node間の共起に留まり、
request同一性は未証明。Fable latestは過去のnot_runのみ。

実証跡: /home/fleet/controller-validation/compatible-log-inspection-hh4o4a1r。
5候補log、fixture_error=4。該当する2物理行はnonjsonとして分類され、
event_fixture_error/event_invalid_params/event各methodは全て0。
JSONイベント項目からの帰属は得られなかった。次の対象は該当テキスト行の形式。
原ログを変更せず、今回も閉域・CLIなし・モデルなし・全VM停止・service停止・exit0。

## 保存ログの同一行エラー文脈（2026-09-20）

compatible_log_summaryへ固定エラーと同じ物理行の-32602/server/method/_meta/
source文字列の有限件数を追加。両markerは行先頭2048bytes以内に限る。
長行の陰性は網羅的でなく、sourceの文字列化でも陽性になることをテスト。
関連テスト12件成功。Fable latestは過去not_runのみ、監査合格ではない。

実証跡: /home/fleet/controller-validation/compatible-log-inspection-z9wmapfs。
候補5ログ。fixture_error=4、同一行invalid_params=2、fixture_name=2。
tool_call/resource_list/prompt_list/metadata/source_codeの同一行一致は0。
これらは独立した共起件数で、同じ2行なのかも証明していない。
echo引数/metadataが原因とはまだ断定しない。次はstructured event/error項目を
有限に分類し、語彙追加やモデル再実行で代替しない。
閉域/モデルなし/CLIなし、全VM停止・管理service停止・exit0。

## 修正版試行時刻の保存ログ検査（2026-09-20）

g6_x4mr7/admission.jsonのissued_at=1789898172 / expires_at=1789898352を読み取り、
compatible_log_summaryで固定mtime区間に設定。--inspect-compatible-logsを追加。
既存bounded stable readerを再利用し、固定17分類の件数のみ返す。本文・名前は非公開。
nofollow/owner/mode/link/サイズ上限/読取前後一致検査は維持。
mtimeでwhole fileを選ぶためattempt_bound=falseを維持。read_completeは選択ファイルの
読取完了であり全試行の網羅ではない。後で更新されたログは対象外になり得る。
回帰460 tests成功（5.719秒、既存catalog log7件も含む）。並行reviewで境界確認。
Fable latestは過去のnot_runのみ、監査合格ではない。

実証跡: /home/fleet/controller-validation/compatible-log-inspection-46_ix0qc。
candidate_count=5、fixture_error(Unsupported fixed probe request)=4、
connect_failure=1、fixture_name=30。ID/protocol/input/audit固定例外、traceback、
broken pipe、unicode/json/value例外、connection closed、exit/signal/timeoutは0。
外側exportに無かったfixture入力拒否がログ中で観測され、params形式の切り分けが次。
時刻絞り込みのみなので4件の呼出し帰属や実引数はまだ証明していない。
phase=closed/all_vms_stopped=true/network_denied=true、通信変更・CLI・モデル実行なし。
管理service停止出力、全体exit0。追加のモデル試行や権限緩和は行っていない。

## 修正版保存証跡の閉域診断（2026-09-20）

--inspect-compatible-resultを追加し、g6_x4mr7の固定export/audit hashと
停止receiptに束縛して専用compatible bootstrapで回収する。旧control経路は保持。
統合450 tests成功（5.720秒）、型guard/語彙追加後の関連19 tests成功（0.015秒）。
Fable latestは過去のnot_runのみ、監査合格ではない。

閉域証跡: compatible-result-inspection-q0bitv2x、および技術語彙拡張後の
compatible-result-inspection-0rgnthy1（双方/home/fleet/controller-validation配下）。
両方で一意なlinked resultを確認し、fixture固定入力拒否文字列/ -32602 /
成功marker/サーバー承認要求の完全一致はいずれもfalse。
応答projectionはfailed to connect to mcp server fleet-probe。末尾の未知3語は
技術語彙拡張でも特定できず、追加の具体的な原因を得ていない。
init2/list1/call2の監査は同じ。phase=closed/all_vms_stopped=true/network_denied=true、
CLIなし/モデルなし/通信変更なし、service停止・exit0。

別agentのコード点検: calledは応答生成前であり、ID/JSON/encoding/stdout/監査I/O/
クライアント切断を区別できない。5イベントは監査容量4096bytesより十分小さい。
runnerのsource/inode/openはcalled到達前に成功している。params不一致は
通常の-32602応答であって単独ではプロセス終了を説明しない。
CLI生stderrは保存されないため、次はCLI保存logに固定エラーが残るかを
対象時刻を限定して確認する。新たなモデル試行は行っていない。

## ID互換修正版の単発実試行: 成功未確認（2026-09-20）

証跡: /home/fleet/controller-validation/mcp-compatible-control-lifecycle-g6_x4mr7。
phase=complete、process rc0/timed_out=false、exact_model_verified=true。
nonce=f005232dfc2d8af0f3ffb541a847369e、work=/tmp/e-base-mcp-probe-r86e47ty。
reservation_sha256=9a3faddf7f38a967eecf2e69f2043e1778bf8b8cb79bafc2101eb999db0ee9e4。
export_sha256=cedd34e3c628db5d6982d97991e8d2103d0e37d8303852c99c6f406283d5c02f。
audit_sha256=3a0b8052a48b4810cd03b2a6ee22446a75ef3de298022e4eeeafa59275da6fba。
同一exportの2calls/2results、対象・リンク・順序・一覧schema・nonce一致。
audit_call_count=2、execution_marker_observed=false、linked_success_observed=false、
consistent=false。文字列ID互換修正だけでは成功に至らず、元障害の原因と断定しない。
修正版の保存応答と終了原因の閉域診断が次の作業。追加の権限緩和・再試行なし。

all_vms_stopped=true/inspection_vm_stopped=true、service停止出力・全体exit0。
passed/permission_denial_accepted/production_admitted=falseのまま。
通信journalはclosed/network_denied_after=true/automatic_resume=false。
serviceは独立確認でもinactive/dead/MainPID=0。専用v1は消費済みとして保全。

## 修正版管理入口と閉域実VM準備（2026-09-20）

--prepare-mcp-compatible / --inspect-mcp-compatible / --mcp-compatible-onceを登録。
専用entryは--onceのみ、固定registry/namespace/中断cleanupを使用。
prepare/inspectのモード混在はnamespace前に拒否、lifecycleと同じ2sourceを合成。
448 tests成功（5.456秒）、別agent静的reviewでblockerなし。
Fable latestは過去not_runで監査合格ではない。

閉域準備: /home/fleet/controller-validation/mcp-prepare-ker6qoxx。
閉域検査: /home/fleet/controller-validation/mcp-prepared-state-nmos1gpq。
9入力、prepared_state_verified=true/prepare_only_retained=true/launch_absent=true。
両方network_changed=false/model_executed=false/all_vms_stopped=true、service停止・exit0。
未実行状態は検査時点のみ。後続単発試験後にはこの状態を流用しない。

## 修正fixture専用の通信予約・外側実行処理（2026-09-20）

COMPATIBLE_CONTROL_RUN=mcp-echo-compatible-live-v1と固定WINDOWを追加。
既存11予約を保持し、12個全てをrestart guardで確認する。
単一machine lease/lock/非本番/期限付き固定4宛先の共通検査を使用。
通常終了・例外時の遮断復元、再入拒否、部分記録のrestart拒否を合成検証。
本番通信の許可先は変更なし。

mcp_compatible_control_lifecycleは固定control+compat sourceを合成し、
compatible bootstrapと専用log/prefixへ接続。既存collectionを維持し、
通信閉鎖→モデルVM停止→別lease回収→検査VM停止を共有する。
実sourceのcompileと3stage引数、失敗時停止・stop hash拒否をテスト。
統合445 tests成功（5.567秒）。Fable latestは過去のnot_runのみ。
実通信窓・モデル実行は未実施。管理launcher入口と実VM準備は残作業。

## 修正fixture専用guest stateと回収接続（2026-09-20）

COMPATIBLE_CONTROL_STATE=/home/agent/.local/state/e-base-mcp-echo-compatible-v1を追加。
既存CONTROL_STATE=v2/旧stateと分離し、明示builderを必須とする。
inspect_compatible_controlは既存の全入力再構築/claim/inode/hold検査を共有。
make_compatible_control_probeはsupport import前に専用STATEを設定し、
検査先とCOLLECTの両state参照を同じ専用stateへ接続する。
既存make_control_probe・v2診断経路は変更なし。結果keyはcontrolを維持。

実sourceの合成・compile・固定state・既存経路保持テストを追加。
実ファイルの6ケース検査も専用state経由に変更し、435 tests成功（5.503秒）。
並行reviewでimport前state束縛と回収2箇所の一致を確認。
Fable latestは過去のnot_runで今回の監査合格ではない。
管理入口/専用通信予約/外側lifecycleへの接続、実VM準備・モデル実試行は未実施。

## 修正fixtureの入力生成・再構築契約（2026-09-20）

mcp_compatible_control_source.composeを追加。control/compatのtrusted sourceを
別module namespaceに読み込み、make_input_builder/build_inputsの双方へ同じ
fixture+runner変換を適用する。合成後もUTF-8 16KiB以内、compile可能であることを要求。
生成時にsourceを実行せず、文字列literalを再走査・再置換しない。
入力9個のうちfixture.pyとrunner.pyだけが変わり、権限/prompt/継承server無効化は不変。
元ビルダーと既存CONTROL_STATE/試行入口は変更していない。

初回はテストに既存overrides契約外の空設定を用いて1件失敗。
非空の無効化対象serverを持つ合成設定に直し、検証条件自体は緩めていない。
一時実ファイル検査をcompatible_controlにも拡張し、正常/旧profile混入/入力変更/
hold欠落/launch混入/再準備拒否を確認。432 tests成功（5.633秒）。
これは管理コードの合成検証であり、実VMの新試行準備・モデル実行は未実施。
並行reviewにより消費済みv2へ接続しない境界を再確認。
Fable latestは過去のnot_runで今回の監査合格ではない。
次は独立固定state/通信予約/回収経路へ同じ合成sourceを接続する。

## Fixture要求IDの互換性不具合を再現・別版修正（2026-09-20）

公式MCP 2025-11-25 schemaのRequestIdはstring | number:
https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2025-11-25/schema.ts
元fixtureは非負intのみ許可し、文字列IDのtools/callでcalled記録後にValueError終了。
initialize/listの数値ID→callの文字列ID→pingという合成系列で再現。
応答は最初の2個のみ、成功markerなし、called監査だけ残る。
実v2の要求IDは記録していないため、これが実障害の原因とまでは断定しない。

mcp_fixture_compat.compatible_sourceは元ソースの一意な固定IDガードだけを変換。
128 UTF-8 bytes以内のstrまたは符号付きsafe intを受け付け同じIDで返答する。
bool/null/float/範囲外は拒否、ツール名・引数・metadataの厳密条件は変更なし。
新fixtureではプロトコルIDだけ反射する例外がある。ツール引数は反射しない。
adapt_inputsはfixture.pyとrunner.py内の対応SHA256のみ変更し、旧入力を変更しない。
hash不一致/重複、source driftは拒否。元fixture・既存予約・保存証跡は不変。

合成検証で文字列/空文字/日本語/符号付き境界ID、応答後のping継続、
不正ID/引数拒否、元入力不変を確認。統合428 tests成功（5.178秒）。
並行reviewを実施。Fable latestは過去のnot_runのみ、監査合格ではない。
修正版はまだ実試行profileへ接続していない。モデル/VM起動/通信窓は今回未実行。

## Echo対照v2の閉域失敗診断（2026-09-20）

--inspect-control-resultを追加。固定r2urx45pのexport/audit SHAと停止receiptを
照合し、既存collectのみで再回収。CLI/モデル/通信窓は実行しない。
固定対象の一意なlinked resultから4つのboolean指標だけを抽出する。
権限受入・本番昇格flagsはfalseのまま。回帰421 tests成功（5.240秒）。
Fable latestは過去のnot_run、今回の監査合格ではない。

閉域証跡: /home/fleet/controller-validation/control-result-inspection-grrctvfk。
unique_linked_result=true、fixture_error_literal_present=false、
invalid_params_code_present=false、marker_present=false。
監査initialized=2/listed=1/called=2。固定語彙応答は接続失敗を示すが、
fixtureのUnsupported fixed probe requestや-32602は観測されなかった。
余分なparamsの仮説は未確認。CLI再接続/fixture終了などの切り分けが必要。
元export/auditの変更なし、phase=closed、all_vms_stopped=true、network_denied=true、
cli_executed=false/model_executed=false、管理service停止・exit0。

固定接続語彙を追加後の再読証跡:
/home/fleet/controller-validation/control-result-inspection-wafoodim。
応答projectionはfailed to connect to mcp server fleet-probeを確認。
後続の未許可語は伏せたままであり、具体的な切断原因は未確定。
関連17 tests成功。再読も閉域/CLIなし/モデルなし/全VM停止・service停止・exit0。

## Echo許可対照v2の実試行: 要求到達・成功未確認（2026-09-20）

証跡: /home/fleet/controller-validation/mcp-echo-control-lifecycle-r2urx45p。
phase=complete、rc0、timed_out=false、exact_model_verified=true。
nonce=844f82736d51bd9b6fbffd05cf3ca5e2、work=/tmp/e-base-mcp-probe-t2k48cly。
reservation_sha256=d9c1d66546f1afa64489bf5f4a460390ba707b90c8fc2a7eb576a9ae3f79ebbd。
export_sha256=f85a9dcfbb1b2b2815143e44ea154b317c287d37567591af58a93d750254e180。
audit_sha256=e8e2f8c71883ef0a7ea8f1c961e1040090c152ddca73f688a614f33acb0582f1。
同一export内tool_calls=2 / observations=2、対象・リンク・順序・一覧schemaは一致。
監査nonce一致、audit_call_count=2、execution_marker_observed=false、
linked_success_observed=false、consistent=false。fixtureのcalledは不正形式を含む
tools/call到達時にも記録されるため、2回のecho成功とは解釈しない。
audit_call_after_list=falseも「ちょうど1回」を含む複合条件であり、逆順の証明ではない。
呼出し形式/CLI再試行の可能性は仮説。閉域で既存証跡の有限診断が次の作業。

all_vms_stopped=true / inspection_vm_stopped=true、service停止出力・全体exit0。
passed/permission_denial_accepted/production_admittedは全てfalse。
通信journalはclosed/network_denied_after=true/automatic_resume=false、
serviceは別途inactive/dead/MainPID=0を確認。v2は消費済み、再実行しない。

## Echo許可対照v2の独立準備（2026-09-20）

v1はcatalog期限切れで消費済みとして保持。別診断v5の成功を受け、
CONTROL_STATE=echo-control-v2 / CONTROL_RUN=echo-control-live-v2へ切替。
PREVIOUS_CONTROL_RUNをrestart guardへ保持し、旧guest stateへのprepareを明示拒否。
旧予約・証跡の削除、再開、上書きなし。権限・prompt・宛先・時間制限は不変。
415 tests成功（5.149秒）。並行reviewで旧state呼出し拒否を補強。
Fable latestは過去のnot_runのみ、監査合格ではない。

閉域準備証跡: /home/fleet/controller-validation/mcp-prepare-echxxgi5。
閉域照合証跡: /home/fleet/controller-validation/mcp-prepared-state-p2ncq3h1。
9入力、prepare_only_retained=true、launch_absent=trueを確認。
両方model_executed=false/network_changed=false/all_vms_stopped=true、
service停止・exit0。未実行状態はこの照合時点のみであり後続試行後に流用しない。

## Catalog診断v5: 到達性とCLI取得の分離（2026-09-20）

前回echo controlの無出力timeoutだけではDNS/TLS/HTTP/CLI内部処理を識別できない。
コード比較でcontrol固有の宛先欠落は未発見。新catalog_endpoint_probeは固定4hostへ
認証なしHEAD /を各6秒、隔離Python子プロセスで一度ずつ実施する。
TLS検証有効、proxy/redirect/cookie/認証headerなし、本文は読まず、
host/status/有限error_classだけを返す。HTTP応答は認証・モデル受入の証明ではない。
その後CLIの無料catalog検証を従来どおり60秒以内で行う。モデル実行なし。
全体guest140秒/通信180秒の有限枠。timeoutやcatalog拒否でも到達性結果を残す。

固定予約catalog-diagnostic-v5へ更新。v4はFOURTH_CATALOG_RUNとして残し、
全10保守予約をrestart guardで検査する。旧予約の削除・再利用なし。
回帰413 tests成功（5.229秒）。endpointの5 testsはmock、実通信の証拠ではない。
Fable latestは以前のnot_runのみで、今回の監査合格ではない。

実診断証跡: /home/fleet/controller-validation/catalog-diagnostic-evidence-urban4ln。
phase=closed / catalog_verified=true / swe-2-high=Free、catalog SHA256:
557b46c4ed35a51067026a87cc990fc6bd3fb40bb3cbfd517b17c23b57f8f4e4。
HEAD /応答はapi.devin.ai=404、app.devin.ai=200、server.codeium.com=404、
unleash.codeium.com=404。全てTLS検証付きHTTP応答、error_class=null。
root pathの404は到達性の観測でありAPI動作の不合格ではない。
model_executed=false / production_admitted=false、all_vms_stopped=true、
network_denied=true、管理service停止出力、全体exit0。
前回のtimeoutが一過性か設定依存かは未特定。今回catalog診断はfixtureを無効化し、
直前にHEAD通信も行うため、control起動と同条件の成功証明ではない。
v5は消費済みとして保持する。次の許可対照には新しい独立予約が必要。

## 許可対照v1の単発試行: catalog期限切れ（2026-09-20）

--mcp-control-onceを一度実行。証跡:
/home/fleet/controller-validation/mcp-echo-control-lifecycle-dij13d8x。
nonce=cb5c0dd79ae6b9b7f3e709b2cade4195、work=/tmp/e-base-mcp-probe-hqyfesqk、
reservation_sha256=4a5e4389aca3adeebe42cb851f2ebdad859ef121c8e2e27a706be6d4eba0c84b。
receiptはdispatchingで停止し、passed/production_admitted/permission_denial_accepted=false。
管理ログoperations/8146be6f811146dca9f41e32104ebb61/logs/echo-control-dispatch.log:
read_catalogでCaptureDeadline、leader_exited=false、stdout/stderrとも0 bytes。
コード上のmodel spawnより前で失敗。echo許可挙動の観測は得られていない。
タイムアウト原因の接続先/認証/CLI内部処理の切り分けは未完了。

launcherは全11VM停止を確認後、service停止完了を出力。全体exit1は子の失敗。
別途systemctlでinactive/dead/MainPID=0を確認。
mcp-echo-control-live-v1/network-window/network-window.jsonはclosed、
network_denied_after=true、automatic_resume=false。
古いreceiptのall_vms_stopped=falseは成功回収に到達しなかったことを示すため
書き換えず保持。後処理の停止証跡と区別する。
監督予約・通信予約は消費済みとして保持し、同じv1を再試行しない。
無料catalog確認の迂回・時間制限撤廃・有料fallback・本番昇格は行っていない。

## 許可対照の管理入口・閉域準備検査（2026-09-20）

launcherへ--prepare-mcp-control / --inspect-mcp-control / --mcp-control-onceを
登録。実行入口は--onceのみ、固定registry・managed namespace・中断cleanupを使用。
準備/検査はcontrolと他profileの混在を拒否し、固定builderのみを渡す。
統合406 tests成功（5.470秒）。別agentの静的reviewで具体的blockerなし。
Fable latestは過去のnot_runであり、今回の監査合格ではない。

実VMの閉域準備: /home/fleet/controller-validation/mcp-prepare-9zd10sk3。
prepared=true / input_count=9 / model_executed=false / network_changed=false。
閉域検査: /home/fleet/controller-validation/mcp-prepared-state-k7cafuqa。
prepared_state_verified=true / prepare_only_retained=true / launch_absent=true、
9入力照合済み。両操作ともall_vms_stopped=true、管理service停止・終了code0。
この未実行状態は準備検査時点の証跡であり、後続単発実行後には適用しない。

## 許可対照の通信予約・外側lifecycle（2026-09-20）

CONTROL_RUN=mcp-echo-control-live-v1 / CONTROL_WINDOWを追加し、非本番machineの
固定単一lease/lock/期限付き4宛先窓へ接続。既存8予約を保持して再起動guardに
9番目として追加。部分記録は起動拒否、終了/例外で遮断復元、再入は拒否する。
本番経路とhost集合は不変。
mcp_echo_control_lifecycle.run_controlを追加。固定5source、専用log/prefix、
control collectionを共通_run_probeへ接続し、通信閉鎖→モデルVM停止→回収→
検査VM停止の順序を維持する。dispatch失敗とstop hash不一致時の停止を模擬確認。

初回テストでは追加時に既存assertを別関数へ移したスコープ誤りが発生し修正。
統合後403 tests成功（5.270秒）。実通信窓・モデルは未実行。
管理launcherの準備/検査/単発入口への登録と実VMでの準備はまだ未完了。

## 許可対照のguest bootstrap接続（2026-09-20）

guest_mcp_wildcardの旧make_probeを維持してmake_control_probeを追加。
固定CONTROL_STATE/inspect_control/control envelopeを選び、source5個は各16KiB上限。
STATEはsupport import前に設定し、回収時は既存の全入力・停止・監督・snapshot
照合を維持する。依存はdiscovery→result summary→wildcard sequence→control evidence。
sourceはテンプレート変換後に一括埋込みし、埋込み文字列を再置換しない。
実source生成・固定state・依存順序・source境界・placeholder保存を含め395 tests成功
（5.207秒）。対照の管理入口/通信予約は未接続、実VM準備・モデル試行は未実施。

## 許可対照専用stateと実準備検査（2026-09-20）

CONTROL_STATE=/home/agent/.local/state/e-base-mcp-echo-control-v1を追加し、
旧maintenance/discovery/wildcardと分離。明示trusted builderを必須とし、
inspect_controlは既存の全入力再構築・claim/inode/継承設定/hold照合を共有。
実ファイルテストを3profile×6ケースへ拡張し、echo_controlでも正常準備、
旧profile混入、入力変更、hold削除、launch混入、再準備拒否を確認。
関連385 tests成功（5.154秒）。一時ディレクトリの合成検証であり、
実machine guestのcontrol stateは未作成、モデル/通信窓は未実行。

並行実装のmcp_echo_control_collectionを確認・統合。
固定binding/control envelope、外側停止/監督/nonce/lease照合を先に要求し、
件数・モデル・実行markerの二重分類一致と成功整合条件を再計算する。
受入4flagsは常にfalse。実_collectionを使う改ざん拒否等7 tests成功。
guest bootstrapと管理実行入口への接続はまだ未完了。

## 許可対照の成功候補判定（2026-09-20）

mcp_echo_control_evidenceを追加。既存の同一export順序/固定対象/ID照合を共有し、
唯一の対応結果が固定markerそのもの、または厳密MCP content/isError=false形式に
一致する場合だけ成功応答候補とする。agent本文やmarkerを含む任意文章は不可。
同nonce監査でcalledがちょうど1件かつlisted後であることも要求。
未知の実CLI応答形式は推測で通さず、passed/production_admitted/
matched_rule_verified/permission_denial_acceptedはfalseのまま。
関連380 tests成功（4.737秒）。独立レビューで必須修正なし。
誤nonce・曖昧JSON・余分な結果の直接テストも追加。live接続・実対照試行は未実施。

## 固定echo許可対照の入力生成（2026-09-20）

mcp_echo_control_inputsを追加（offline、実行入口には未接続）。
基底DENYからmcp_list_tools/mcp_call_tool/mcp__*だけ除き、allowは
mcp_list_tools/mcp_call_tool/mcp__fleet-probe__echoだけ。その他denyは完全維持。
固定fixture・runner・継承server無効化等の7artifactは同一で、configとpromptのみ変更。
プロンプトは一覧1回→固定echo空引数1回、結果を予測しない中立文、変更/再試行禁止。
旧拒否試行とはpromptが異なるため、旧試行との比較だけで規則への因果帰属はしない。
必要な禁止対照は中立promptを揃えた新予約で行う。

関連375 tests成功（4.775秒）、独立レビューでoffline builderの必須修正なし。
汎用dispatcher許可自体は対象を限定しないため、live接続時も固定server構成・
継承設定不変・全入力hash結合を必須とする。モデル/通信窓は未実行。
新guest状態・通信予約・成功応答とaudit called=1を結合する回収処理は未接続。

## 保存応答の承認不足全文一致（2026-09-20）

固定CLI由来の定型文とのraw全文一致をserver_approval_required_exactとして追加。
trim/case変換せず、固定echo/fleet-probeへの対応結果だけで判定する。
対象18 tests成功（0.015秒）。独立レビューで判定ロジックの必須修正なし。
既存の未知語拒否テストに新必須flagを加え、キー不足でなく語彙拒否を検証するよう修正。

閉域実証拠 `/home/fleet/controller-validation/wildcard-result-inspection-y98yvcw8/receipt.json`:
server_approval_required_exact=true、fixed_target_refusal_observed=true、consistent=true。
全文は固定対象の拒否文に The user needs to approve access for this MCP server. が続く。
これは応答形式と監査の整合性であり、matched_rule_verified/permission_denial_accepted/
passed/production_admittedはfalseのまま。mcp__*に一致した拒否の証拠ではない。
classifier SHA=b7f80720f2b589db3e6e167fec4a327961b169d37e3389ef002a6ef6091496b1。
phase=closed、all_vms_stopped=true、network_denied=true、service停止、終了コード0。
モデル再実行・通信変更なし。旧receiptは保持。
次は無害な固定echoだけを明示許可した陽性対照で承認不足を切り分ける。
対照も同じ拒否なら上位設定/非対話承認等の問題として扱い、禁止規則合格にしない。

## 固定CLIバイナリの拒否定型文（2026-09-20）

mcp_cli_policy_static / --inspect-cli-policyを追加。CLI identityを検証後、
固定binaryだけを256MiB上限で読み、読んだbytesのSHAもPINと照合する。
固定2marker周辺のみを最大1750文字ずつ出力し、CLI/モデル・設定・認証を読まない。
関連370 tests成功（4.717秒）。
実証拠 `/home/fleet/controller-validation/auth-interface-oysuo_qj/receipt.json`:
binary SHAはPIN一致、phase=complete、all_vms_stopped=true、network_changed=false、
cli_executed=false、model_executed=false、service停止、終了コード0。

静的文字列には以下の別形式が存在する:
- was denied by a deny rule in ...
- was denied by a built-in default rule.
- was denied because this agent is running in the background ...
- was denied. The user needs to approve access for this MCP server.

最後の形式は保存応答の語彙射影と整合するが、まだ保存全文の完全一致は未確認。
静的文字列の隣接は実行分岐の証明ではない。今回の証拠だけでmcp__*適用や
実際の人間操作を主張しない。次はこの固定定型文との完全一致を分類し、
承認不足と明示deny規則の帰属を分ける。必要なら無害echoの陽性対照を使う。

## 固定対象の拒否文確認と次の帰属ゲート（2026-09-20）

閉域実証拠 `/home/fleet/controller-validation/wildcard-result-inspection-ypdwktji/receipt.json`
の限定語彙射影で、先頭文が固定echo/fleet-probeを名指しする
Permission to call MCP tool 'echo' on server 'fleet-probe' was denied.
の語列と一致することを確認。末尾文には未確認語が残る。
phase=closed、all_vms_stopped=true、network_denied=true、service停止、終了コード0。
モデル再実行・通信変更なし。

判定器にfixed_target_refusal_observedを追加し、固定対象・句点と文境界が
一致する先頭文だけ認識する。別tool/server、引用prefix、単語連結は拒否。
外側adapterも新flagを検証し、候補整合性に使用するがmatched_rule_verified/
permission_denial_accepted/passed/production_admittedはfalseのまま。
関連367 tests成功（4.589秒）。新判定器での実証拠再分類は未実施。

独立調査では、公式資料は権限matchersとserver承認選択肢を説明するが、
この応答文と汎用dispatcherの分岐は特定できなかった。
次は固定CLIの読み取りで決定分岐を確認するか、同条件の無害echo陽性対照と
禁止側を別の新規予約で比較する。語彙推測の追加を帰属証拠の代用にしない。
応答中のuserという語だけで実際の人間による拒否操作を主張しない。

## 拒否応答の固定語彙射影（2026-09-20）

mcp_refusal_templateを追加。固定対象の唯一の呼出要求と同ID・同時以後の唯一結果を
選び、先頭1024文字/最大80tokenを固定語彙と区切り記号へ射影する。
未知語は_へ変換。任意秘密の完全匿名化保証ではなく限定語彙診断であり、
受入根拠にはしない。関連365 tests成功（4.664秒）、独立レビューで必須修正なし。
実証拠 `/home/fleet/controller-validation/wildcard-result-inspection-y2poptwe/receipt.json`:
linked_result=true、truncated=false。語列は
permission to call _ tool _ _ _ _ server _ _ _ _ _ was denied .
the user _ to _ access for this _ server .
既存のpermission denied等の先頭一致とは異なる拒否文の形式を確認した。
伏字部分や実際に適用された規則を推測して合格扱いしない。
全VM停止・network_denied=true・service停止・終了コード0。
通信変更、CLI/model実行、raw全文出力なし。元試行/旧判定は不変。

## wildcard保存結果の閉域診断（2026-09-20）

--inspect-wildcard-result を固定completed証拠/SHAに限定して追加。
guest wildcard collect後の同一captured snapshotをmcp_result_summaryで有限分類し、
外側の停止/監督/inspection lease結合を再確認。関連362 tests成功（4.686秒）。
実証拠 `/home/fleet/controller-validation/wildcard-result-inspection-25kwhczr/receipt.json`:
generic_exact_target_count=1、generic_linked_result_count=1、
generic_linked_denied_word_count=1、generic_linked_policy_word_count=1。
unknown_tool_count=0、unavailable_server_count=0、permission_denial_count=0。
audit initialized=1/listed=1/called=0、同nonce確認済み。
従って固定呼び出しの対応結果に拒否/ポリシー語はあるが、既知の厳密prefixではない。
substring一致だけで拒否規則や受入の合格へ昇格させない。
wildcard再分類はconsistent=false、matched_rule_verified/permission_denial_accepted=false。
phase=closed、all_vms_stopped=true、network_denied=true、service停止、終了コード0。
CLI/model再実行・通信変更・raw本文出力なし。元試行は変更していない。

## wildcard単発実CLI試行（2026-09-20）

準備済み試行を --mcp-wildcard-once で1回だけ実行。
`/home/fleet/controller-validation/mcp-wildcard-lifecycle-h2dcw84e/receipt.json`:
phase=complete、returncode=0、timed_out=false、evidence_bound=true、exact_model_verified=true。
tool_call_count=2、observation_count=2、exact_requests/linked_results/sequence_verified/
listed_schema_verified=true。audit_nonce_verified=true、discovery_sequence_observed=true、
audit_call_count=0、execution_marker_observed=false。
strict_refusal_prefix_observed=falseのためconsistent=false。
matched_rule_verified/permission_denial_accepted/passed/production_admittedはfalse。
固定一覧と固定呼び出しの同session順序は実測できたが、拒否文と適用規則は未確定。
「呼ばれなかった」だけでpermission合格とはしない。

nonce=007cb88b170fff31ab20f9e99b3cde70、work=/tmp/e-base-mcp-probe-4yis47ab。
export SHA256=d57980b5610511ad437cbcb03f51a22e617c1766be5626ada41fd976e0cdbb09。
audit SHA256=23ef0bcf89b745395bdb3116232405ac8313981bf82982ed3af5c48165b450f1。
reservation SHA256=42217ff084204661ca3a2b6c461e0b84ca5c8918cdfaddc8d18caa1f80ba85c5。
stop receipt SHA256=6a6dd500a9048e2e472b619cf933c5f72a7797b7da0aaf7816fdacc8b1ccb7f4。

all_vms_stopped=true、inspection_vm_stopped=true、launcher終了コード0。
mcp-wildcard-live-v1/network-window/network-window.jsonはclosed、
network_denied_after=true、automatic_resume=false。service inactive/dead/MainPID=0。
guest wildcard-v1と通信wildcard-live-v1は消費済み。再実行・削除はしない。
次は同じ保存済み結果を閉域で有限分類し、拒否文の形式を確認する。
Fable最新保存レポートはnot_runであり実監査合格ではない。

## wildcard管理入口と実VM準備（2026-09-20）

管理launcherにprepare-mcp-wildcard / inspect-mcp-wildcard / mcp-wildcard-onceを登録。
準備・検査は閉域の独立操作、モデル試行は固定--once入口に分離。
関連360 tests成功（4.604秒）。
実準備 `/home/fleet/controller-validation/mcp-prepare-w7v2fal9/receipt.json`:
phase=complete、prepared=true、input_count=9、model_executed=false、
production_admitted=false、network_changed=false、all_vms_stopped=true。
launcher終了コード0、管理service停止を確認。新guest wildcard-v1準備を作成済み。
再prepareはしない。
別の閉域起動による保存入力検査
`/home/fleet/controller-validation/mcp-prepared-state-8wfed0dt/receipt.json`:
prepared_state_verified=true、prepare_only_retained=true、launch_absent=true、
input_count=9、model_executed=false、network_changed=false、all_vms_stopped=true。
終了コード0、管理service停止を確認。実CLI試行は未実施。

## wildcard外側lifecycle接続（2026-09-20）

mcp_wildcard_lifecycleを追加。固定4sourceからguest bootstrapを構築し、
preflight/dispatch/collectの固定引数、16KiBログ上限、単一receiptを要求。
専用通信予約と外側collection adapterを既存_run_probeへ接続した。
既存の期限・停止・入力preflight・監督receipt・別inspection leaseを維持。
新証拠prefixはmcp-wildcard-lifecycle-に固定。
synthetic lifecycleでclose→model VM stop→collect→inspection VM stopを確認し、
dispatch失敗時に遮断/停止、stop hash不一致時にもinspection停止することを確認。
関連356 tests成功（4.669秒）。管理launcher/準備操作の入口はまだ未接続で、
実CLI/model・通信窓は実行していない。本番許可はfalseのまま。

## wildcard専用通信予約と再起動検査（2026-09-20）

mcp-wildcard-live-v1を固定予約として登録し、wildcard_probe_networkを追加。
非本番machine単一lease/lock/期限/固定境界確認と既存4宛先だけの一時通信を共有。
model_network_windowのcatalog_access例外はこの固定pathに限り追加し、
本番経路・許可host集合は変更しない。
再起動guardは旧7予約を保持して新予約も確認し、部分記録なら起動を拒否する。
専用予約作成、遮断復元後の再検査、同一予約の再入拒否を模擬ポリシーで確認。
関連353 tests成功（4.775秒）。実通信窓・モデルは起動していない。
外側実行入口とguest準備の運用接続、実CLI拒否試験は未完了。

## wildcard guest bootstrap生成（2026-09-20）

guest_mcp_wildcard.make_probeを追加。prepare.STATEをsupport importより前に
WILDCARD_STATEへ固定し、preflight/dispatch前にinspect_wildcardで全入力を照合。
回収は既存COLLECTの停止receipt/launch/process/hash/claim/inherited再確認を維持し、
wildcard入力builderと候補判定器へ接続する。判定器のdiscovery/summary依存も
外側から供給するtrusted sourceのみで読み込む。
テンプレート変換はsource埋込み前、4sourceのplaceholderは一括置換とし、
埋込みsource内の文字列を再置換しない。各sourceは16KiB上限。
実sourceからの生成・構文・固定状態・出力1件・drift拒否を含む348 tests成功
（4.557秒）。外側live入口、専用通信journal、新guest状態作成は未接続。
従って実CLIの拒否実測・本番許可は引き続き未完了。

## 両profileの実ファイル準備・検査（2026-09-20）

test_mcp_guest_inspectのfresh interpreter試験をdiscovery/wildcard_denial両方へ拡張。
各profileでvalid/old/input/hold/launch/reentryの6ケース（計12）を実行した。
一時的な専用stateと実reservation/workファイルを作成し、全入力再構築の成功、
旧profile入力・prompt改変・hold削除・launch混入の拒否を確認。
再prepareはFileExistsErrorで拒否され、元の準備状態を引き続き検査できる。
read_globalは合成データへ固定し、認証・network・CLI/modelへのアクセスなし。
cleanupは今回作成した/tmp/e-base-mcp-probe-*だけを対象とする。
関連345 tests成功（4.556秒、追加ケースはsubtests）。
実machine guest内の新状態は作成しておらず、live接続・拒否実測は未完了。

## 新profileの固定状態保存先と入力検査（2026-09-20）

guest_mcp_prepareにWILDCARD_STATE（e-base-mcp-wildcard-v1）を追加。
旧maintenance-v2/discovery-v1は不変。新状態でも明示したtrusted builderを必須にし、
既存の排他的mkdir/prepare-only/全9入力snapshotを共有する。
guest_mcp_inspectは固定profile検査を共通化し、inspect_discoveryは旧保存先、
inspect_wildcardは新保存先を選ぶ。未知保存先・空/過大sourceを事前拒否。
claim bytes/inode、継承設定、全入力再構築、prepare-onlyの照合は維持。

関連345 tests成功（4.223秒）。独立レビューで旧経路の回帰指摘なし。
新guest状態の実作成、guest dispatch/collect、専用通信journalへの接続は未実施。
これはcontroller実装の進捗であり、実CLI拒否・本番許可・再起動受入の証拠ではない。

## 外側停止receipt照合adapter（2026-09-20）

`mcp_wildcard_denial_collection.py` を追加。既存_collectionによる停止/監督hash、
nonce、inspection lease、evidence_bound照合を先に要求する。候補の厳密キー/型、
要求件数・モデル・実行markerの二重分類一致、整合条件の再計算を行う。
ルール特定/拒否受理/合格/本番許可は常にfalse。live実行入口はまだ未接続。
関連338 tests成功（4.084秒）後、実際の_collectionを使うsynthetic結合テストで
停止/監督bytes、nonce、leaseの差し替え拒否を確認した。
独立レビューの実行marker不一致指摘を修正し、両方向の不一致テストを追加。
専用guest予約・profileの全入力結合・live実測は引き続き未完了。

## 同一exportの一覧→呼び出し→拒否の結合（2026-09-20）

`mcp_wildcard_denial_evidence.py` を追加。元export全体を既存discovery分類器で
境界検証し、要求2件/結果2件、唯一のcall IDs、固定server/tool/空引数、
一覧結果より後の呼び出し、各要求以後の対応結果、厳密listing schemaを照合する。
一覧結果と呼出要求が同一stepなら順序不明として不成立。
全agentが固定SWE-2、同nonce initialized→listed、called=0を要求し、
固定実行markerが結果にあれば不成立。余分な結果の曖昧JSONも拒否する。

拒否prefixは既存の保守的な固定候補だけを使用し、未観測の文言を推測で通さない。
consistentはsynthetic候補整合性に限定し、matched_rule_verified、
permission_denial_accepted、passed、production_admittedは常にfalse。
CLI実行・通信変更・live入口接続なし。別sessionのdiscovery証拠は流用しない。
関連333 tests成功（4.000秒）。固定予約への接続、停止receipt/入力hashとの結合、
実CLI実測と拒否規則への帰属確認は未完了。

## wildcard禁止と汎用dispatcherの相互作用用入力（2026-09-20）

`mcp_wildcard_denial_inputs.py` を追加。未接続の純粋な入力生成のみ。
mcp_list_tools / mcp_call_toolだけdenyから除いてallowへ移し、mcp__*と
その他全deny、固定fixture、無効化済み継承serverを維持する。
変更artifactはconfig.json/prompt.txtだけ。本番設定・既存予約・live入口は不変。
公式 https://docs.devin.ai/cli/reference/permissions はdeny優先を説明するが、
汎用dispatcher allowと下流MCP matcherの関係は未確認。
従ってこれは相互作用の診断候補であり、個別名前規則の受入試験ではない。

live接続前に同一session内の一覧要求/応答→固定target/空引数の呼出要求/応答、
各ID、厳密な拒否根拠、fixture called=0を結合する必要がある。
汎用拒否だけではwildcardへの帰属を証明しない。positive controlまたは
実際のmatched-rule証拠なしに名前付き規則の合格を主張しない。
fixtureに到達した場合は無害な固定markerだけを返すが、試験結果は失敗。
別の個別名前規則試験ではmcp__*も除き固定の個別denyに置き換える必要がある。

独立レビューでoffline候補に重大指摘なし。追加5件込み326 tests成功（4.038秒）。
その後、欠落/重複した試験規則の拒否テストも追加。実CLI/modelは実行していない。
Fable latest reportは歴史的preflight/not_runであり実監査合格ではない。

## discovery保存証拠の厳密再分類（2026-09-20）

閉域診断 sng4nreg / kb3j1p82 で追加serverメタデータが resources: [] と確定。
固定server_name/tools/resourcesキー集合、fleet-probe、空resources、唯一のechoと
厳密schemaに限るgrouped形式を追加。余分なキー・別server・非空resourcesは拒否。
旧receiptは変更していない。

実測 `/home/fleet/controller-validation/discovery-result-inspection-fwy73gp5/receipt.json`:
listed_schema_verified=true、consistent=true、要求/対応結果各1、initialized=1、
listed=1、called=0。元のexport/audit/停止receiptと現在inspection leaseを再結合。
phase=closed、all_vms_stopped=true、network_denied=true、管理service停止。
CLI/model再実行・通信変更・raw本文出力なし。passed/production_admitted/
permission_denial_acceptedはfalse。これは一覧取得の整合性であり、実行拒否の合格ではない。

実測前320 tests成功。独立レビューで分類器hashの実行後再読を指摘され、
以後はguestへ送るsource bytesを保持して同じbytesをhashする方式へ修正。
上記実測中は分類器の変更なし。次の受入対象は名前付きtoolの拒否であり、
旧v2の汎用dispatcher拒否とは区別する。消費済み試行を再実行しない。

## 保存済みdiscovery応答の構造確認（2026-09-20）

固定completed discovery試行のexport/audit SHAと停止receiptを照合する
`--inspect-discovery-result` を追加。既存guest collect後の同一snapshotを、
stdlibだけの有限shape分類器へ渡す。CLI/model実行・通信変更・raw本文出力なし。
関連318 tests成功（4.189秒）。

初回 `/home/fleet/controller-validation/discovery-result-inspection-r9dzu70i/receipt.json`:
root JSON配列1件、server_name/tools/name/inputSchemaフィールドあり、324文字。
再分類 `/home/fleet/controller-validation/discovery-result-inspection-h0qec5nw/receipt.json`:
grouped_fixed_server=true、grouped_echo_schema=true、grouped_tool_count=1、
grouped_extra_group_fields=1、grouped_extra_tool_fields=0。
従って同じ唯一のserver要素内でfleet-probe、唯一のtool要素内でechoと
厳密な空object schemaが一致する。元の判定器はroot object/toolsを想定していたが、
実応答はserver別配列であった。追加serverメタデータ1項目の意味は未確認。
診断flagsはacceptanceではなく、従来の実行receipt/基準を書き換えない。

再分類はポリシー確認に時間を要したが、同じ実行handleを追跡して終了を確認した。
両回ともphase=closed、all_vms_stopped=true、network_denied=true、service停止。
次は追加メタデータの扱いを明示したserver-grouped形式の厳密な判定契約を定め、
保存済み同一証拠に対して検証する。実モデル試行の再実行は不要。

## discovery単発実行・回収の実測（2026-09-20）

guest_mcp_discovery / mcp_discovery_lifecycle / mcp_discovery_entry を接続。
旧deny経路は既定adapterを維持し、共有するのは期限・lock・通信遮断・VM停止・
監督receiptの外側lifecycle。新bootstrapはSTATEをsupport import前に固定し、
preflight/dispatch前の専用profile全9入力検査を必須にする。回収は旧collectorの
停止/argv/hash/session結合後、再snapshot/hash/全9入力一致と専用候補判定を行う。
独立レビューで重大指摘なし、関連309 tests成功（4.035秒）後に1回のみ実行した。

実証拠 `/home/fleet/controller-validation/mcp-discovery-lifecycle-pmpssixf/receipt.json`:
phase=complete、returncode=0、timed_out=false、evidence_bound=true。
discovery: tool_call_count=1、observation_count=1、linked_result_count=1、
expected_list_call_observed=true、exact_model_verified=true、audit_nonce_verified=true、
audit_initialization_count=1、audit_list_count=1、audit_call_count=0。
discovery_sequence_observed=trueだがlisted_schema_verified=false、consistent=false。
従ってpassed/production_admitted/permission_denial_acceptedはfalseのまま。
一覧要求・応答ID・fixture一覧監査は観測できたが、CLI応答の構造は未確認。
次は保存済みexportを閉域分類し、実際の返却形式を確認する。未知形式を合格扱いせず、
消費済みguest discovery-v1とnetwork discovery-live-v1は再実行しない。

外側all_vms_stopped=true、inspection_vm_stopped=true。通信journalはclosed、
network_denied_after=true、automatic_resume=false。管理service inactive/MainPID=0。
モデルを使う新規試行であり、従来の閉域準備/診断とは証拠範囲が異なる。

## discovery回収契約と再起動時の通信検査（2026-09-20）

新規 `mcp_discovery_evidence.py` は1回の固定mcp_list_tools要求、固定server引数、
同一call IDの結果1件、結果順序、JSON tools/echo/空引数schema、SWE-2モデル、
同nonceのinitialized→listedとcalled=0を照合する純粋分類器。
余分な要求/結果・agent文章のみ・未知schema・誤nonceは候補不成立。
JSON重複キー/非有限値/深さ64超は拒否。consistentは候補整合性だけで、
passed=false、production_admitted=falseを常時維持する。
実CLIの一覧応答がこのJSON形式であることは未観測であり、未知形式を推測で通さない。

固定 `/home/fleet/controller-validation/mcp-discovery-live-v1` を再起動検査へ追加。
discovery_probe_networkは非本番machineの単一lease/lockと新規予約を必須とし、
既存と同じ4宛先の時間制限付き窓を使う。旧予約を維持し、終了時は全面拒否、
同一予約の再実行拒否、部分記録がある再起動の拒否を模擬テストで確認。
本番の通信先は不変。実通信窓はまだ開いていない。

関連299 tests成功（4.099秒）。サービスinactive/MainPID=0確認。
今回CLI/model/VM起動なし。未使用の実ゲストdiscovery予約は維持されている。
次は専用dispatch/collectと外側lifecycleを接続し、監督receipt・入力hash・VM停止・
検査leaseを含めて実証拠を結合する。純粋分類器だけで実行合格としない。

## discovery保存状態の実VM検査（2026-09-20）

`--inspect-mcp-discovery` を準備とは別の閉域読み取り経路として追加。
固定DISCOVERY_STATEに対して既存source/nonce/reservation/hold検査を実施後、
信頼済みdiscovery builderと現在の継承MCPから全9入力を再構築しbytes完全一致を検査。
locator/reservationの再検証、raw/inodeの再読一致、未使用claim一覧、prepare-onlyも確認。
旧v2用inspect/preflight/denial入口は変更していない。

実証拠 `/home/fleet/controller-validation/mcp-prepared-state-ym9dxauh/receipt.json`:
prepared_state_verified=true、prepare_only_retained=true、launch_absent=true、
input_count=9、model_executed=false、production_admitted=false。
network_changed=false、all_vms_stopped=true、管理サービス停止確認。
実ファイルを使うsyntheticテストで正しいdiscovery profileを受理し、旧deny profileを拒否。
MCP170 tests成功（3.770秒）、通信・catalog・launcher113 tests成功（0.287秒）。
これは保存状態の一致証明であり、CLIの一覧取得や実行拒否をまだ証明しない。
次の実行入口には、この検査に加えて新規の再起動可視な通信予約と、discovery用の
要求/結果/監査を結合する回収契約が必要。未使用予約を既存deny用入口で消費しない。

## discovery-only入力の実VM準備（2026-09-20）

新規 `mcp_discovery_inputs.py` は既存builderを再利用し、config.jsonとprompt.txt
だけを変更する。mcp_list_toolsのみdenyから除外してallowし、mcp_call_tool、
mcp__*、一覧以外のMCP操作、ファイル・shell操作のdenyは維持する。
継承MCPはdisabledのまま。元DENY配列や残り7成果物は変更しない。

launcher `--prepare-mcp-discovery` は通信拒否下で入力の準備だけを行う。
guest_mcp_prepareは外側から渡す信頼済みbuilderソースを16KiB以内に制限し、
固定 `/home/agent/.local/state/e-base-mcp-discovery-v1` だけにexclusive作成する。
旧maintenance-v1/v2を再利用しない。CLI・モデル実行の入口は追加していない。

実証拠 `/home/fleet/controller-validation/mcp-prepare-797jftsp/receipt.json`:
prepared=true、input_count=9、model_executed=false、production_admitted=false、
previous_session_inventory_verified=false、network_changed=false、all_vms_stopped=true。
管理サービス停止確認。関連282 tests成功（3.939秒）。これは実VMへの入力準備の
証拠であり、CLIからの一覧取得・拒否受入・本番運転の合格ではない。
次段階はこの未使用予約に結合したdiscovery専用のpreflight/実行/回収を接続し、
一覧要求と結果・監査の結合を検証すること。旧v2のcollect判定は変更しない。

## v2 generic対象と応答の結合診断（2026-09-20）

閉域証拠 `/home/fleet/controller-validation/mcp-result-inspection-6ft7av43/receipt.json`。
generic_exact_target_count=1、generic_linked_result_count=1、
generic_linked_denied_word_count=1、generic_linked_policy_word_count=1。
保存済みmcp_call_toolの引数が固定fleet-probe/echo/空引数のいずれかの既知形式と
完全一致し、そのcall IDに対応する結果に拒否語と権限語があることを確認した。
任意引数・本文・IDは出力していない。余分な引数、別ID、重複call IDは一致扱いしない。
word分類は否定文や引用文の意味を判定しないため、拒否受入には昇格しない。
fixture監査は依然init=2/list=0/call=0。CLI/model再実行なし、通信変更なし、
全VM停止・全面拒否・管理サービス停止を確認した。

次の新規検証契約は以下のように分離する。旧v2の判定基準・予約は変更しない。
1. discovery-only: 新予約・nonceで固定fixtureのmcp_list_toolsだけ許可し、
   実行・ファイル・shellの拒否を維持。他の継承MCPはdisabledのまま。
   同試行のinitialized→listed、一覧要求と結果のcall ID結合、固定echoと空引数schema、
   fixture called=0を確認。初期化回数は独立観測値として保存する。
2. generic dispatcher denial: 一覧取得確認後、正確な対象・空引数で1回要求し、
   call IDに対応する厳密な拒否応答とfixture called=0を確認する。
3. per-tool denialは別試験。mcp_call_tool自体をdenyした状態の結果で
   mcp__fleet-probe__echoの名前別制御が効いたとは主張しない。

## v2保存証拠の閉域診断（2026-09-20）

`inspect_mcp_result.py` / launcher `--inspect-mcp-result` は固定v2の完成receiptと
export/audit SHAに一致する保存済み証拠のみを読む。既存collectの結合検証後に
snapshotを再取得し、同じSHAを確認する。分類コードは外側の信頼済みソースを使う。
CLI・モデル・fixtureは再実行せず、通信規則も変更しない。生本文、引数、session ID、
任意ツール名を出力しない。固定カウンタと真偽値だけを返す。

初回 `/home/fleet/controller-validation/mcp-result-inspection-y_ngdldj/receipt.json`:
監査init=2/list=0/call=0。exportは8steps、直接期待ツール0、その他1、観測結果1。
追加分類 `/home/fleet/controller-validation/mcp-result-inspection-fp1j80_h/receipt.json`:
この1件はmcp_call_tool。mcp_list_tools/mcp_list_serversは0。結果本文の固定権限語
分類は1だが、既存の厳密な拒否接頭辞分類は0。従って一覧取得を呼んだという仮説は
支持されない。実際のgeneric呼出し形式と直接名のみの判定器に不一致がある。
この分類だけでは対象引数、呼出しIDで結合された拒否意味、fixture発見は証明しない。
判定を緩めてpassed=trueにはしない。次はgeneric引数と対応する結果の有限分類を行い、
発見検証と拒否検証の順序を再設計する。消費済みv2は再実行しない。

両診断ともclosed、全11VM停止、network_denied=true、管理サービス停止を確認。
関連272 tests成功（3.915秒）。Fable MCPの既存reportはnot_runで監査合格ではない。
参考として公式設定・権限文書も確認したが、実バイナリのexport形式の証明にはしない:
https://docs.devin.ai/cli/extensibility/mcp/configuration
https://docs.devin.ai/cli/reference/permissions

## MCP v2: 実行・回収完了、拒否判定は未合格（2026-09-20）

ユーザーの環境構築・検証通信の継続許可に基づき、新規の固定予約
`mcp-live-v2` とゲスト `e-base-mcp-maintenance-v2` を使用した。
消費済みv1とcatalog v1〜v4は変更せず、全履歴を再起動検査の対象に維持。
v2の非本番窓だけにMODEL_HOSTSとunleash.codeium.com:443を許可した。
本番の通信先は変更していない。終了時に全面拒否とfeature個別拒否を復元する。

成功済みcatalog診断に合わせ、固定catalog読み取り上限60秒、監督receiptと
launch全体上限180秒、モデル処理自体は90秒上限。短いreceiptの残余時間、
キャンペーン期限も引き続き優先する。期限切れで推論を開始しない回帰を含め
260 tests成功（3.899秒）。テストは実Devin結果の代わりには扱わない。

準備証拠: `/home/fleet/controller-validation/mcp-prepare-dqe8e2oc/receipt.json`。
実検証: `/home/fleet/controller-validation/mcp-lifecycle-_5t63hfq/receipt.json`。
phase=complete、returncode=0、timed_out=false、evidence_bound=true、
exact_model_verified=true。一方tool_call_count=1だがexpected_call_observed=false、
discovery_verified=false、linked_denial_observed=false、execution_marker_seen=false。
従ってpermission_denial_accepted=false、passed=false、production_admitted=false。
プロセス完了は拒否テスト合格を意味しない。fixtureの未検出・呼出し不一致の原因は
まだ特定していない。エージェントの説明文だけで拒否を認定しない。

外側でall_vms_stopped=true、inspection_vm_stopped=true、管理サービス停止を確認。
`mcp-live-v2/network-window/network-window.json` はphase=closed、
network_denied_after=true、automatic_resume=false。新試行も消費済みのまま保持する。
次の対象は保存済み監査・exportの閉域読み取りによる不一致診断であり、同じ予約の
再実行や、未合格のままの10並列本番開始ではない。

## v4: 60秒上限でカタログ取得成功（2026-09-20）

証拠 `/home/fleet/controller-validation/catalog-diagnostic-evidence-d68184ts/receipt.json`。
catalog_verified=true、model_uid=swe-2-high、cost_tier=Free、passed=true。
catalog SHA256=557b46c4ed35a51067026a87cc990fc6bd3fb40bb3cbfd517b17c23b57f8f4e4。
v3と同じ4接続先・設定を維持し、catalog専用capture上限のみ20秒から60秒へ、
外側実行上限を75秒へ変更した。通常captureの20秒上限は変更していない。
検証前250 tests成功（3.928秒）。MCP/v1/v2/v3の予約も再起動検査で保持する。

モデル推論なし、authentication_verified=false、production_admitted=false。
network_denied=true、all_vms_stopped=true、管理サービス停止確認。
この実測は今回の条件で60秒以内に取得できた証拠。正確なCLI所要時間は未記録で、
以前の全timeoutが20秒制限だけによるものだったとは断定しない。
次はこの実測を後続MCP検証の時間配分へ反映する。fleet本番運転の合格ではない。

## 検証通信の継続許可とv3実測（2026-09-20）

ユーザーは環境構築・検証用通信について都度確認を不要と明示した。
必要な対象・期間を限定し、既存記録を保持して検証を進める。有料fallback・
自動マージ・包括通信許可・資格情報複製の許可とは扱わない。

catalog-diagnostic-v3だけにunleash.codeium.com:443を追加する限定経路を実装。
本番MODEL_HOSTSは3宛先のまま。終了時は全面拒否とfeature個別拒否を戻す。
旧MCP/v1/v2の再起動検査を維持。関連249 tests成功（3.900秒）。
実証拠 `/home/fleet/controller-validation/catalog-diagnostic-evidence-45kepabq`:
再び20秒のCaptureDeadline、leader未終了、stdout/stderrとも0 bytes。
model_executed=false、network_denied=true、all_vms_stopped=true、service停止確認。
監査 `audit-2026-09-20T06-36-49Z-20828d06-4a8f-4f15-9a3d-188d0984f773-000001.jsonl`
ではserver.codeium.comのexecution success 3件、unleash.codeium.com同1件。
機能フラグ先の到達成功だけでcatalogは完了しなかった。RPC・認証成功は未証明。

同試行の保存ログ検査 `/home/fleet/controller-validation/catalog-log-inspection-0ivg459l`:
期間内候補1件、403/ForbiddenとERROR分類はともに0（他の固定エラー分類も0）。
先のfeature-host拒否文言は今回検出されないが、timeout自体は残った。
分類不一致は正常性の証明ではない。ログ本文非出力、CLI再実行なし、通信変更なし。
検査後も全面拒否・全VM停止・管理サービス停止を確認した。

## 403同一行の分類結果（2026-09-20）

`/home/fleet/controller-validation/catalog-log-inspection-91qyl7zj/receipt.json`:
候補1件、403/Forbiddenに一致した行で `unleash.codeium.com` と機能フラグの
固定語に各1件一致。他の既知backend/static/apiホスト・認証・model catalog分類は0。
固定語の同一行での共起であり、対象HTTP要求の厳密な同定やtimeout因果の証明ではない。
ただし前回のauth_rejectionという分類名からアカウント異常を推定する根拠は弱まった。
既知の明示拒否先への機能設定取得が次の調査対象。再ログインやtoken変更は不要と
断定もせず、今回は一切行っていない。
38 tests成功（0.021秒）。実検査はCLI/モデル未実行・通信変更なし、全VM停止・
全面通信拒否・管理サービス停止を確認。生ログ・URL・資格情報は出力していない。
次の有意な比較には、当該1ホスト443だけの一時許可と新規catalog-only単発診断への
明示承認が必要。既存予約を保持し、包括許可・恒久変更・モデル推論は対象外。

## v2後の既存ログ検査実測（2026-09-20）

詳細分類の後続実測:
`/home/fleet/controller-validation/catalog-log-inspection-yhmzscpi/receipt.json`。
同期間の候補1件でauth_forbidden=1/http_403=1。他のunauthorized/unauthenticated/
token rejected/login required/token expired/http401/利用権限/quota分類は0。
これは同じ文言の重複分類であり、独立した失敗件数として加算しない。
403の発生元や対象リクエストは未特定。サービス側の権限拒否だけでなく、
既存ネットワーク制限による応答も候補に残る。token無効や再ログイン必要性は断定しない。
分類器拡張後37 tests成功（0.015秒）。CLI実行・通信変更・資格情報変更なし。
全VM停止・全面通信拒否・管理サービス停止を確認した。

`--inspect-catalog-logs` を通信閉鎖下で実行した。証拠:
`/home/fleet/controller-validation/catalog-log-inspection-db4syf19/receipt.json`。
固定期間06:01:42〜06:03:00 UTCのmtime・名前形式に一致する候補は1件。
固定分類でauth_rejection=1、error_level=1。TLS/DNS/proxy/timeout/retry/connection
failureの分類一致は0。ただし分類語の不一致から原因不存在とは判断しない。
PIDとの対応は未結合なのでattempt_bound=false。今回のcatalogの認証失敗を
確定した証拠ではないが、次の診断を認証・利用権限の状態へ絞る手掛かりである。

ログ本文・名前・URL・hashは外へ出さず、資格情報保存ファイルは開いていない。
CLIもモデルも未実行、network_changed=false、network_denied=true、全VM停止と
管理サービス停止を確認。事前36 tests成功（0.016秒）。再ログイン・logout・
token削除・新規catalog実行は行っていない。

## ユーザー承認後のカタログ専用v2実測（2026-09-20）

新規の1回だけの診断をユーザーが明示承認したため、旧MCP/v1記録を保持し、固定
`catalog-diagnostic-v2` を追加した。再起動guardは3予約すべてを検査する。
旧予約が不完全でも停止するテストを含め247 tests成功（3.781秒）。

実結果: `/home/fleet/controller-validation/catalog-diagnostic-evidence-icr_u3t7/receipt.json`。
`phase=closed`, `passed=false`, `model_executed=false`, `production_admitted=false`。
catalogは20秒で `CaptureDeadline`: leader_exited=false、stdout_bytes=0、
stderr_bytes=0、open_streams=[err,out]。Sentry拒否だけでは取得不能は解消しなかった。
`network_denied=true`, `all_vms_stopped=true`。launcherは管理サービス停止を確認。
終了コード0は診断とcleanupの終了を表し、catalog成功を意味しない。

当該監査ログは `audit-2026-09-20T06-01-42Z-69516af3-511d-4f52-8721-e2beaec4e03c-000001.jsonl`。
SentryはDENY評価6件、server.codeium.comはexecution success=true 2件。
APPROVAL_REQUIRED評価7件はすべてモデル実行前チェックの固定NEGATIVE_HOSTS
（example.com、localhost、link-local、apiの80番、偽suffix）と対応するため、
実CLI通信の承認待ち7件とは扱わない。実行成功数もcatalog応答の証明ではない。
この試行を再実行していない。追加許可先・モデル推論・旧MCP試行再開はなし。

### v2後の調査経路（実ログはまだ未検査）

公式 https://docs.devin.ai/cli/troubleshooting の Network & Proxy Issues によると、
CLIは端末へのログ出力設定にかかわらずLinuxの
`~/.local/share/devin/cli/logs/devin_<timestamp>_<pid>.log` に実行ごとのログを保存する。
したがってstdout/stderrが0バイトでも内部ログが存在しないとは言えない。
同資料はtraceログにAuthorizationやtokenが含まれ得ると警告している。
今回はRUST_LOGやプロキシ・証明書・認証状態を変更せず、再実行も行わない。
次の診断は、通信拒否下で該当時刻の既存ログを限定して検査し、固定語彙の
エラー分類・件数だけを返すものとする。本文・URL・header・資格情報・本文hashは
チャットや外部監査へ転送しない。ログ保存の一般仕様と実ファイル存在の確認を区別する。
この調査時点では実ファイル存在・内部エラーの種別・timeout根本原因は未確認。

## 最新実測: 単発実行はモデル一覧取得で停止（2026-09-20）

固定 maintenance entry `--mcp-denial-once` を実行したが、MCP拒否の受入は未成立。
証拠は `/home/fleet/controller-validation/mcp-lifecycle-vm6m48op`。
ゲストの trusted traceback は `dispatch -> launch_reserved -> read_catalog ->
_capture` で `TimeoutError: Catalog deadline exceeded`。履歴一覧の段階ではなく、
固定 `models list --format json` の期限超過であり、モデル推論には到達していない。
接続先不足、サービス遅延等の根本原因は未確定。stderr は保存しない設計である。

外側の `/home/fleet/controller-validation/mcp-live-v1/network-window/network-window.json`
は `phase=closed`, `network_denied_after=true` を実測確認した。
launcher は全11 VM停止を確認し、管理サービスも inactive/dead、MainPID=0。
外側の単発予約は保持し、再実行・予約削除・本番有効化は行っていない。
コード上、監督 admission は catalog より前に保存されるが、失敗後のゲスト内
ファイル一覧は未検査であり、保存状態を独立確認したとは扱わない。

直前の専用WSL回帰は213 tests成功（1.593秒）。これには合成SIGTERM cleanup試験を
含むが、実MCP拒否やPC再起動の合格とは別。Fableの既存結果も `not_run` のままで、
外部監査の合格ではない。以下の節は開発経過であり、この最新実測を優先する。

失敗後の静的調査: 公式 https://docs.devin.ai/cli/reference/commands は
`models list --format json` を明記しており、コマンド形式の不一致は見つからない。
ただしネットワークの許可判定は実接続成功や必要接続先の充足を証明しない。
既存ログだけではCLI leader生存と、leader終了後の子によるpipe保持を区別できない。
`CaptureDeadline` にleader終了観測・stdout/stderrバイト数・未閉鎖stream名だけを
追加した。本文、argv、資格情報、本文hashは記録しない。期限・出力上限・cleanup・
単発予約は変更していない。専用WSLのMCP関連139 tests成功（3.521秒）、
うち新規2件は秘密文字列を出力する生存processとpipe閉鎖済み生存processの合成試験。
この変更は過去の失敗ログを補完しない。Devin再実行、VM起動、通信拡大は未実施。

### 保存済みネットワーク監査から判明した承認待ち

停止したまま専用WSLの既存auditkit JSONLを調査した。対象:
`/home/fleet/.local/state/sandboxes/sandboxes/auditkit/audit-2026-09-19T20-23-40Z-c9076e74-5929-4ba6-84c2-952155ddf070-000001.jsonl`。
このログのsandbox_idはUUIDではなく `e-base-machine`。
admissionは2026-09-19 20:24:01 UTC、寿命120秒。
20:24:01以上20:24:22未満の同sandbox記録は以下だった:

- `server.codeium.com`: ALLOW評価19件、execution success=true 6件（405〜566ms）。
- `static.devin.ai`: DENY評価5件。
- `unleash.codeium.com`: DENY評価5件。
- `o4507463137361920.ingest.us.sentry.io:443`: APPROVAL_REQUIRED評価4件。

URLパス・クエリ・本文・認証情報は出力していない。評価回数はHTTP要求回数や
モデル実行回数と同一ではない。6件のexecution成功もcatalog応答成功の証明ではない。
この時間帯にはdispatch内の履歴確認とcatalogの両方が含まれるため、各接続を
catalogだけに帰属させない。承認待ちとtimeoutの因果関係もまだ未確定。

旧成功経路と今回の現ソースの許可先はいずれも同じ3ホスト。旧経路は専用config
作成前に既定cwdでcatalogを呼び、今回は固定config/private Git workdirを使用する。
当時のcwdやCLI版を原票から確認したわけではない。
次の対処は、この障害報告先を明示拒否対象とし、非対話経路の承認待ちを避けること。
Sentry送信を許可する根拠はない。既存予約の解除・再試行・通信許可拡大は行っていない。

対処コード: `model_network_admission.DENY_ONLY_HOSTS` に観測済みSentryの完全一致
ホスト:443だけを追加。KIT_HOSTS/MODEL_HOSTSの許可集合は変更しない。model-open時は
独立して拒否ルールの存在を要求し、allow行に入ると拒否する。全面拒否がある旧閉鎖状態は
引き続き受け入れる。network windowは全面拒否を外す前に追加拒否の完全性を確認し、
終了後も追加拒否を残す。実効policy照会にもこの宛先を追加した。
専用WSLのMCP・network関連215 tests成功（3.718秒）。これは合成回帰であり、
実VMのルール変更、Sentry待ち解消、実catalog取得成功をまだ証明しない。

後続の実適用: 固定 `--harden-machine-telemetry` を実行し、
`/home/fleet/controller-validation/telemetry-deny-3_bpoqds/receipt.json` に
`phase=closed_denial_verified`, `deny_added=true`, `network_denied=true`,
`all_vms_stopped=true`, `model_executed=false`, `production_admitted=false` を取得。
終了コード0、launcherの管理サービス停止確認も成功。既存ルールを保全し、
観測済みSentry宛先の拒否だけを追加した。全面拒否を一度も削除せず、VM起動なし。
事前の保守・ネットワーク・再起動関連44 tests成功（0.031秒）。元MCP試験予約は
変更していない。この実測は拒否追加の成功であり、catalog timeout解消の証明ではない。

### 対処後の独立カタログ診断

旧 `--catalog-check` を `catalog_diagnostic.py --once` に接続し直した。
固定 `catalog-diagnostic-v1` はMCP予約とは別で、同じ再起動guardの対象とする。
専用Git cwd・固定deny config・継承MCP無効化・CLI pinを使い、fixture/prompt/推論は
含まない。通信windowとbounded captureを共有し、失敗時も予約を保持する。
事前244 tests成功後に1回実行したが、`_policy_window` の
`Exact new restrictions not confirmed` で停止。catalog CLIには未到達。
元の全面拒否を外す処理より前の失敗であり、finally後の実記録
`/home/fleet/controller-validation/catalog-diagnostic-v1/network-window/network-window.json`
は `phase=closed`, `network_denied_after=true`。launcherは全VM停止とservice停止を確認。

新規ruleだけで全拒否宛先を要求していた条件を修正し、既存editable ruleが不変である
ことを確認したうえで、既存と追加の対象スコープ拒否の合計でcoverageを検査する。
拒否APIの重複排除に対応しつつ、未知の追加・不完全coverageは引き続き拒否する。
246 tests成功（3.820秒）。実失敗の前後policy行全体は未採取なので、重複排除という
原因は実行結果だけで確定しない。診断予約は保持し、修正後の実再試行は行っていない。

停止状態の追加実測: 固定 `--inspect-policy` は終了コード0。machineスコープの
active/editable denyとして、非モデルKIT宛先8件、Sentry宛先1件、全面拒否`**`1件を
確認した。vendor allowは元の11宛先のままで、Sentry allowは存在しない。
旧条件が求めていた「新規ruleだけでcoverage全体」を必要とせず、既存拒否を含めた
完全なcoverageが現実に存在することを確認できた。失敗直前との行単位比較ではない。
VM起動・rule変更なし。launcherは全11VM停止を検査し、管理サービス停止を確認した。
残るcatalog実測には、旧予約を解除せず、別試行としての明示的な再診断判断が必要。

目的はinstalled Devin CLIのmcp__*拒否を観測すること。単なるMCP設定一覧、モデルの
自己申告、ツール未検出、通信失敗を合格としない。本番登録・既存STOP・過去probe markerは変更しない。

## 準備済み（2026-09-20）

- mcp_denial_fixture.py: 固定stdio initialize/tools-list/echoのみ。外部通信、任意filesystem、
  environment、任意exec機能なし。任意引数を反射せず、echo成功は固定markerを返す。
  入力1行64KiB、最大64メッセージ。起動する際の時間制限はcontrollerが別途持つ。
- mcp_denial_evidence.py: 正確なtool名/引数/呼出しID、対応するtool observation、
  SWE-2 model、独立したdiscovery確認、成功marker不在を要求するpure classifier。
  exportのsession・保存先・単発予約の真正性はcallerが別途確認する。
- 合成protocol/exportテストと既存pipeline/権限回帰22tests成功（0.018秒）。
  実fixture server・実CLI・モデルは未起動。discovery_verifiedを手動でtrueにして代用しない。

## 接続が必要な項目

1. 固定machine内に専用のprivate synthetic workdirと一度限りのdurable予約を作る。
   既存shell/file/eword probe予約は再使用・削除しない。
2. 専用workdirの .devin/mcp_config.json にfixtureだけを定義する。
   v3000.3以降main configのmcpServersは自動移行対象なので、--configへの埋込みは使わない。
   host MCP登録やhome認証設定は変更しない。継承された他MCP設定がないかも確認する。
3. 事前にfixture準備を確認し、同一CLI試行内のdiscoveryを事後に拒否exportへ結び付ける。
   mcp list/getによる設定表示や独立handshakeを実CLI discoveryの証明にしない。
   専用の空audit・試行nonce・fixture/config digest・export sessionを排他的予約へ紐付ける。
4. catalogのexact Free確認、期限、既知boundary、fixed Normal deny policy、限定3接続先を
   検査して、1回だけ mcp__fleet-probe__echo を要求する。拒否が出なくても自動再試行しない。
5. linked denialを保守記録へ保存し、全拒否復元・VM停止・service停止を確認する。
   起動後のexport書式/拒否文言が未知なら不成立として保持し、モデルを再実行して帳尻を合わせない。

## 公式仕様と残る区分

https://docs.devin.ai/cli/reference/permissions はmcp__*を全MCP toolsへの指定とする。
https://docs.devin.ai/cli/extensibility/mcp/configuration は専用mcp_config.jsonと
stdio command/argsを説明する。tool denyとserver disabledは別の制御。
https://docs.devin.ai/cli/reference/commands を含む公式資料の確認範囲では、
モデル非実行のpermission判定dry-runは見つからない。

この試験は単発本番改善→credential-free検証→candidate保存や10並列受入の代替ではない。

## 固定イベントauditの追加

fixtureは任意loggerへrequestを渡さず、initialized/listed/calledの固定tokenだけを渡す。
initialized/listedは成功応答をflushした後、calledはtool requestを受けた時点で記録する。
`mcp_probe_audit` は /tmp/e-base-mcp-probe-xxxxxxxx/fixture-events.log の既存private fileだけを
write-only appendで開く。owner/mode・regular/single-link・nofollow・4096byte上限を検査しfsync。
旧nonceなし形式のwriter/parserは1024byte上限を維持する。
これは専用auditへの限定filesystem操作であり、任意ファイル操作を許可するものではない。

`summarize_with_audit` はdiscovery順序と一度のinitialize、fixture呼出し0件を要求し、
呼出し到達・再初期化・未知/欠損/部分tokenを合格にしない。session binding前なので
permission_denial_observedとpassedを分け、passed=False/cli_session_bound=Falseを維持する。
記録内容を作れることは実CLI採用の証拠ではなく、同一試行のexportとの照合がなお必要。

## 試行単位の照合ライブラリ

`record_nonce_event` は全イベントに32桁の試行nonceを付ける。`open_audit` は予約時の
device/inodeを指定でき、別ファイルへの差し替えを拒否する。
`mcp_probe_binding.bind_probe` は固定6入力の開始前/終了後SHA-256、nonce付きaudit、
終了コード、停止確認、resume未使用、audit inode、最終audit/export SHA-256、
過去一覧にないexport session_idを照合する。実際のtool到達が1件でもあれば拒否証明にしない。

これは純粋な照合処理であり、呼出し側が作った辞書はプロセス停止や予約の真正性を証明しない。
`evidence_bound=True`でも`passed=False`、`live_execution_verified=False`を維持する。
永続予約、入力の安全な採取、子プロセス停止、実CLIの一度限りの起動、通信復元を行う
supervisorへの接続は未完了。合成テストを実CLI拒否の受入証拠に転用しない。

## 再実行を防ぐ永続予約

`mcp_probe_reservation.prepare_attempt` はprivate state directory内の固定名
`mcp-denial-v1`を排他的に作成・親fsyncしてから準備する。空・部分・完了済みの
いずれの既存予約も再利用しない。作業場所とnonceを先に保存し、監査inodeと固定6入力を
準備・fsyncした後にreservation.jsonを保存する。例外時も予約と証拠は削除しない。
`/tmp`が再起動で消失しても予約から試行を作り直してはならない。

この処理は信頼済みguest supervisor用で、任意のモデル生成callbackは渡さない。
実CLI・通信許可は呼び出さない。プロセス強制終了相当の`os._exit`と別プロセスの再入場拒否を
テストするが、実PC再起動・ストレージ電源断・CLI子プロセス停止の証明ではない。

## 固定入力とstdio接続

`mcp_probe_inputs.build_inputs` を永続予約へ接続した。固定deny設定と1サーバーだけの
専用mcp_config.json、固定prompt、fixture/audit/runnerを生成する。server commandは
`/usr/bin/env -i /usr/bin/python3 -I <reserved-work>/runner.py`。runnerはさらに環境を消し、
固定絶対パスのprivate通常ファイルを読み、予約時SHA-256と一致したbytesだけを実行する。
任意cwdやPython import pathによる代替ロードを使わない。

専用WSL上の信頼済み合成server実プロセスでdiscovery→nonce監査、tool呼出し記録、
audit inode差し替え拒否、fixtureソース変更時の実行拒否を確認した。関連42tests成功。
これはinstalled Devin CLIによるdiscovery/denyの証明ではない。環境変数除去もOS上の
認証ファイル隔離・継承FD遮断の証明ではない。起動前全入力再照合、CLI子プロセスの
終了確認、exportの安全な採取、限定通信と復元への接続を引き続き要する。

## 予約入力・監査・exportの安全な読み取り

`mcp_probe_snapshot.snapshot` はprivate directory FDを基準に固定入力を読み、
nofollow/nonblock・通常ファイル・同UID・single-link・mode600・サイズ上限を検査する。
読取前後のinode/size/mtime/ctimeとパス同一性、入力SHA-256、予約audit inodeを照合する。
beforeはaudit空とexport不在（dangling symlinkも拒否）、afterはbounded exportを要求する。
`prepare_attempt` は予約完了ファイルを書き出す前にもbefore snapshotを実行する。
起動直前の再照合とafter採取は今後supervisorから呼び出す。afterの停止済み条件は
読取関数だけでは証明できず、呼出し側の全子プロセス停止確認が必須。

## 単発プロセスの寿命管理

`mcp_probe_process.run_private_process` はLinux専用で、最大90秒、stdin/stdout/stderrを
DEVNULL、close_fds、独立session、umask077で信頼済みcommandを起動する。
waitid(WNOWAIT)で親の終了を観測し、reapする前に同PGIDへSIGKILLするため、親が先に
正常終了した場合も子への停止要求を省略しない。別waiterやSIGCHLD自動reapとの併用は禁止。
親waitは5秒上限。例外は外側へ伝え、外側controllerが通信復元・VM停止を必ず実行する。

専用WSLの合成実プロセスで正常/非ゼロ終了・タイムアウト・親正常終了後の子heartbeat停止・
大量出力抑制・継承FD遮断・private umaskを検証し、関連54tests成功。
返すのはleader_reapedとprocess_group_stop_requestedであり、シグナル送信を全子停止の
証明にしない。all_descendants_stopped=Falseを維持し、setsid等による別groupの可能性は
外側VM停止で扱う。実CLI起動、停止後再起動して行うexport採取、通信復元への接続は未完了。

## 予約から単発起動への接続

`mcp_probe_launch.launch_reserved` は保存済み予約とlocatorを読み、before snapshot、
trusted callerによる同guestのfresh catalog確認、exact Free/期限検証、launch.jsonの
排他的作成・fsync、再snapshotを経て固定CLIをnormal/no-resumeで一度だけ起動する。
起動記録はnonce/work/入力hash/予約hash/catalog hash/argv hashを結び付ける。
最大90秒とキャンペーン残時間・関数開始から120秒の残時間で起動timeoutを制限する。
catalog callback自体の20秒制限・出力上限はtrusted callerが実装する責務。
spawn失敗・タイムアウト・保存失敗でもlaunch記録を削除せず再実行を拒否する。

終了票はawaiting_vm_stop/passed=False。実CLI起動をmockした接続試験と既存回帰60tests成功。
公開entrypointはまだなく、managed VM/global lock/継承MCP設定検査/限定networkの実接続前に
この関数を直接呼ばない。実CLI受入・停止後のexport採取と照合は引き続き未完了。

## 実machineの設定候補メタデータ

固定保守action `--inspect-mcp-config-locations` を追加。設定内容を開かずlstatのみ行い、
環境変数は固定キーの存在とHOME一致booleanだけを返す。関連44tests成功。
実行証拠 `/home/fleet/controller-validation/mcp-locations-y9k4rrzj/receipt.json`:
user_mainとuser_mcpは通常ファイルとして存在。user rules/skills、home/tmp/rootの.devin
候補、tmp/rootの.git/.jj、/etc/devin/system.jsonは不存在。XDG等固定overrideキーは
未設定、HOMEは期待値一致。network_changed=False、model_executed=False、全11VM停止。
設定の内容・秘密値は未取得であり、configuration_isolated=Falseを維持する。

公式 https://docs.devin.ai/cli/reference/configuration/global-vs-local では、MCPは名前ごとに
mergeされ、hooksは複数層から収集される。project rootは.git/.jjを探索する。
共通MCPファイルが存在するので、試験用設定だけと推定して実CLIを起動しない。
次は共通設定の構造を秘密値非出力で確認し、継承とproject discoveryを解決してから実試験へ進む。

## 共通設定の構造確認と属性上の未確認点

固定保守action `--inspect-mcp-config-shape` は2設定だけをVM内で解析し、任意キー名・
URL・command・env値・raw JSON・例外本文を出力しない。認証ストアは開かないが、
設定に埋め込まれた値は解析時にメモリへ入るため「秘密値を一切読まない」とは表現しない。
初期の合成/保守回帰47tests成功。

実証拠 `/home/fleet/controller-validation/mcp-shape-p9rey48c/receipt.json`:
通常config.jsonはMCP登録0件、hooks absent。共通mcp_config.jsonはregular/期待所有者/
single-link/サイズ上限を満たすが、groupまたはotherのwrite bitがあるため読取guardで拒否。
MCP内容は未解析で、空・無効とは判断できない。設定のchmod/移動/削除は行っていない。
network_changed=False、model_executed=False、all_vms_stopped=True。
先行診断 w3_gzk6x/ps64lsyf も同じファイルの未確認状態であり、モデル試行ではない。

## 読み取り診断と実行許可の分離

`mcp_config_shape.collect(diagnostic=True)` を追加。strict defaultはprotected属性での
拒否を維持する。診断だけはgroup/other writeがあっても他の読取条件と前後同一性検査を
維持して解析し、status=parsed_untrusted、configuration_isolated=Falseとして返す。
権限変更はせず、これを起動admissionへ接続しない。関連48tests成功。

実証拠 `/home/fleet/controller-validation/mcp-shape-ak6tkfd4/receipt.json`:
mainはMCP0件/hooks absent。共通MCPはremote1件/disabled0件/stdio0件/hooks absent。
名前・URL・値は出力していない。network_changed=False、model_executed=False、全VM停止。
既存remoteを読み込む可能性が確認されたので、fixtureだけの設定とみなさない。
公式commandsページでは確認範囲にstrict MCP専用overrideは見つからない。
https://docs.devin.ai/cli/reference/commands
次は既存共通設定を変更せず、試験work内で同名disabled overrideを適用できるか、
installed CLIの設定一覧で確認する。名前はVM内だけで扱い、モデル試行前にdiscovery対象を限定する。

## installed CLIのproject override観測

`--inspect-mcp-override` を追加。固定共通設定の名前だけをVM内で使い、private synthetic
Git rootのproject MCP設定に同名disabled overrideとfleet-probeを作る。全commandは
/usr/bin/falseへ置換し、既存URL/env値をコピーしない。mainのhooksや移行前MCPがある場合は拒否。
通信全拒否のままCLI mcp list/getだけを実行し、モデルは起動しない。関連52tests成功。

実証拠 `/home/fleet/controller-validation/mcp-override-vvaeoa68/receipt.json`:
list/get fixture/get inheritedはいずれもrc0、stdoutはそれぞれ8/2/3行で非JSON。
global_config_unchanged=True、network_changed=False、all_vms_stopped=True。
unknown出力を合格にせずoverride_verified=Falseを維持。次は人間向け出力の固定書式を
秘密値非出力で把握する必要がある。CLIの終了成功だけではdisabled適用を証明しない。
試験用private workは証拠としてVM内に残し、既存設定・認証ストアは変更しない。

## project overrideの表示一致確認

`display_tokens` は有限語彙への診断用変換のみ。合格判定には使わない。
`exact_get_display` はraw出力に対し、対象Server名・/usr/bin/false command・disabled状態と
固定理由の全行一致を要求する。余分な行、別名、コマンド部分一致、ANSI付き出力は拒否。
関連54tests成功。

実証拠 `/home/fleet/controller-validation/mcp-override-erevyepi/receipt.json`:
fixtureと既存serverのgetでexact_get_override_display=True。既存serverはdisabled、
両方のcommandは固定falseとして表示される。共通設定bytes不変、通信未変更、全VM停止。
これでこのprivate Git rootにおける設定表示上のoverride適用を確認できた。
ただし実fixture discovery/モデル呼出し拒否/全設定層の隔離の証明ではないため、
全体override_verified=Falseは維持する。次はこの同名disabled overrideとproject-root境界を
予約済みMCP単発試験へ接続する。今回のconfig-only試験ではモデルは実行していない。

## 単発予約へのoverrideと探索境界の統合

`make_input_builder` は固定共通MCPの名前だけを捕捉し、同名disabled/false commandを
試験用MCP設定へ追加する。URL/env値はコピーしない。fixture名との衝突・重複名を拒否。
固定入力は9件へ拡張した（従来6件＋.git/HEAD＋.git/config＋inherited-mcp.sha256）。
private Git rootと空objects/refsを作成・fsyncし、snapshotはGitファイル内容とdirectoryを
検査する。.devinの余分なlocal設定も拒否する。旧6入力予約は再利用・自動変換しない。

起動経路は元MCP設定のdigestをcatalog前とCLI起動直前に再照合する。未結合や変更は
拒否し、起動予約が作成済みなら保持する。digestはprivate予約内の整合性確認用で、
設定内容や任意値をログに出さない。通常config/hooksなど全層の継続的な不変性や
実モデルによる拒否はまだ証明していない。外側managed VM/network接続も未完了。

## fresh catalog取得の接続

`mcp_probe_catalog.read_catalog` を `launch_reserved` の既定処理へ接続した。
固定reserved workとconfigを使い、CLI models list --format jsonだけを呼ぶ。
単一20秒deadline、stdout1MiB/stderr64KiBの累積上限、nonblocking同時drainを使い、
超過やtimeoutは切り詰めず失敗とする。stderr本文を戻さずログにも出さない。
leaderはWNOWAITで保持し、終了経路でgroup停止要求・reap・pipe closeを行う。
catalog前にも予約入力/共通MCP照合とキャンペーン期限検査を適用する。

合成実プロセスによる出力超過・タイムアウト・stderr非出力と、default接続のmock試験を
含むMCP関連73tests成功。実CLIカタログの新規取得やモデル試験はこの検証では行っていない。
catalog CLI起動も継承hooks等の影響を受け得るため、外側の全設定層検査・限定通信・
VM停止への接続を省略して実行してはならない。

## 実machineへの準備専用配置

`--prepare-mcp-probe` は固定10 moduleを名前・個別hash・展開サイズを検査してguestへ配置する。
固定state `/home/agent/.local/state/e-base-mcp-maintenance-v1` は排他的作成し、親もnofollowで辿る。
既存stateは再使用せず、途中失敗でも削除しない。共通MCPから名前だけを取得して無効化設定、
Git root、nonce監査と9入力を準備・fsyncし、before snapshotを実行する。
CLI/モデルを呼ばず、prepare-onlyマーカーを残す。launch_reservedはこのマーカーがあれば
catalog前に拒否する。過去session一覧はまだ未確認で、準備を本番admissionに昇格させない。

実証拠 `/home/fleet/controller-validation/mcp-prepare-yp8c_8l9/receipt.json`:
prepared=True、input_count=9、model_executed=False、production_admitted=False、
previous_session_inventory_verified=False、network_changed=False、all_vms_stopped=True。
準備領域と予約は実VM内に保持済み。このprepare actionを再実行して作り直してはならない。
関連109tests成功。次は保存済み準備の読取検証と、残る実行admission/停止後回収への接続を行う。
# Prepared-state restart observation

## Reviewed CLI installation link accepted with unchanged binary pin

Actual metadata evidence `auth-interface-arp45ebl` showed the fixed CLI symlink
targets `/home/agent/.local/share/devin/cli/_versions/current/bin/devin`, an owned,
protected executable regular file. `_verify_install` now accepts only this exact
logical link, resolves the version indirection strictly within the canonical
reviewed `_versions` root, checks protected directories, hashes the final regular
file with O_NOFOLLOW and the unchanged reviewed pin, then rechecks link identity
and resolution. Arbitrary links, storage escape and changed bytes remain refused.
Access-time changes caused by reading are not treated as content modification.

Synthetic tests passed 210 in 1.511s. Actual pinned preflight succeeded:
`/home/fleet/controller-validation/auth-interface-t1nbd6km/receipt.json`.
The existing reservation and scoped empty history still matched; network was
unchanged, model execution false, no admission consumed. All VMs stopped and
managed service inactive/dead/PID0 independently confirmed. This resolves the
installation-format mismatch, not the remaining live lifecycle/signal acceptance.

## CLI identity gate: actual install indirection discovered

Added bounded streaming verification against the previously observed CLI SHA256
9926e1e6e0f3071398759efd1414609a8a54762d08a01bb301f4407d1caccf5a,
with regular/executable/owner/protected-mode checks and before/after/path metadata
comparison. Dispatch checks it before inventory/catalog/model; remaining-time
budgets are computed after hashing. Synthetic tests passed 208 in 1.528s.

Actual preflight `/home/fleet/controller-validation/auth-interface-evjqr79v`
failed before CLI execution: O_NOFOLLOW returned ELOOP for the fixed
`/home/agent/.local/bin/devin-cli` path. This establishes an installation symlink,
not malicious modification or a changed digest. Model execution did not occur;
managed cleanup completed and service inactive/dead/PID0 was independently read.
Next step is read-only metadata inspection of the exact CLI symlink chain and
binding the reviewed real executable to that chain. Do not drop no-follow checks
globally or automatically accept a new executable hash. Live activation remains
unavailable pending this check and signal-cleanup review.

## Outer lifecycle library connected (no activation command)

`mcp_probe_lifecycle.run_probe` now composes locked registration revalidation,
closed policy and host/guest boundary checks before CLI preflight, the fixed
one-shot network window, guest dispatch, network closure/model lease stop,
eleven-VM inventory and closed-policy observation, durable model-stop receipt,
a distinct offline inspection lease, bound collection, and final inspection
shutdown/inventory. The saved admission/stop **file bytes** are exactly those
sent to the guest and hashed against collection output. No retry, production
promotion, reservation clearing or public activation CLI is added.

The maintenance network wrapper additionally rereads the protected current
registration before and after boundary checks, refusing stale caller objects
before policy mutation. Guest boundary validation precedes even preflight CLI
inventory, not just model dispatch. Stateful synthetic lifecycle tests verify
close-before-stop, stop-before-collection, final inspection stop, exception
cleanup, foreign evidence rejection and stale registry rejection. Combined tests
passed 204 in 1.522s in dedicated WSL. All permission acceptance flags remain
false; no real invocation of this lifecycle library has occurred. Before a live
entry is enabled, its managed-service/signal cleanup and installed-CLI identity
must be reviewed and bound, then the actual one-shot result inspected.

## Offline evidence collector connected internally

`mcp_probe_collect.collect` binds exact stored reservation/admission/launch/process
records to an outer-provided stop receipt (fixed machine, model lease, nonce and
reservation hash). Inspection requires a different lease ID. It reconstructs the
fixed no-resume argv, verifies reserved input hashes, reads one bounded after
snapshot and binds those same audit/export bytes. It rechecks claim bytes after
collection and emits finite verdict fields and hashes, never raw export or raw
session IDs. Expired historic admission receipts are not rejected merely because
collection occurs later; this does not certify actual launch timing.

The trusted-source bootstrap now has an internal collect branch with seven
support modules. Collection does not execute stored guest source/cache files.
`passed=false`, `live_execution_verified=false` and `inspection_vm_stopped=false`
remain explicit: outer stop-receipt provenance and inspection final shutdown
must still be observed and checked by the lifecycle owner. No public model or
collector command has been enabled. Synthetic tests passed 199 in 1.518s; no
real model run, network opening or real post-model collection occurred here.

## Trusted guest dispatch preflight connected

`guest_mcp_dispatch` loads the baseline prepared-state inspector and six exact
support modules from bounded, hashed trusted outer source bundles, not guest
cached bytecode. Its internal dispatch validates schema-2 admission binding and
expiry, obtains a fresh exact-workdir empty inventory, and delegates the one-shot
launch. The public maintenance command exposes **preflight only**, not dispatch.
The outer live network/lease owner and final stopped-evidence collection are
still required before the internal model path can be activated.

The combined mock suite passed 194 tests in 1.519s. Actual fixed
`--mcp-dispatch-preflight` evidence:
`/home/fleet/controller-validation/auth-interface-446h734o/receipt.json`.
Trusted bundle bootstrap, existing reservation binding and scoped empty CLI
inventory succeeded in the real machine VM. Before/after prepared input and
inherited config checks passed. Model execution and production admission were
false, network unchanged, all VMs stopped, managed service inactive/dead/PID0.
No admission was consumed, no guest preparation was recreated, and no global
session-inventory or live permission-denial acceptance is claimed.

## Fixed maintenance network wrapper

`mcp_maintenance_network.machine_probe_network` is an internal one-shot wrapper,
not a public command. It requires production=false, capacity one, the exact
machine VM/active lease/global lock, the protected fixed controller root, no
STOP, and live pinned boundary checks. It exclusively creates `mcp-live-v1`,
fsyncs the parent and reservation, then enters the existing restricted-model-host
policy engine. A partial reservation is retained and blocks subsequent runtime
entry via the restart guard. Existing reservations cannot be reused, even closed.

The yielded remaining timeout must bound every command in the trusted caller;
this context manager is not an independent background watchdog. It also checks
deadline/STOP on body return. Exceptions poison the runtime and stop the VM after
policy cleanup; closure failure retains inspection-required state. No production
registration is changed. Stateful mock tests cover exact identity/lock/root,
write failure without policy mutation, uncertain removal, body/closure/deadline
failure, repeat refusal and restart gate behavior. The combined dedicated-WSL
suite passed 189 tests in 1.509s. The actual fixed run remains uncreated and
the wrapper has not opened real networking. Guest single-attempt dispatch and
final stopped-evidence collection remain to be connected before activation.

## Maintenance restart gate before network activation

The network policy engine is shared internally while the existing production
wrapper still requires explicit production registration and its durable role
fence. The internal engine retains namespace, lock, active lease/VM, root and
timeout checks; it is not a public admission API.

`mcp_maintenance_restart.require_closed_maintenance` is now called from every
`SandboxRuntime` entry, including non-production maintenance. Presence of the
fixed `/home/fleet/controller-validation/mcp-live-v1` run requires an exact
reservation and closed network journal. Partial/missing/unknown/open state
refuses runtime entry before VM resume. Even closed journals require live
blanket-denial verification and unchanged journal bytes after that verification.
No marker is removed and no recovery is attempted automatically.

The fixed run has not been created and no maintenance network-opening wrapper
or live activation has run. The future wrapper must durably create
`network-attempt.json` with schema 1, fixed machine ID, the exact run directory,
state `reserved`, and `automatic_resume=false` before policy mutation. Its policy
journal belongs at `network-window/network-window.json`. These are separate from
the existing guest preparation, which remains unchanged. Dedicated-WSL mock
tests (including runtime, network policy/failure restoration and MCP tests)
passed 180 tests in 1.504s; this is not PC-reboot or live model acceptance.

## Schema 2: scoped inventory and fresh-attempt preconditions

Supervised admission now requires schema 2, `session_inventory_scope=current_workdir`,
`session_inventory_verified=true`, and `fresh_attempt_preconditions_verified=true`.
Old ambiguous schema-1 receipts are rejected, not upgraded. The last field means
only that reserved inputs and work met launch preconditions; it proves neither
CLI invocation, new session creation, permission denial, nor process termination.
The consumer independently snapshots inputs/empty audit/absent export and checks
unchanged reservation bytes and absent launch marker before and after the trusted
callback. Only exclusive admission-journal creation can advance toward the CLI.

`read_empty_workdir_inventory` binds its fixed list command to the exact private
workdir and requires rc=0 with an explicit empty JSON array. Nonempty lists,
unknown schemas, failed commands and missing output are rejected, never coerced
to empty. It is an internal supervisor helper, not an account-wide inventory.
The original reservation and guest hold remain unchanged. The dedicated-WSL
mock suite passed 130 tests in 1.482s. No actual model or new live admission was
run. Outer same-lease lock/VM/network checks and stopped evidence are still to
be connected; receipt declarations alone do not supply them.

## Actual offline CLI history-shape observation

Installed CLI follow-up: `list --help` exposed only `--format` and `--help`.
Evidence `/home/fleet/controller-validation/auth-interface-nfnup2ou/receipt.json`;
both help and workdir list succeeded, list remained empty, all VMs stopped,
network unchanged, no model. The suite passed 128 tests in 1.455s. This establishes
no documented all-directory switch in this installed command's help, not the
absence of every possible CLI/internal mechanism. Do not scan session bodies
or credentials to compensate. Workdir-scoped freshness and global historical
uniqueness are separate claims; admission remains unissued pending that review.

Design review conclusion: account-wide session enumeration is not required for
the bounded MCP denial experiment. It would not prove actual invocation or
evidence provenance. The required claim is a fresh exclusive attempt: private
work, fresh nonce, fixed empty-audit inode, absent prior export, exact trusted
CLI/config/argv with no resume/continue, one invocation, linked discovery and
denial evidence with zero fixture calls, unchanged inputs, final evidence hashes
and verified outer VM stop. This assumes the trusted-supervisor boundary, not
hostile guest-root attestation. Workdir history is supplementary evidence only.
Before issuing a live admission, change its currently ambiguous history contract
to carry explicit inventory scope and fresh-attempt preconditions separately;
never satisfy an account-wide claim by assigning true to an empty local list.
Existing known-session inclusion checks may remain as an additional defense.

Official commands reference https://docs.devin.ai/cli/reference/commands documents
`list --format json` as current-directory scoped, not account-wide inventory.
The fixed `--inspect-mcp-history` maintenance action ran this command inside
the existing prepared private workdir, with its fixed config and blanket network
denial retained. Raw session output stays in guest memory; only finite schema
shape, count and return code are exported. Prepared inputs and the hold were
checked, and common config bytes were checked before/after the command.

Actual evidence: `/home/fleet/controller-validation/auth-interface-utwfookb/receipt.json`.
Return code 0, JSON list, count 0. `history_verified=false` intentionally remains:
this does not enumerate other directories or authenticate the account. Model
execution and network changes are false; all VMs and managed service stopped.
The related maintenance suite passed 127 tests in 1.459s. No supervised
admission was issued or consumed, and no prepared state was recreated.

## Supervised one-shot library path (not live-connected)

`launch_reserved(..., supervised_check=...)` can now retain a valid prepare-only
hold while accepting a fresh trusted-controller callback. No public command
supplies this callback. It must perform actual same-lease lock, VM, boundary,
network and complete session-history checks; receipt contents alone do not
prove those checks happened. Its bounded raw receipt binds the original
reservation hash, nonce, work, fixed machine VM, lease ID, lifetime of at most
120 seconds, and prior session IDs. The original reservation is never rewritten.

The receipt is exclusively persisted and fsynced before the catalog CLI. Once
consumed, catalog failure also prevents re-entry. The launch record includes
the receipt and its hash; the hold and receipt bytes are rechecked before model
spawn, whose timeout is also capped by receipt expiry. Default calls still
reject a preparation hold. `bind_supervised_probe` uses the admitted history
instead of the preparation's unverified empty history, while keeping `passed`
and live-execution acceptance false. The dedicated-WSL synthetic suite passed
123 tests in 1.489s; no live guest, CLI, network window or model was started.
The catalog capture timeout is capped by remaining admission/campaign/global
time as well as its 20-second maximum. Final history binding rejects an admitted
inventory that omits any session already known to the original reservation.
Outer callback implementation and live stopped-evidence binding remain required.

Follow-up controller verification: 115 maintenance tests passed (1.627s).
Fresh-process synthetic preparation/inspection covers the valid state and
changed input, dangling launch marker, missing hold, changed controller source,
and world-writable cache rejection. These are not live guest/model tests.
`mcp_probe_launch` now rejects global main-config hooks and pending legacy MCP
migration before the catalog CLI starts, binds the main-config digest in the
attempt record, and rechecks it before model spawn. A changed config retains
the consumed attempt and prevents spawn. The live prepared state is unchanged.
Remaining live wiring includes supervised admission without deleting the hold,
session-history evidence, and outer VM/network/final-stop evidence binding.

The fixed read-only `--inspect-mcp-prepared` maintenance action verified the
existing guest preparation after VM restart. Evidence:
`/home/fleet/controller-validation/mcp-prepared-state-mfedljfl/receipt.json`.
All nine inputs matched, the prepare-only hold remained, and no launch record
existed. Stored controller sources matched the trusted outer source bundle;
inspection executed the outer bundle, not guest source or cached bytecode.
The optional inert Python cache directory is checked but never loaded.
The related maintenance suite passed 112 tests. Network restrictions were not
changed, no model executed, all VMs stopped, and the managed service stopped.
This is not PC reboot acceptance, live MCP denial proof, authentication proof,
or admission to production. The existing reservation must not be recreated.
