# Web Playground

`ebase-playground` は、EPUエミュレーターとC風コンパイラをブラウザで触るための
ローカルWeb UIです。

前提: Python 3.11以上を用意し、GitHubからcloneしたcheckoutのルートで実行します。

```powershell
git clone https://github.com/AAAmirinu/e-base-computer.git
cd e-base-computer
python -m pip install -e .
ebase-playground
```

PATHに `ebase-playground` が入らない場合:

```powershell
python -m web_playground
```

起動後、`http://127.0.0.1:8765` を開きます。

GitHub Pagesなどの静的ホスティングでは、Pythonサーバなしで `web/playground/` をそのまま配信できます。
この場合、画面はブラウザ内蔵の `static fallback` ランタイムに切り替わります。サンプル実行、E桁の表示、
温度タイムライン、チャレンジ結果の雰囲気は試せますが、公式コンテストの順位判定はCLIまたは
`ebase-playground` のサーバ版で再確認してください。
公開後は `https://OWNER.github.io/REPO/` を「Try the Playground」リンクとして案内できます。
ただしGitHub Pages版はデモ用です。公式チャレンジ提出用JSONは、CLIまたはローカルの
`ebase-playground` Pythonサーバ版で取り直します。

## 見えるもの

- **Output**: `EOBS` / `EPRINT` による観測結果。
- **Assembly**: C風ソースから生成されたEPUアセンブリ。
- **Challenge Suite**: 公式部門または数値計算部門の問題別メトリクス。
- **Thermal & Precision Timeline**: 最大温度、安全分割数 `q_max`、選択tick。
- **Timeline Scrubber**: 任意tickへ移動し、その時点の状態を同期表示。
- **E Digit Ladder**: 選択tickにおけるEレジスタの `e^k` 桁と連続digit。
- **E Field Map**: 選択tickにおけるE場、セル値、温度、分割数。
- **Events**: 命令、フラグ、引数、対象、温度、分割状態。
- **Operation Profile**: 実行された命令種別ごとの回数。

## サンプル

Playgroundのサンプルは `src/epu_experiments.py` に集約されています。
同じサンプルをCLIからも使えます。

```powershell
ebase samples
ebase samples e-ladder --run
ebase samples thermal-degrade --run --json
```

これにより、Webで見た実験をCLIやコンテスト用のベースラインとして再現できます。

## 共有リンク

`Copy Program Link` は、現在のソース、言語、precisionをURL hashに入れたリンクをコピーします。
GitHub Pagesの静的Playgroundでも同じリンクを開けます。リンクを開くと editor が復元され、そのまま
`Run` できます。

長いプログラムではURLが長くなりすぎることがあります。その場合は短いサンプルや要点だけを共有し、
コンテスト提出には、CLIまたはローカルサーバ版 `Run Suite` の `Copy JSON` を使ってください。

## 公式チャレンジ

Playgroundの `Run Suite` は、選択したスイートを実行します。

```powershell
ebase challenge --json
ebase challenge --suite numerical --json
```

結果欄の `Copy JSON` で、IssueやDiscussionに貼る提出用JSONをコピーできます。
サーバAPIとしては、`/api/challenge`, `/api/challenge?suite=numerical`,
`/api/challenge?name=thermal-degrade` も使えます。

静的版では `/api/challenge` が存在しないため、`Run Suite` は `static fallback` の内蔵スイートを実行します。
これは公開ページで雰囲気を伝えるための軽量版です。静的版では `Copy JSON` は無効です。
提出前には必ず次のコマンドで公式結果を取り直します。

```powershell
ebase challenge --json
```
