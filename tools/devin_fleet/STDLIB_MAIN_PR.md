# 公開main基準のstdlib候補（2026-09-19）

候補worktree: `.ai/devin-fleet-run/pr-stdlib-main`
base: `616ad6b343a58651eba4310123ab267cd74fa2b7`
branch: `improve/guest-stdlib-earray`
local commit: `7d0e065`（通常のGit設定でコミット、フック・署名設定の変更なし）

追加は以下の6ファイルのみ。他laneの未公開core変更や運用・認証設定は含まない。

- `src/guest_stdlib.py`
- `guest/stdlib/earray.epu`
- `examples/stdlib/vector_dot.epu`
- `docs/fleet/stdlib/earray_v0.md`
- `tests/test_guest_stdlib.py`
- `tests/test_stdlib_earray.py`

マクロ展開器の空引数拒否と22件の直接テストを追加。格納指数範囲、数値誤差、
別名参照、逐次更新、命令数の契約を修正。ソースチェックアウト向けであり、
pip配布時のguest asset探索対応は含まない。

## 最終検証

snapshot `6039785fee9ba2a0425c41b6999e0fa082abe49310f47e0124ab9d204ad070ff`
は公開mainのGit blobと上記6追加ファイル（全121ファイル）。他のlane履歴は含まない。

専用WSL内の固定receipt:
`/home/fleet/controller-validation/dispatch-d3333d1e806c4d49928337f16398c722/dispatch.json`

通信拒否・認証情報なしの検証コンテナで203テスト全成功、skipなし、
期待失敗なし、9.516秒。Node v22.23.2。コンテナ、全11VM、管理サービス停止確認済み。
ステージ済み6ファイルのSHA256とGit blobをsnapshotと一致確認してからコミットした。
Windowsホスト・認証済みrole VMで候補コードは実行していない。
`validation_passed=false` / `full_isolation_accepted=false` は運用全体の未承認を示し維持。
Fableの最新reportは別案件のnot_runで、本件の外部監査合格ではない。

## 公開承認ゲート

確認済み公開先: https://github.com/AAAmirinu/e-base-computer

PR本文案: `.ai/stdlib-main-pr-body.md`

新規branchへのpushは自動承認チェックで拒否された。理由は未公開6ファイルを
公開repoへ送る正確なpayload/destinationの明示承認が必要というもの。
迂回送信は行っていない。PRは未作成。ユーザーに公開先と6ファイルの承認を求める。
マージは依然ユーザーによる手動承認のみ。10セッション運用の残ゲートも未解消。
