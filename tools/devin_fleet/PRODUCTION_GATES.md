# 本番運転までの残作業

この一覧は完成条件を縮小するものではない。目的は、専用VMに隔離したDevin CLIの
10担当（調整1＋作業9）がSWE-2で改善を継続し、成果を人間確認用PRへ届けること。
本番登録、容量確認、認証、検証、復旧、公開許可は別々に扱う。

## 現在の停止条件（2026-09-20）

- 実登録はproduction_enabled=false、simultaneous_capacity_verified=1。
  registryをtrue/10に書き換えるだけでは受入完了にならない。
- 実VM境界検査callbackと固定単発library入口は接続済み。運用CLI・本番登録への
  切替と実モデル一巡は未受入。
  machineのmetadata観測でvirtiofs 2件、Docker socket、SSH_AUTH_SOCK/GH_TOKEN等の
  変数名が存在した。提供元・接続範囲が未分類のため、隔離受入とは扱わない。
- model→credential-free検証→candidate保存の本番一巡は未受入。
- model fenceの終端解決と次ターン開始、10モデル並列schedulerは未完成。
- AUTH_HANDOFF.mdに残る9担当の本人ログイン待ちがある。秘密の複製で代用しない。
- 継続運転のsignal/強制終了/PC再起動の受入は未完了。
- PR公開は別の許可条件を維持し、auto-mergeしない。過去の公開拒否を別経路で迂回しない。

## 実装・検証を混同しないための区分

| 項目 | 現在の証拠 | 残る確認 |
| --- | --- | --- |
| 全拒否policy照合 | machineの実管理APIで16接続先拒否 | 限定開放と復元を含む本番一巡 |
| 通信windowと復元 | 状態付きmock、元記録hash照合 | 実VM通信状態・クラッシュ復旧 |
| 再開gate | private実ファイル＋mock検査、VMresume前配置 | 実運用入口・signal・PC再起動 |
| 復旧CLI | production=falseで実機拒否、mock正常系 | 登録済み本番試行の閉鎖復旧 |
| 単発pipeline | adapter結合のmock、別途保守用検証・候補証拠 | 実モデルから同一turn identityでの一巡 |
| 容量 | 登録値1、10台idleの過去保守記録は別証拠 | 10モデル同時実行と負荷下停止 |

詳細な検証記録はONE_TURN_PIPELINE.md、運用入口はMANAGED_RECOVERY.mdを参照する。
検証用プロセスのSIGKILL試験は、VM障害やPC全体の再起動試験の代わりにはしない。

## machine metadata観測（2026-09-20）

固定保守入口 `launch_machine_auth.py --inspect-guest-boundary` で取得。
証拠: `/home/fleet/controller-validation/guest-boundary-ff8hr0pk/receipt.json`。
前後の全拒否policy検査成功、network_changed=false、all_vms_stopped=true。
秘密値・credentialファイルは未読、外部通信・model・project sourceの実行なし。

- UID1000、logical CPU2、MemTotal4095364KiB（観測値であり資源上限の証明ではない）。
- 13mount中virtiofs2件。任意mount pathは出力しない設計のため接続元は未分類。
- 固定Windows/host共有path、表示socket pathは不在、abstract display socket0件。
- `/var/run/docker.sock` 存在。VM内daemonかホスト共有かは未判定。
- WAYLAND_DISPLAY、SSH_AUTH_SOCK、GH_TOKENの**キーのみ**存在。値・資格内容は未採取。
- metadata parser6件＋関連regressionを合わせ34tests成功（0.277秒）。

この結果をfull_boundary_accepted=trueへ変更しない。次の確認は固定metadata分類で
mountの用途、socket提供元、転送設定を特定すること。秘密の読み取りや実接続で代用しない。

### 固定metadata分類の追試

証拠: `/home/fleet/controller-validation/guest-boundary-sw6ny6lh/receipt.json`。
同じ固定保守入口で、前後の通信全拒否確認・全VM停止に成功。
virtiofs2件の対象は `/etc/resolv.conf` と `/etc/hosts`、双方mountのro属性あり。
filesystem自体の属性はrwであり、共有全体がimmutableであるとは主張しない。
SSH_AUTH_SOCKが示す対象へのlstatはENOENT。変数名の存在は接続可能なSSH agentの証拠ではない。
Docker socketはsocket型、UID0/GID1001、mode0660。提供daemonの所在はなお未確定。
GH_TOKEN・WAYLAND_DISPLAYの値は未読/未出力のまま、提供機構の調査を継続する。
metadata分類とlauncher回帰16tests成功（0.012秒）。初回は関連テストmodule指定の誤記で
import errorとなり、実在するmodule名に修正して再実行した。

公式資料との照合（一般仕様であり実登録の証明ではない）:
- https://docs.docker.com/ai/sandboxes/get-started/ はsandbox毎のDocker daemonを説明する。
- https://docs.docker.com/ai/sandboxes/workflows/authentication/ はGitHub認証の
  proxy-managed placeholderとホスト側credential解決を説明する。
- https://docs.docker.com/ai/sandboxes/security/isolation/ はSSH転送無効時にagentを
  渡さない仕様を説明する。環境変数キーの存在だけで転送有効とは判断しない。
したがって今回のsocket/token変数の存在だけでホスト漏洩とも安全とも断定しない。

### Docker socket所有者のmetadata追試・受信schema強化

証拠: `/home/fleet/controller-validation/guest-boundary-zcp0n3h1/receipt.json`。
固定Docker endpoint inodeは1件。非rootのproc fd観測では2プロセスが読み取り不可で、
dockerd/other ownerいずれも未特定、scan_complete=false。未特定を「所有者なし」や
「ホストへ接続しない」という証明として使用しない。socket接続、cmdline/environ、
descriptor内容の読み取りは行っていない。全VM停止後service inactive/dead/MainPID0を確認。

`guest_boundary_receipt.validate_metadata` を受信処理へ接続した。固定schema・型・範囲、
mount数整合、socket分岐、owner集計、安全フラグの厳密Falseを検証し未知fieldを拒否する。
関連43tests成功（0.058秒）、上記実受信metadataもVM再起動なしで検証成功。
これは観測の形式検証であり、VMからの報告の真正性や隔離受入を証明しない。

次のhost設定確認項目:
- SSH転送設定が明示falseであること（ENOENTだけでは設定無効を証明しない）。
- MCP gateway登録/kit宣言。local stdio MCPはhost実行となり得る別経路。
- 認証kitのGH_TOKEN提供宣言。placeholderかpassthroughかを秘密値ではなく宣言で確認する。
- Docker daemon所在は未確定。現在の非root proc観測だけで確定しない。

### 管理側統合設定の読み取り（2026-09-20）

固定入口 `launch_machine_auth.py --inspect-host-integrations` を追加。
証拠は `/home/fleet/controller-validation/host-integrations-fg1__ztv/receipt.json`、
構造分類追試は `host-integrations-1kq5af8z/receipt.json`。
両方でssh.agentForwardingEnabled=false、clipboard.imagePaste=falseをCLIから確認。
MCP一覧はtop-level servers配列0件とgateway管理metadata。任意名・URL・header・
credential値は保存/出力せず、固定key有無と件数だけ記録した。
これでSSH転送の明示設定は確認済み。clipboard画像無効はtext write無効の証明ではない。
MCP servers0件は当該管理一覧の観測であり、gatewayそのものの無効化は未証明。

管理serviceのみ起動し、VM起動・モデル・MCP接続・認証flow・設定変更は実施していない。
公式 `sbx mcp ls` は内部で認証状態を参照し得るため「秘密ストアに一切触れない」
または「完全offline」とは主張しない:
https://docs.docker.com/reference/cli/sbx/mcp/ls/
kit調査ではremote referenceのinspectは取得を伴い得る。既知のlocal宣言を限定解析し、
`oauth.passthrough`等の属性と登録の対応を確認すること。`sbx kit ls`は公式CLIにない。

### 既存machineのinspect構造確認

公開helpでinstalled `sbx inspect --json` 対応を確認（host-integrations-yl45hz41）。
固定machine登録を読み、値・任意名・secret hashを出さない構造抽出を追加した。
実記録 `/home/fleet/controller-validation/host-integrations-5t2yvu7c/receipt.json`:
root object、name/agent/imageはscalar、kits配列は0件、その他fieldは11件（値未出力）。
既知管理/cache/config/share領域に独立kit宣言の候補は見つからなかった。
追加kit参照一覧だけでは組込みagent/imageのcredential提供機構は分からないため、
公開contrib kitを実登録の証明にせず、組込み側の設定確認へ切り替える。
`kits=[]`は認証未設定・secretなし・host連携なしの証明ではない。

構造抽出は深さ4・配列sample4、既知field名以外を件数だけに縮約。関連8parser tests成功。
VM起動・モデル・設定変更なし、全VM停止とlauncher終了を確認。

### 管理側共有契約の準備

`host-integrations-otvo96r0/receipt.json` で公式namespaceのimage参照
`docker/sandbox-templates:devin-docker`、agent=devinを確認。
`host-integrations-s7hc6tpw/receipt.json` でruntime_mounts配列0件を確認。
これは明示host runtime mountの登録がない証拠であり、内蔵の名前解決用共有や
credential機構が存在しないことを意味しない。

`host_boundary_contract.validate_host_contract` を追加: 既知manager schema、名前/agent/
imageと明示digestの一致、runtime_mounts=[]、kits=[]、SSH/画像clipboardが厳密False、
既知MCP構造のservers=[]を要求。不明項目や共有追加で拒否するpure validator。
関連31tests成功（0.041秒）、service inactive/dead/MainPID0確認。
**まだ本番callbackへ未接続。** image digestの明示pin、実API入力への適用、guest側制限との
結合が次の作業。本検証から本番登録を書き換えたりfull isolation acceptedへ昇格しない。
認証VMは資格情報を利用する役割であり、GH_TOKENの存在だけを追加の禁止理由にせず、
file-only/credential path拒否/限定接続先/生成コード実行禁止を維持した単発一巡を優先する。

### 実管理APIへの契約適用（未合格）

`host_boundary_admission.check_host_boundary` を追加。有限共通deadline、管理namespace、
固定role名、出力bound、同じimage pinで2巡検証し、共有条件の逸脱は例外で拒否する。
保守入口へ接続し、本番登録を変更せず実APIへ適用した。関連22tests成功（0.006秒）。

観測image pin: `sha256:df7d566115e4d16b23a0477be5677ea0eb569de027bc1933238859a6f62293fd`
（host-integrations-77koyfjn）。この観測値を明示固定し、各検査で現在値へ追従しない。
host-integrations-_cwzd66v と host-integrations-wzcgy5iz の実適用は
host_contract_verified=false/ValueError。本番admissionへはまだ未接続。
MCP gateway schemaはdecision/local/name/operator/signed_in_as、local=true。
decisionは文字列だがallow/deny/allowed/deniedのいずれでもない。想定したenumと
実APIが不一致のため、文書/API仕様を確認するまで拒否を維持する。
任意decision文字列・利用者識別子は出力していない。VM起動、モデル、設定変更なし。

### gateway decisionの解釈修正と管理側契約の実測合格

decisionは権限allow/denyではなくgateway routingの選択。過去のenum仮定を修正し、
厳密なlocal=trueかつdecision='local'を要求した。remote/allow/deny/unknownは拒否。
一次観測例 https://github.com/docker/sbx-releases/issues/478 と、
https://docs.docker.com/ai/sandboxes/mcp-gateway/ のlocal gateway説明を参照。
実APIでもdecision='local'を確認した。

証拠 `/home/fleet/controller-validation/host-integrations-6ufcb0yc/receipt.json`:
host_contract_verified=true。固定image digest、runtime_mounts=[]、kits=[]、
SSH/画像clipboard=False、MCPservers=[]とlocal gatewayを2巡確認。
関連37tests成功（0.043秒）。VM/モデル起動・設定変更なし、全VM停止。

これは管理側の限定共有契約のみ。本番boundary callback全体には未接続で、
gatewayには登録serverとは別のbuiltin toolsが存在する。fleet.DENY_TOOLSのmcp__*等、
guest policyの完全一致、実行直前hash再確認が既存の防御だが、実CLIでgateway builtinが
どのpermission名へ写像され拒否されるかの実証は残る。servers0件をgateway無効化の
代替証明にせず、guest policyの検証と単発一巡へ結合する。

### 同一leaseの管理/guest境界checker

`guest_boundary_contract.validate_guest_contract` と
`observed_boundary_admission.make_boundary_check(image_digest)` を追加。
callback署名はmodel_turn_admissionのboundary_checkへ渡せる形だが、本番入口は未接続。
初期段階は管理側のみ、guest段階はactive role/UUID/root/STOP/fenceを照合した同一leaseで
管理側→guest metadata→管理側の順に検査する。guest段階の失敗はVM停止とruntime失敗状態化、
initial管理失敗もruntime再利用を拒否。過去receiptではなくlive観測を使う。

guest契約はUID1000、固定host/displayパス不在、既知Docker socket属性、SSH対象ENOENT、
abstract displayなし、/etc/hostsとresolv.confの2件だけのro virtiofsを確認する。
credentialキーの存在から秘密不存在や漏洩を判断せず、Docker所在・資源上限の証明ともしない。

初回実結合はrunning managerのuptime追加で拒否。診断記録guest-boundary-xzox7l9xで
停止時schemaとの差がuptimeだけであることを確認し、その表示fieldのみoptional化。
ネットワーク/共有/identity条件を緩めず、追加mountは拒否する回帰を追加。
関連45tests成功（0.039秒）。保存済み実guest metadataも限定契約を満たすことを確認。

修正後の実結合記録: `/home/fleet/controller-validation/guest-boundary-nu1kc223/receipt.json`。
observed_boundary_contract_verified=true、前後のnetwork全拒否、network_changed=false、
all_vms_stopped=true。管理serviceもinactive/dead/MainPID0を独立確認。
full_boundary_accepted=falseは維持。これは保守用の同一lease境界検査の成功であり、
MCP権限の実CLI受入・単発本番model一巡・10並列・PC再起動の受入ではない。

### 固定単発library入口へ検査adapterを結合

`registered_turn_guards.make_registered_turn_guards` はproduction=trueかつrole登録に
image_digestが明示pin済みであることを必須とする。登録・ownership・settingsを複製し、
make_admissionへlive境界callbackとnetwork検査を渡す。network scopeは同じ登録/roleを
確認してから共有契約を再検査し、残時間内で限定windowを開き、既存finally復元へ渡す。
構築だけではVM/通信/モデルを起動しない。

`sandbox_one_turn.run_registered_one_turn` を追加。任意admission/network callbackを
呼び出し側が省略・差し替えない固定入口で、既存の検証→candidate→人間review経路へ接続。
運用CLIやproduction登録自動作成、STOP/fence解除、publishは追加していない。
関連87tests成功（0.262秒）。実production=false登録でVM/モデル段階より前の拒否を確認。
登録bytes前後同一、SHA256 afd5e5f94691c2237cde2219e114fbc66ad95acff57f7be87b0663756874c9bf。
管理service inactive/dead/MainPID0を確認。

Devin公式permissionsはmcp__*を全MCP toolsに一致すると説明する:
https://docs.devin.ai/cli/reference/permissions
公式commands/permissions/MCP configurationを調べた範囲では、モデル非実行のpermission
check/dry-runは見つからない。mcp list/getは設定表示であり拒否試験ではない。
拒否指定の公式仕様上の裏付けとinstalled CLIの実拒否を区別する。server起動禁止は
disabled:trueの別条件であり、tool拒否だけでdiscovery無効を主張しない。

MCP実拒否試験の固定fixtureとpure export classifierを追加した。準備/未接続部分は
MCP_DENIAL_ACCEPTANCE.md参照。関連22tests成功（0.018秒）だが実モデル試験は未実施。
通常configへのMCP設定埋込みは自動migration副作用があるため、専用workdirの
.devin/mcp_config.jsonを使用する設計。旧shell/file/ewordの予約や試行を再利用しない。

固定fixtureイベントauditを追加し、同一試行内のdiscovery/拒否照合の準備を進めた。
関連23tests成功（0.016秒）。独立handshakeをCLI discovery証拠として流用せず、
session未結合の判定はpassed=Falseを維持する。実CLI/fixture server/modelは未起動。
専用workdir・排他的予約・nonce/config/fixture/sessionの結合と、通信復元付き実試験は残る。
