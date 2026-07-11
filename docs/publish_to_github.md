# Publish to GitHub

初回公開時に行う作業を、上から順に進めるための手順です。実リポジトリURLが決まったら
`OWNER/REPO` を差し替えてください。

## 1. 最終確認

```powershell
python .\scripts\publication_audit.py --full
python .\scripts\release_smoke.py
```

Dockerもローカルで確認できる環境なら、Docker Desktopなどのdaemonを起動してから実行します。

```powershell
docker build -t e-base-computer .
docker run --rm -p 8765:8765 e-base-computer
```

確認する値:

- `publication_audit_ok`
- `release_smoke_ok`
- `ebase challenge --json` が `correct=true`
- `total_score=373.1`
- Playgroundの `/api/challenge` が `correct=true`

## 2. GitHubリポジトリを作成

推奨設定:

- Repository name: `e-base-computer`
- Visibility: Public（公開準備中はPrivateで進め、公開時に手動で切り替えてよい）
- Description: `An experimental E-base computer emulator, C-like compiler, playground, and compiler challenge kit.`
- Topics:
  - `emulator`
  - `compiler`
  - `virtual-machine`
  - `playground`
  - `education`
- License: repository内の `LICENSE` を使う。
- Issues: enabled
- Discussions: enabled
- Actions: enabled
- Pages: GitHub Actionsからdeploy
- Wiki: optional

## 3. URLを差し替える

実URLが決まったら、まずdry runで `project.urls` を確認します。

```powershell
python .\scripts\finalize_project_urls.py OWNER/REPO
```

問題なければ `pyproject.toml` に反映します。

```powershell
python .\scripts\finalize_project_urls.py OWNER/REPO --apply
```

custom domainやuser/org pagesを使う場合は、Playground URLを明示できます。

```powershell
python .\scripts\finalize_project_urls.py OWNER/REPO --playground-url https://play.example.test/ --apply
```

反映される内容:

```toml
[project.urls]
Homepage = "https://github.com/OWNER/REPO"
Repository = "https://github.com/OWNER/REPO"
Issues = "https://github.com/OWNER/REPO/issues"
Discussions = "https://github.com/OWNER/REPO/discussions"
Playground = "https://OWNER.github.io/REPO/"
```

必要に応じてREADMEやrelease notesにも実URLを追記します。
この手順書内の `OWNER/REPO` は公開作業用のプレースホルダとして残して構いません。

## 4. Push

通常はGit履歴からpushします。まずリポジトリとして認識されているか確認します。

```powershell
git rev-parse --show-toplevel
git status --short
```

`.git` が壊れている、OneDriveのreparse pointだけが残っている、または別PCへ渡して公開したい場合は、
先に公開用ソースzipを作れます。このzipは `.git`, `build/`, `dist/`, cache, `.ai/`, `.agents/` を除外し、
GitHubのWeb uploadや新しいclone先への展開に使えます。

```powershell
python .\scripts\make_release_bundle.py
```

出力例:

```text
created dist\e-base-computer-0.1.0-source.zip
files: 42
```

zipから公開する場合は、展開後のフォルダで次を実行します。

```powershell
git init
git add .
git commit -m "Initial public preview"
git branch -M main
git remote add origin https://github.com/OWNER/REPO.git
git push -u origin main
```

既存のGit履歴を使う場合は、`git init` 以降を状況に合わせて調整してください。

## 5. GitHub Actionsを確認

Actionsで次のjobが通ることを確認します。

- `unittest`
- `wheel-smoke`
- `docker-smoke`
- `release-smoke`
- `pages`
- `release` は `v*` tagまたは手動実行で配布物を作る。

`docker-smoke` はローカルDocker未起動環境では確認できないことがあるため、GitHub Actionsでの
結果を公開判断に使います。
`pages` は `web/playground/` を静的Playgroundとして公開します。公開URLで画面上のengine表示が
`static fallback` になり、サンプルの `Run` と `Run Official Suite` が動くことを確認してください。
Pages workflowはdeploy前に `node scripts/static_playground_smoke.cjs` も実行します。
Privateリポジトリでは `pages` job はスキップされます。Publicへ切り替えた後に、リポジトリ設定で
PagesのSourceをGitHub Actionsに設定すると、次の `main` push または手動実行でdeployできます。

## 6. 初回Releaseを作成

タグをpushすると、`.github/workflows/release.yml` が `scripts/release_smoke.py` を実行し、
sdist/wheelを作成してGitHub Releaseへ添付します。

```powershell
git tag v0.1.0
git push origin v0.1.0
```

Release案:

- Tag: `v0.1.0`
- Title: `E-base Computer v0.1.0 - Initial Public Preview`
- Body: [release_notes_v0_1.md](release_notes_v0_1.md) を貼る。

Release前に確認:

```powershell
python .\scripts\publication_audit.py --full
python .\scripts\release_smoke.py
```

## 7. DiscussionまたはIssueを作る

最初に置くとよい投稿:

- Compiler Challenge kickoff: [challenge_kickoff.md](challenge_kickoff.md)
- Challenge operations: [challenge_operations.md](challenge_operations.md)
- Good first experiment: `.github/ISSUE_TEMPLATE/good_first_experiment.md`
- Challenge entry template: `.github/ISSUE_TEMPLATE/compiler_challenge.md`

最初のGood first issue案:

- Add a sample that demonstrates `EREFRESH` and `REFRESH_DUE`.
- Add a Playground view for quantized state and partition.
- Try reducing `thermal-degrade` score without changing the official emulator.
- Add a compiler optimization that removes redundant `EMOV`.

## 8. 公開後の軽い運用

- Challenge投稿には `ebase challenge --json` の出力を添えてもらう。
- 主催者は提出JSONを保存し、`ebase leaderboard .\submissions\*.json --best-per-participant` で暫定ランキングを更新する。
- 公式baselineを変える場合は、`docs/compiler_challenge.md`, `CHANGELOG.md`,
  `docs/release_notes_v0_1.md`, `scripts/publication_audit.py` を同時に更新する。
- 命令セットを変える場合は、`src/epu_spec.py` と [epu_instruction_set.md](epu_instruction_set.md)
  を同時に更新する。
- Playground UIを変える場合は、`web/playground/` と `src/e_base_computer_web/playground/`
  を同期する。

## 9. Public Readiness Snapshot

現時点の公開準備で特に大事な証拠:

- READMEにPlaygroundスクリーンショットがある。
- `ebase-playground` でローカルWeb UIが起動する。
- GitHub Pages workflowで静的Playgroundを公開できる。
- `Run Official Suite` と `Copy JSON` でチャレンジ参加導線がある。
- `ebase leaderboard` で複数提出JSONを検証し、Markdownランキングを生成できる。
- `ebase spec --json` で命令仕様を読める。
- `python .\scripts\publication_audit.py --full` が通る。
- `python .\scripts\release_smoke.py` が通る。
