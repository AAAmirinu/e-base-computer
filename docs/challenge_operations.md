# Challenge Operations

コンパイラチャレンジを運営するときの最小手順です。

## 1. 固定するもの

- 対象リリースまたはcommit。
- Pythonバージョン。
- `ebase challenge --json` の公式コマンド。
- 外部生成アセンブリを認める場合は `ebase challenge --assembly-dir .\generated-assembly --json`。
- 締切、1人あたりの提出数、最新提出/最高提出のどちらを採用するか。

## 2. 提出を集める

参加者には `Compiler challenge entry` Issue template を使ってもらいます。複数提出を許す場合も、
JSON内の `participant` は同じ名前にしてもらいます。貼られた `ebase challenge --json` のJSONを
`submissions/<participant>-<issue-or-date>.json` として保存します。
外部コンパイラ参加者には、`factorial.epu`, `e-ladder.epu`, `cold-memory.epu`,
`thermal-degrade.epu`, `branching.epu` を生成する手順もIssue本文に書いてもらいます。

## 3. 暫定ランキングを作る

```powershell
ebase leaderboard .\submissions\*.json
```

`ebase` 側で `*.json` を展開するため、PowerShellでも同じ書き方で使えます。
存在しないファイルや壊れたJSONは `valid=false` として表に残ります。
`valid=false` が1件でもある場合、コマンドは表を出したうえで終了コード `1` を返します。

1人複数提出のうち最高成績だけを採用する場合:

```powershell
ebase leaderboard .\submissions\*.json --best-per-participant
```

JSONで加工したい場合:

```powershell
ebase leaderboard .\submissions\*.json --json
```

`ebase` がPATHに入らない環境では、同じ操作を次で実行できます。

```powershell
python -m epu_cli leaderboard .\submissions\*.json --best-per-participant
```

`valid=false` の提出は、公式slugの不足、余分なslug、合計点の不一致、必須キー不足などを含みます。

## 4. 公式記録を確定する

leaderboard は提出JSONの一次検証とランキング表生成の道具です。最終順位は、主催者が同じcommitと
同じコマンドで再実行した結果を公式記録にしてください。

```powershell
ebase challenge --json
```

外部生成アセンブリを再採点する場合:

```powershell
ebase challenge --assembly-dir .\generated-assembly --json
```

`--assembly-dir` は存在する `<slug>.epu` だけを差し替え、存在しないslugは公式内蔵サンプルへfallbackします。
提出JSON内の `submission_source` は任意メタデータで、ランキング検証では必須ではありません。

採点式、期待出力、公式slugを変更した場合は、`docs/compiler_challenge.md`, `CHANGELOG.md`,
`docs/release_notes_v0_1.md`, `scripts/publication_audit.py`, `examples/challenges/baseline_submission.json`
を同時に更新します。
