# Playground Visual QA

Playgroundの視覚確認では、単にHTTP 200を見るだけでなく、E進らしい状態が
画面上で読めることを確認します。

## 起動

```powershell
ebase-playground --port 8765
```

ブラウザで `http://127.0.0.1:8765` を開きます。

## チェック項目

- サンプル選択に `factorial`, `e-ladder`, `cold-memory`, `thermal-degrade`, `branching` がある。
- `factorial` は `OUT0: 120` 相当の出力、生成アセンブリ、58前後のイベントを表示する。
- `Thermal Timeline` に赤い温度線が表示される。
- `E Digit Ladder` に活動中のEレジスタと `e^k` digit bar が表示される。
- `cold-memory` を選んで `Run` すると、`E Field Map` に `F0 @ COLD` とセル値が表示される。
- `thermal-degrade` は `DEGRADED` を含むイベントを作り、温度と分割数低下が見える。

## 直近の確認メモ

2026-07-03時点で、in-app browserにより次を確認しました。

- `factorial`: sample count 5、`OUT0` 120、`EPRINT` あり、register rows 4、events 58。
- `cold-memory`: `EALLOC` あり、field rows 1、`F0 @ COLD`、`OUT0` 7.5、traceあり。

スクリーンショット上でも、メトリクス、Output、Assembly、Thermal Timelineが
重なりなく表示されていました。
