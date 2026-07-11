# Compiler Challenge Kickoff Draft

GitHub Discussionsや最初のIssueに貼るための告知たたき台です。

## Title

E-base Compiler Challenge: 公式スイートをもっと短く、冷たく、読みやすくしよう

## Body

E進コンピュータは、連続値のE桁、熱、観測、量子化、劣化を持つ実験的な計算モデルです。
このチャレンジでは、同じプログラムをよりよいEPUアセンブリへ変換するコンパイラや
最適化アイデアを募集します。

まずはリポジトリを取得して、公式ベースラインを実行してください。

```powershell
python -m pip install -e .
ebase challenge --json
ebase-playground
```

Playgroundでは `Run Official Suite` を押すと同じ公式スイートを実行できます。
`Copy JSON` で結果を貼り付けられます。GitHub Pagesの静的版はデモ用なので、
公式提出にはCLIまたはPythonサーバ版PlaygroundのJSONを使ってください。

## Baseline

```text
correct=true
total_score=373.1
```

公式課題:

- `factorial`
- `e-ladder`
- `cold-memory`
- `thermal-degrade`
- `branching`

## Submit

公式提出は `Compiler challenge entry` Issue templateに投稿してください。Discussionには途中経過、
解説、別解、質問を自由に置けます。提出Issueには次を貼ってください。

- `ebase challenge --json` またはPlaygroundの `Copy JSON` の結果。
- 外部コンパイラで参加する場合は `ebase challenge --assembly-dir .\generated-assembly --json` の結果。
- 変更したコンパイラ/生成アセンブリ/最適化方針。
- 実行環境と対象コミット。
- どのE-baseらしさを狙ったか。

主催者側では提出JSONを保存し、次で暫定ランキングを作れます。

```powershell
ebase leaderboard .\submissions\*.json
```

詳しいルールは [compiler_challenge.md](compiler_challenge.md) を参照してください。
