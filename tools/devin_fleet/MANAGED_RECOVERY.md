# 専用環境の復旧：状態確認とmachine通信閉鎖

対象は `EBase-Sandboxes` だけです。Devin の再開、生成コードの実行、
自動起動の有効化、旧 STOP の解除はこの手順に含みません。

## 専用ディストリビューション停止・起動の実測（2026-09-19）

実編集の完了後、全11VM停止・管理サービスinactive/dead/MainPID=0を確認して、
`wsl --terminate EBase-Sandboxes` を実行。続く `wsl --list --running --quiet`
は空で、専用ディストリビューションの停止を確認した。
他ディストリビューションやPC全体の終了操作はしていない。

その後、同ディストリビューションを起動して確認：

- 管理サービスはinactive/dead/MainPID=0のまま。自動モデル再開なし。
- `/tmp/e-base-devin-fleet-global.lock` はfleet:fleet、0600。
- 通信拒否のまま `launch_machine_auth.py --eword-evidence` を実行。
  この固定操作はCLIやモデルを呼ばず、既存markerと候補・exportだけを照合する。
- 停止前receipt: `/home/fleet/controller-validation/interactive-auth-834vtkz1/receipt.json`
- 起動後receipt: `/home/fleet/controller-validation/interactive-auth-snp0occy/receipt.json`
- 両方ともpassed=true、reservation_preserved=true、tool_scope_verified=true。
- 予約SHA256: `79c6b283d62dcb9485a36f2242b4e6bcf0eb3aee7ee6b6add93825883eb1156d`
- 候補SHA256: `9a4b52142e99a7acb226c483a9ce78597e37686b1b635405795ebc80ddb5baaf`
- export SHA256: `75ab8262a510ccd00b7d08224ae29adb1bdf64598cd6109cd693303249a5e261`
- 両方ともmodel_executed=false、candidate_executed=false、resume_available=false。
- 通信拒否・全VM停止・cleanup_errors=[]、ランチャーの管理サービス停止確認。

関連モック56件成功（0.044秒）。破損marker、重複JSONキー、余分なディレクトリ、
候補/exportのhash不一致、tool監査不一致を拒否し、CLI起動・予約削除を行わない。
予約が存在することを確認したのであって、実モデルを再投入して拒否させる試験ではない。

前後のLinux kernel boot IDはどちらも
`d25503e2-0677-43ab-a104-c0e6f7f72aaf`。共有カーネルの再起動は立証していない。
これは停止済み作業の記録保持と読み取り再確認の証拠に限定し、Windows再起動、
停電、推論/候補回収/検証の途中中断、10並列復帰や自動継続の合格にはしない。
残る9担当の本人認証、本番admissionと継続運転の確認は別途必要。

## 一時通信許可中に処理が中断した場合

machine以外の固定担当にも、`--recover-role coordinator` のように閉鎖専用の
復旧入口を使える。受理する担当名は登録済み10担当だけ。対象UUIDも固定する。
ログイン用の `--login-role` とは別であり、復旧入口は認証・推論を開始しない。

通常終了・扱えるシグナルでは後処理が動きますが、電源断や強制終了で
後処理が必ず完了するとは保証しません。再開前に下記の固定操作を使えます。

```powershell
wsl -d EBase-Sandboxes -u root --exec /usr/bin/python3 -I /home/fleet/controller-validation/launch_machine_auth.py --recover-machine-deny
```

管理サービス停止・全11VM停止・machine UUIDを前提に、machine限定の
network deny `**` を確認し、ない場合だけ追加します。既存ルールは削除しません。
稼働中VMや不明な状態は拒否します。VM・モデル・旧ジョブは再開しません。
固定管理入口・大域ロックを使い、確認後に管理サービスを停止します。
子操作が失敗した場合、ランチャーも成功終了せず失敗を返します。

2026-09-19の実機結果：専用WSLの
`/home/fleet/controller-validation/network-recovery-ox4jns2d/receipt.json`。
`added_blanket_deny=false`, `network_denied_after=true`, `all_vms_stopped=true`,
`model_executed=false`, `rules_removed=false`, `resume_available=false`。
既存拒否ありの冪等動作を確認。拒否欠落時の追加・稼働中拒否・検証失敗は
モックテストで確認し、電源断による欠落の実機再現は未実施です。

## 再起動後

1. 専用環境を起動し、ロックが fleet 所有・0600 で存在することを確認します。
   起動時の tmpfiles 設定が作成します。存在しない・所有者が違う場合は
   手動削除・上書きをせず、その場で止めて調査してください。
2. 管理サービスだけを明示的に起動します。
3. 管理者用入口で全11環境の状態を確認します。
4. 全て停止状態であることを確認し、保守用コントローラーの状態を確認します。
5. 確認が終わったら管理サービスを停止します。

PowerShell からの各操作（失敗したら次へ進まないこと）：

```powershell
wsl -d EBase-Sandboxes -u root --exec stat -c '%U:%G %a %n' /tmp/e-base-devin-fleet-global.lock
wsl -d EBase-Sandboxes -u root --exec systemctl start e-base-sandboxd.service
wsl -d EBase-Sandboxes -u root --exec /usr/bin/python3 -I /usr/local/libexec/e-base-managed-status.py
wsl -d EBase-Sandboxes -u root --exec /usr/bin/python3 -I /usr/local/libexec/e-base-managed-status.py --controller-status
wsl -d EBase-Sandboxes -u root --exec systemctl stop e-base-sandboxd.service
```

状態確認に失敗した場合も、今回起動した管理サービスは停止してください。
起動直後の準備待ちで失敗した場合は、サービス状態を調べてから状態確認だけを
再試行できます。別の通常モード管理プロセスを起動してはいけません。

確認すべき結果は、全11環境 `stopped`、コントローラー `maintenance_only`、
`resume_available=false` です。ここでの `stop_requested` は保守用ディレクトリ
だけの状態で、Windows側の旧 STOP の状態ではありません。

## レビュー待ち候補のローカル確認

管理サービスを起動せずに実行できます。モデル/Git実行、通信、STOP/fence解除はしません。
以下は保守rootに対する実行例です。現登録には本番controller_root/migration_epochが
ないため、実測結果は `registration_missing_or_mismatched` です。
「候補なし」「運転可能」とは異なります。この表示を消すためだけに登録を書換えないでください。

```powershell
wsl -d EBase-Sandboxes -u fleet --exec python3 /home/fleet/controller-validation/sandbox_driver.py --registry /home/fleet/controller-validation/sandbox-registry.json --root /home/fleet/controller-validation/managed-maintenance inspect-candidates
```

本番rootが正式登録された後の一覧は次を区別します。

- `pending_review`: 保存した元証拠とbundleの照合成功。公開・承認・実VM停止の現在確認ではない。
- `incomplete`: 必要ファイル欠落。途中保存の可能性があるため、再実行や削除をしない。
- `inspection_required`: 破損・不一致など。元の記録と実行予約を保持する。
- `partial_inventory` / `inventory_limit_exceeded`: 全件を確認していない。未確認を正常と解釈しない。

一覧の詳細検証は32件、directory探索は256件が上限です。既知operationを個別確認する
場合は同じregistry/root指定で `inspect-candidate --operation <32桁のoperation ID>` を使います。
これは疑似引数表記です。実際の一覧にあるIDを指定し、推測したIDや別rootのIDを使わないでください。

いずれの結果でも `resume_available=false`、`runtime_state_observed=false` です。
`inventory_complete=true` は列挙・検査対象の網羅性だけを示します。
破損したrecordがある場合もtrueになり得るため、各recordのstateを必ず確認してください。
このコマンド自体に修復・再開・削除機能はありません。

検証実績: 専用WSLで関連47テスト成功（0.035秒）。12件は独立作成の一覧/CLIテスト。
現保守rootでの実CLIも未登録を明示し、管理サービスinactive/dead/MainPID=0を維持。

## 引き続き未完了の復旧・運転機能

未解決記録の読み取り専用検査は、管理サービス停止中でも実行できます。
以下は**保守用ディレクトリだけ**の検査です。本番・旧環境全体の確認ではありません。

```powershell
wsl -d EBase-Sandboxes -u fleet --exec python3 /home/fleet/controller-validation/sandbox_driver.py --registry /home/fleet/controller-validation/sandbox-registry.json --root /home/fleet/controller-validation/managed-maintenance inspect-turns
```

`absent` は選択した管理ディレクトリに記録がない状態です。`unresolved`、
`invalid`、`identity_mismatch` は、いずれも確認が必要な状態です。
どの結果でも、このコマンドはVMの停止や作業の合格を証明せず、再開を許可しません。
停止指示や既存の記録は変更しません。

- 本番用管理ディレクトリの `model-turn-fences/<担当名>.json` は、未解決の実行を
  再開させないための記録です。空・途中書き込み・検証待ちでも再実行を拒否します。
  出力先や実行番号を変えて再試行したり、記録を削除したりしないでください。
  本番の管理ディレクトリは信頼済み登録の `controller_root` と一致する必要があります。
  確認後にこの記録を安全に解決する手順はまだ未実装です。
- ロックファイルを削除して競合を解消しないでください。
- 外側から直接 sbx を操作したり、従来の実験用スクリプトで通常管理プロセスを
  復元したりしないでください。更新済みの通常入口は隔離外の操作を拒否します。
- `managed_cutover.py` は旧管理プロセスからの初回移行用であり、再起動復旧用ではありません。
- 専用WSLの再起動と状態確認は実機検証済みですが、PC全体の再起動、実行途中の
  Devinジョブの復旧、自動連続実行、10セッション同時実行は未検証です。
- systemd サービスを起動しただけでは、WSL環境が永続稼働するとは限りません。
  常時稼働の管理方式は別途整備が必要です。

## モデル通信窓の閉鎖専用復旧

本番登録後の固定入口です。現在のproduction=false登録では操作前に拒否されます。
このコマンドを通す目的で登録を書き換えたり、STOPを消したりしないでください。

```powershell
wsl -d EBase-Sandboxes -u root --exec /usr/bin/python3 -I /home/fleet/controller-validation/launch_machine_auth.py --recover-model-network machine
```

末尾は登録済み担当名だけです。任意パス・VM ID・追加オプションは使えません。
既存管理サービスは停止状態、全11VMも停止状態であることが前提です。
途中実行のhandleが残る場合はまずその停止・状態確認を行い、復旧を重ねて起動しません。

処理は対象担当への全通信拒否の追加と照合だけです。元window記録・model fence・STOPを
変更せず、独立したrecovery/recovery.jsonに元記録のhashと閉鎖結果を保存します。
成功は通信閉鎖だけを意味し、モデル成果の合格や次ターンの許可ではありません。
既存recovery directoryがある場合は自動再送せず、inspection_required/部分記録を
保持して内容と現在の状態を確認してください。削除して再試行しないでください。

SIGINT/SIGTERM/SIGHUPは通常の中断経路へ渡します。SIGKILL・電源断では記録が途中で
残り得るため、実クラッシュ試験とPC再起動の受入が済んだという意味ではありません。
2026-09-20、本番無効の実登録で通信操作前の拒否、登録SHA不変、全VM停止、
管理service inactive/dead/MainPID=0を確認済み。本番復旧成功の実測ではありません。
