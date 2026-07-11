# Release Checklist

GitHubで公開する前に確認する項目です。

## 必須

- `LICENSE` がある。
- `README.md` に実行方法、デモ、テスト、Playgroundの起動方法がある。
- `pyproject.toml` で editable install とCLIが動く。
- wheelに `e_base_computer_web/playground/*.html|css|js` が含まれる。
- `python -m unittest discover -s tests` が通る。
- `python examples/demo.py`、`python examples/epu_demo.py`、`python examples/cstyle_demo.py` が動く。
- `python -m web_playground` でローカルPlaygroundが起動する。
- `docker build -t e-base-computer .` でPlaygroundコンテナを作れる。
- `ebase` が PATH にない環境でも `python -m epu_cli` で同じ操作ができる。
- `python -m epu_cli challenge --json` が公式チャレンジを全件正解で実行できる。
- `python .\examples\compiler_starter\emit_baseline_assembly.py --output <dir>` で外部コンパイラ用のbaseline `.epu` 一式を作れる。
- `python -m epu_cli challenge --assembly-dir <dir> --json` で外部生成アセンブリを採点できる。
- `python .\scripts\make_release_bundle.py --dry-run` で公開用ソースzipの生成対象を確認できる。
- GitHub Actionsがテストとデモを実行する。
- GitHub Actionsが `scripts/release_smoke.py` を実行し、wheel install、CLI、Playground HTTPまで確認する。
- `v*` tag用のrelease workflowがsdist/wheelを作り、GitHub Releaseへ添付する。

## 推奨

- 初心者向けIssueを作る。
- `.github/ISSUE_TEMPLATE/good_first_experiment.md` から初心者向けIssueを作る。
- [challenge_kickoff.md](challenge_kickoff.md) をもとにコンパイラ最適化チャレンジのルールをIssue templateとDiscussionに置く。
- `ebase leaderboard .\examples\challenges\baseline_submission.json` でランキング表を生成できる。
- `ebase leaderboard .\examples\challenges\*.json --best-per-participant` がPowerShellでも動く。
- Playgroundのスクリーンショット `docs/assets/playground-challenge.png` をREADMEに貼る。
- GitHub Pages workflowで `web/playground/` の静的Playgroundを公開できる。
- 静的Playgroundでは `static fallback` 表示でサンプルの `Run` と `Run Official Suite` が動く。
- `node scripts/static_playground_smoke.cjs` で静的Playground runtimeが動く。
- [release_notes_v0_1.md](release_notes_v0_1.md) をGitHub Release本文の土台にする。
- `CHANGELOG.md` に初回公開内容をまとめる。
- [publish_to_github.md](publish_to_github.md) に沿って初回公開する。
- `python .\scripts\finalize_project_urls.py OWNER/REPO --apply` で `project.urls` を実際のリポジトリに合わせる。
- `.git` が壊れている環境やWeb uploadで公開する場合は `python .\scripts\make_release_bundle.py` で
  `dist/e-base-computer-0.1.0-source.zip` を作る。
- custom domainやuser/org pagesを使う場合は `--playground-url` で実Pages URLを指定する。

## 配布検証コマンド

```powershell
python -m pip install -e .
python .\scripts\publication_audit.py
node .\scripts\static_playground_smoke.cjs
python .\scripts\make_release_bundle.py --dry-run
python .\examples\compiler_starter\emit_baseline_assembly.py --output .\generated-assembly
python -m unittest discover -s tests
python -m pip wheel . --no-deps -w dist
python -m epu_cli challenge --json
python -m epu_cli challenge thermal-degrade --json
python -m epu_cli challenge e-ladder --assembly-dir .\generated-assembly --json
python -m epu_cli leaderboard .\examples\challenges\baseline_submission.json
python -m epu_cli leaderboard .\examples\challenges\*.json --best-per-participant
python -m epu_cli spec --json
python -m epu_cli run .\examples\challenges\factorial.cbase --json
python -m epu_cli samples thermal-degrade --run --json
python -m web_playground
docker build -t e-base-computer .
docker run --rm -p 8765:8765 e-base-computer
```

より実リリースに近い一括検証:

```powershell
python .\scripts\publication_audit.py --full
python .\scripts\release_smoke.py
```

`publication_audit.py` は公開向けファイル、README画像、GitHubテンプレート、
公式チャレンジ、Playground assetsの同期を確認します。`release_smoke.py` は、
テスト、wheel build、fresh venv install、CLI、Playground HTTPをまとめて確認します。
GitHub Actionsの `release-smoke` job でも同じ総合スモークを実行します。
`static_playground_smoke.cjs` はGitHub Pagesで配る静的runtimeのサンプル実行と
デモ用チャレンジsuiteを確認します。
`release.yml` はタグ付き公開時に `release_smoke.py`、`python -m build`、`twine check` を通してから
配布物をRelease assetとしてアップロードします。
