# stdlib earray命令数の修正・隔離検証（2026-09-19）

9担当の本人認証待ちとは独立して、過去の実ソース検証で失敗した
`test_guest_app_example`（期待51、実測52）を修正した。

## 原因と変更

EDOT3は6 ELOAD + 3 EMUL + 2 EADD = 11命令。
マクロ本体とエミュレータのカウントは正しく、テスト・仕様が10と誤記していた。
stdlib laneの次の3ファイルだけを変更した。

- `guest/stdlib/earray.epu`: コスト説明を11へ修正。実命令は変更なし。
- `docs/fleet/stdlib/earray_v0.md`: 表と末尾の5/11/9、アプリ総数52を修正。
- `tests/test_stdlib_earray.py`: アプリ期待52、EDOT3実行テスト31、展開の内訳6/3/2を検査。

## 命令数修正版の実証

旧snapshot `2c4008d2837858e8e733eb943335a564da65c8a4723becc3456cd84b438c73eb`
から3ファイルだけを置換した派生snapshot：
`7a121d110b173d1a7a44d56a1ec88000bd20c8a6f3ab5a4df581893a8bb866ab`。
基点の各旧ファイルhashを一致確認し、その他149ファイルはそのまま。

専用WSLの証拠：
- `/home/fleet/controller-validation/earray-repair-cbi86f9i/derivation.json`
- `/home/fleet/controller-validation/dispatch-17a715f0820a43fa923d1871833372a3/dispatch.json`

既存のdigest固定Python/Nodeイメージ、通信拒否、非root、認証情報なしの内側
検証コンテナで実行した。261テスト、260成功、既知の期待失敗1、skipなし、終了0。
コンテナ・検証VM・全11VM・管理サービスの停止を確認した。
Windowsホストや認証済みrole VMでは候補ソースを実行していない。

## 限界と残作業

本番隔離全体の合格ではなく、receiptの `validation_passed=false` と
`full_isolation_accepted=false` は維持した。テストコマンド成功だけを確認した。
元の失敗snapshot/receiptは書き換えていない。修正はWindows側stdlib laneと
派生snapshotにあり、stdlib VMの作業ツリーにはまだ反映していない。
候補コミット・PR作成・マージも未実行。自動継続運用の認証・admission・復旧ゲートは残る。

## 契約説明レビュー後の再検証

格納条件を「全ての正規化済み桁の指数が範囲内」に修正し、ゼロの扱いを明記。
exact / 固定相対誤差の保証を撤回し、EPSILON cleanup・異符号加算時のfloat変換を説明。
EVSCALE3は逐次更新で、別名参照では繰り返し更新され得ることとrollbackなしを明記した。
実命令とテストは命令数修正版から変更していない。

最新snapshot: `efeea379f3aa1531c404f2f78103b0c741cde6469aead6386d9dbe91b1ac20fe`

- `/home/fleet/controller-validation/earray-repair-9kzr3pex/derivation.json`
- `/home/fleet/controller-validation/dispatch-4f1521fcbb114f528f38f73b917ef548/dispatch.json`

261テスト、期待失敗1、skipなし、終了0（10.445秒）。検証コンテナ・全11VM・
管理サービスの停止を固定ランチャーで確認した。全体隔離の非承認フラグは維持。

## PR依存関係の注意

公開先はREADME・pyproject・GitHub APIから `AAAmirinu/e-base-computer` と確認。
確認時mainは `616ad6b343a58651eba4310123ab267cd74fa2b7` で、
`src/guest_stdlib.py` は存在しない。laneのoriginはローカル統合repoであり、
テスト基点 `c25b2d33ef3823fd78a0117f20f6bd1d50e86260` はmainではない。
上記261テストの結果をmain+earrayだけの検証結果として扱ってはならない。
マクロ展開器の前提変更（5b789d7、44d0397）を含む最小PR範囲の確認が必要。
未レビューの統合履歴全体をpushする操作は行っていない。
