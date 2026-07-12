# E-base Compiler Challenge

E進コンピュータ向けコンパイラの遊び方、公式採点、提出ルールです。

## 目的

同じC風プログラムやEPUアセンブリ課題を、よりよいEPUアセンブリへ変換します。
普通のコンパイラ最適化と違い、速さだけではなく、Eセルの熱、観測回数、
量子化の劣化、メモリ使用も評価します。

## 公式コマンド

提出前には必ず公式スイートを実行してください。

```powershell
python -m epu_cli challenge --json
```

外部コンパイラや別言語のコンパイラが生成したEPUアセンブリを採点する場合は、
公式slugと同名の `.epu` ファイルをディレクトリに置き、`--assembly-dir` を指定します。

```powershell
python -m epu_cli challenge --assembly-dir .\generated-assembly --json
```

まず動く外部コンパイラ枠を作りたい場合は、公式baselineアセンブリをスターターとして出力できます。

```powershell
python .\examples\compiler_starter\emit_baseline_assembly.py --output .\generated-assembly
python -m epu_cli challenge --assembly-dir .\generated-assembly --json
```

例えば `generated-assembly\factorial.epu` があれば `factorial` はそのアセンブリで採点され、
存在しないslugは内蔵baselineで採点されます。全課題を提出する場合は、次の5ファイルを置きます。

```text
factorial.epu
e-ladder.epu
cold-memory.epu
thermal-degrade.epu
branching.epu
```

単体課題だけ確認する場合:

```powershell
python -m epu_cli challenge thermal-degrade --json
```

`ebase` がPATHに入っている環境では、同じ操作を次のようにも実行できます。

```powershell
ebase challenge --json
ebase challenge thermal-degrade --json
```

命令セットの機械可読リファレンス:

```powershell
ebase spec --json
```

## 参加者ワークフロー

最初のコンテストでは、参加者はリポジトリをforkし、自分の作業ブランチで
`src/cstyle_compiler.py` や周辺のコンパイラ実装を改造するか、外部コンパイラから
公式slugごとの `.epu` を生成する想定です。そのcheckoutから公式スイートを実行し、
同じ環境で出たJSONを提出します。

```powershell
python -m pip install -e .
python .\examples\compiler_starter\emit_baseline_assembly.py --output .\generated-assembly
python -m epu_cli challenge --json
python -m epu_cli challenge --assembly-dir .\generated-assembly --json
```

提出時には、結果JSONに加えて branch、commit、主なdiff、生成アセンブリの例を添えてください。
外部コンパイラや別言語実装を使う場合も、公式エミュレーターと公式採点式は変更せず、
再現方法と `--assembly-dir` に渡した生成物の作り方をIssue本文に書きます。将来版では、
外部コンパイラを直接呼ぶ `--compiler-command` 形式の公式フックも検討します。

## 公式課題

現在の公式スイートは、`src/epu_experiments.py` に定義された5件です。

| slug | expected output | language | baseline score | baseline steps | baseline assembly lines |
| --- | --- | --- | ---: | ---: | ---: |
| `factorial` | `OUT0 = 120.0` | C-like | 73.3 | 58 | 21 |
| `e-ladder` | `OUT0 = 144.40872214` | EPU asm | 20.7 | 6 | 6 |
| `cold-memory` | `OUT0 = 7.5` | EPU asm | 20.2 | 6 | 6 |
| `thermal-degrade` | `OUT0 = 1.62761319` | EPU asm | 233.5 | 98 | 12 |
| `branching` | `OUT0 = 0.0` | C-like | 25.4 | 12 | 18 |

Baseline total:

```text
correct=true
total_score=373.1
```

`examples/challenges/` のファイルは、単体実行や説明用の素材です。公式順位は
`ebase challenge --json` の出力を基準にします。

## 公式スコア

`epu_scoring.score_timeline()` は次を集計します。

- `steps`: 実行命令数。
- `observations`: `EOBS` / `EPRINT` / 観測フラグの回数。
- `max_temperature`: 実行中の最大温度。
- `degraded_events`: `DEGRADED` が立った回数。
- `refresh_events`: `EREFRESH` / `ESCRUB` の回数。
- `memory_cells`: 確保されたEセル数。
- `score`: 低いほどよい総合点。

正解判定は、各課題の期待出力に対して `1e-8` の相対/絶対許容差で比較します。
既定の実行上限は `max_steps=10000` です。

## 変更してよいもの

- 自分のコンパイラ実装。
- コンパイラが生成するEPUアセンブリ。
- 最適化のための解析、変換、ラベル付け、命令選択。

## 変更してはいけないもの

- 公式命令セットやエミュレーターの挙動。
- `epu_scoring.py` の採点式。
- `epu_challenge.py` の期待出力や正解判定。
- 課題を特別扱いして、出力だけを直接返すハードコード。

## タイブレーク

1. `correct=true` の提出を優先します。
2. `total_score` が低い提出を上位にします。
3. 同点なら `steps` 合計が低い提出を上位にします。
4. さらに同点なら `assembly_lines` 合計が低い提出を上位にします。
5. まだ同点なら、読みやすさや説明の面白さを見ます。

## 提出形式

公式提出はGitHubの `Issues` -> `New issue` -> `Compiler challenge entry` から作ります。
テンプレート本文は [../.github/ISSUE_TEMPLATE/compiler_challenge.md](../.github/ISSUE_TEMPLATE/compiler_challenge.md) です。
Discussionは設計メモ、解説、途中経過、別解の相談に使ってください。提出Issueには次を含めます。

- `ebase challenge --json` の出力。
- 外部生成アセンブリで参加する場合は `ebase challenge --assembly-dir ... --json` の出力。
- 実行環境、Pythonバージョン、対象コミットまたはリリース。
- どの最適化をしたかの説明。
- 代表的な生成アセンブリ。
- 既存命令や採点式を変更していないこと。

提出JSONは次の形を満たす必要があります。

- トップレベルに `correct`, `total_score`, `results` がある。
- 任意でトップレベルに `participant` を入れられる。複数提出する場合は同じ `participant` を使う。
- `results` には公式slug `factorial`, `e-ladder`, `cold-memory`, `thermal-degrade`, `branching` が1件ずつある。
- 各resultに `slug`, `correct`, `steps`, `assembly_lines`, `score.score`, `score.degraded_events` がある。
- `submission_source` は任意メタデータです。`assembly-dir` の結果か公式内蔵サンプルかを示します。
- `total_score` は `results[].score.score` の合計と一致する。

`examples/challenges/baseline_submission.json` は、公式baselineの最小提出JSON例です。

## 部門案

- **Lowest score**: 公式総合点を下げる。
- **Shortest assembly**: 生成アセンブリ行数を少なくする。
- **Coolest run**: `max_temperature` を下げる。
- **Low observation**: 観測回数を必要最小限にする。
- **No degrade**: 高温サンプルでも `DEGRADED` を避ける。
- **Readable compiler**: Playgroundで追いやすいラベルとトレースを残す。

勝敗だけではなく、生成アセンブリを読んで「その手があったか」と楽しめることを
重視します。

## 数値計算部門

別部門として、binary64範囲での精度と実行stepsを比較する数値計算スイートがあります。

```powershell
ebase challenge --suite numerical --json
ebase challenge --suite numerical --assembly-dir .\generated-assembly --json
```

数値部門は最大相対誤差、accuracy digits、steps、温度を別々に記録します。課題、許容誤差、
順位規則は [Numerical Compiler Challenge](numerical_challenge.md) を参照してください。
