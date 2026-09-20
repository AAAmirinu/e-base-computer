# Git候補作成用の派生イメージ（ビルド・synthetic Git確認済み）

## 確認済み

- 既存イメージID: `sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f`
- OS実測: Debian13/trixie、aptあり、Gitなし。
- 取得元実測: `http://deb.debian.org/debian` と `/debian-security`。
- 証拠: `/home/fleet/controller-validation/git-capability-of1l_mlq/receipt.json`。
- mode=image_infoの読取り確認に成功。Gitコミット成功ではない。
- 通信拒否を維持し、コンテナ・全11VM・管理サービス停止を確認。

## 準備したレシピ

`validation_git.Dockerfile` と `install_validation_git.py`。
既存イメージとは別の派生イメージを作り、2つの既定Debian取得元だけをHTTPSへ
変更する。未知のhost/suite/署名設定・追加取得元は拒否する。
APT/TLS署名検証を無効化せず、Gitと必須依存関係だけを導入する。
インストール結果のGitパッケージversionをイメージ内に記録する。
参照: https://wiki.debian.org/SourcesList

取得元変換の14件と既存保守入口を含む38テスト成功（専用WSL、0.018秒）。
APT/subprocess起動を禁止した純粋関数テストであり、実導入やビルド成功ではない。

## 実ビルド前の条件

以下の条件で、検証VMだけの一時通信を伴う実ビルドを実施する。
外側WSLやWindows、認証済み担当VMでinstallerを直接実行しない。

1. 専用validation VMのUUID、全11VM停止、排他ロックを確認。
2. 既存イメージのIDとDockerfile用local tagのIDを完全照合。
   同名tagが別IDなら上書きせず停止。既存の検証イメージは変更しない。
3. 固定2ファイルだけの空に近いbuild contextを使う。プロジェクト、認証、
   ホストディレクトリをマウント/コピーしない。
4. ユーザーの依存取得許可の範囲で、validation VMだけに
   `deb.debian.org:443`を一時許可。既存の他宛先許可はbuild中も遮断する。
   古い固定deny IDは使わず、現在の規則を検証し、自分が追加した規則だけを回収。
5. ビルド時間・出力を制限。新image ID、レシピdigest、package versionを保存。
   失敗/中断時は不明なビルドを再実行せず、状態確認して通信拒否と停止を優先。
6. 全面通信拒否を復旧し、全VM・管理サービス停止を確認。
7. 新imageをIDで固定し、非root/network-none/readonly-root境界、Python/Node、
   synthetic Git init/add/commit、既存回帰テストを別途確認してから使用する。

固定build driver `build_validation_git_image.py` と保守入口
`launch_machine_auth.py --build-validation-git-image` を実装した。
排他的な永続予約を作り、失敗した試行を自動再実行しない。
新規allowの所有権が不明な場合は他の規則を削除せず、全面denyを維持して
`inspection_required` を残す。Dockerの一覧取得・inspect失敗を不存在とみなさない。

純粋/mockテスト48件成功（専用WSL、0.046秒）。ビルド失敗時のdeny復帰順序、
復帰失敗でもVM停止を試みること、既存規則の不変性、固定2ファイルcontextを確認。
これらは実ビルド・Gitコミット成功の証拠ではない。

候補のcommit、bundle回収、ターン完了処理、10担当の継続運転は未完成であり、
このレシピだけで利用可能とは扱わない。

## 初回試行と原因特定

`/home/fleet/controller-validation/git-image-build-we0oqgmz/receipt.json`:
ビルド失敗（exit 1）。APT実行前の署名鍵パス確認で停止した。
通信拒否復旧、全11VM停止、管理サービス停止を確認。旧予約は保持。
固定ログ `/tmp/e-base-git-image-build-39ppmflc/build.log` を通信拒否下で読み取った。

`/home/fleet/controller-validation/git-capability-h3p1t49z/receipt.json`:
既存イメージの署名鍵実測は `/usr/share/keyrings/debian-archive-keyring.pgp`。
以前のレシピは `.gpg` を想定していた。取得元・suite・componentは想定通り。
署名チェックを無効化せず、固定鍵パスだけ実測値へ修正した。
48テスト再成功（0.045秒）。v2試行は初回の安全終了とレシピ変更を必須にし、
`git-image-build-v2.reservation` により同一試行の繰返しを拒否する。

## 修正後の実ビルド・動作確認

- ビルド証拠: `/home/fleet/controller-validation/git-image-build-edfcfgb7/receipt.json`
- 新image ID: `sha256:cee9fe9272c17a34c0b1620485843ff67431dcc18d2e0f7380581fe28f5aeaf4`
- イメージサイズ: 145705028 bytes。元imageは保持。
- Git: `1:2.47.3-0+deb13u1`（git/git-man）。Debian HTTPS取得・署名検証維持。
- 動作証拠: `/home/fleet/controller-validation/git-capability-5wpuf9t9/receipt.json`
- UID65532、資格情報なし、network-none、readonly-rootコンテナで通常の
  Git init/add/commit成功。固定一ファイル内容・tree・clean statusを確認。
- synthetic commit: `09c27b0c1ec504649c450a09da5a392ec68cdfa5`
- Python3.12.14、Node22.23.2。
- ビルド後の通信拒否復旧、確認コンテナ停止、全11VM停止を確認。

synthetic commitはプロジェクト候補commitやPRではない。本番image設定は未変更。

## 新イメージの境界・回帰確認

保守用固定入口 `--validate-newgit-stdlib` で、新imageと同じstdlib snapshotを照合。
既定imageとゲスト側の既存runnerファイルは変更しない。候補image指定と
本番turn/capture入力の併用は拒否する。

- dispatch: `/home/fleet/controller-validation/dispatch-7e3e23afef9f4a1d8edd71f7688c3704/dispatch.json`
- snapshot: `6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff`
- base: `616ad6b343a58651eba4310123ab267cd74fa2b7`、121files。
- 203 tests、7.872秒、OK、skipなし、Node22.23.2。
- image ID、manifest、base、container ID、materializationの結果を結合。
- `boundary.observations_verified=true`、コンテナ停止・VM停止・管理サービス停止。
- 管理コード47テスト成功（0.019秒）。初回は2テストファイル未配置でimport失敗、
  配置後の再試験がこの成功結果。初回失敗を成功とは扱わない。

保守用固定入口 `--validation-newgit-active` の能動的境界確認:

- 証拠: `/home/fleet/controller-validation/git-capability-2l5grfu0/receipt.json`
- guest証拠: `/tmp/validation-active-d33b435c90d346cbb3766a4a8e8f3481.json`
- 外側VMの非秘密canaryは非表示かつ試験後も不変。
- root書込み拒否（EROFS/30）、scratch書込み確認。
- 外部試験addressはENETUNREACH/101、loopback443はECONNREFUSED/111。
- cgroup: memory536870912、swap0、pids64、CPU100000/100000。
- detached childを含む観測プロセスはコンテナ停止後に消滅。
- 全11VM停止・管理サービス停止。

上記はこのimage/コンテナ条件の限定的な実測証拠であり、脆弱性が無いことや
完全隔離・10並列運用の証明ではない。`full_isolation_accepted=false` と
`validation_passed=false` を維持する。プロジェクトcandidate commit、bundle移送、
turn完了/fence解消、継続schedulerへの接続は別の未完了段階。
