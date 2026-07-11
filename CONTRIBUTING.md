# Contributing

このリポジトリは、架空のE進コンピュータを「触って遊べる」形に育てるための
実験場です。コンパイラ、エミュレーター、可視化、世界設定、サンプルプログラムの
どこからでも参加できます。

## 最初に動かす

```powershell
python -m unittest discover -s tests
python .\examples\cstyle_demo.py
python -m web_playground
```

`python` が PATH にない場合は、手元のPython実行ファイルを直接指定してください。

## 変更の目安

- 既存の `EPU` 命令セットと `timeline()` の構造を壊さない。
- E進らしい状態、温度、観測、量子化、正規化の見え方を大事にする。
- 新しい構文や命令を足す場合は、サンプルとテストを一緒に追加する。
- コンパイラ最適化は、速さだけでなく、熱、観測回数、劣化、レジスタ圧も評価する。

## コンテスト向けの貢献

歓迎する貢献例:

- C風コンパイラの最適化パス。
- より短いEPUアセンブリを生成する別コンパイラ。
- 熱や量子化をうまく避けるスケジューラー。
- Playgroundで見える新しい可視化。
- `examples/challenges/` に追加できる課題プログラム。

公式スイートの確認:

```powershell
python -m epu_cli challenge --json
```

GitHubでは、次のテンプレートを使えます。

- `Compiler challenge entry`: スコアや生成アセンブリを共有する。
- `Good first experiment`: 小さなサンプル、可視化、E-base実験を提案する。
- `Bug report`: 再現できる不具合を報告する。

最初の開催告知は [docs/challenge_kickoff.md](docs/challenge_kickoff.md) を土台にできます。
