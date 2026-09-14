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
[公開Playground](https://aaamirinu.github.io/e-base-computer/) をインストールなしの
「Try the Playground」として利用できます。
ただしGitHub Pages版はデモ用です。公式チャレンジ提出用JSONは、CLIまたはローカルの
`ebase-playground` Pythonサーバ版で取り直します。

## 見えるもの

- **Output**: `EOBS` / `EPRINT` による観測結果。
- **Assembly**: C風ソースから生成されたEPUアセンブリ。
- **Challenge Suite**: 公式部門または数値計算部門の問題別メトリクス。
- **Thermal & Precision Timeline**: 最大温度、安全分割数 `q_max`、選択tick。
- **Timeline Scrubber**: 任意tickへ移動し、その時点のレジスタとEフィールドを同期表示。
- **Operation Profile**: 命令種別ごとの実行回数。
- **E Digit Ladder**: Eレジスタの `e^k` 桁と連続digit。
- **E Field Map**: `EALLOC` で確保したE場、セル値、温度、分割数。
- **Events**: `NORMALIZED`, `QUANTIZED`, `DEGRADED`, `OBSERVATION_DIRTY` などのフラグ。

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

## チャレンジスイート

Playgroundの `Run Suite` は、選択したスイートを実行します。

```powershell
ebase challenge --json
ebase challenge --suite numerical --json
```

結果欄の `Copy JSON` で、IssueやDiscussionに貼る提出用JSONをコピーできます。
サーバAPIとしては、`/api/challenge`、`/api/challenge?suite=numerical`、
`/api/challenge?name=thermal-degrade` も使えます。名前指定と数値スイート指定は同時に使えません。

静的版では `/api/challenge` が存在しないため、`Run Suite` は `static fallback` の内蔵スイートを実行します。
静的ランタイムの命令ライフサイクル、量子化、`q_max`、分岐epsilon、採点式は
Python版と同じ定義を使い、公式5件すべてのscoreをsmoke testで照合します。
さらに `conformance/runtime-v1.json` をPython runtime、local server payload、
静的runtimeの両コピーへ通し、共通assemblyシナリオの出力・命令列・tick・flags・
partitionを完全一致、温度と実数値を記載許容誤差内で照合します。
ブラウザのC-likeコードもPython `CStyleCompiler` と同じassemblyへコンパイルされ、
同じ`runAsm`経路で実行されます。cross-runtime corpusではassembly、symbols、出力順、
命令列、scoreおよび主要診断を照合し、静的公式suiteの現在値`366.6`、数値suiteの
現在値`302.304481`はPython baselineと一致します。
静的`runAsm`は公開38命令を実装し、schema-v1 ASM corpusで離散状態・出力・制御フロー・
エラー名/code/messageをPython版と照合します。実数と熱・noise・healthのfloatは絶対許容誤差
`1e-9`、相対許容誤差0で比較します。詳細は `docs/static_asm_parity_v1.md` を参照してください。
ただし静的版はブラウザ内デモであり、独立した公式提出証拠にはなりません。
静的版では `Copy JSON` は無効になり、結果JSONにも
`demo_only=true` が入ります。提出前には必ず次のコマンドで公式結果を取り直します。

```powershell
ebase challenge --json
```
