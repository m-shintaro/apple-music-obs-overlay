# OBS Apple Music Progress Bar

macOS の Music.app / Apple Music から曲名、アーティスト、アルバム、再生位置、総時間、ジャケットを取得し、OBS Browser Source 用のオーバーレイとして表示します。

## 使い方

```bash
python3 nowplaying.py
```

OBS で **Browser Source** を追加し、URL にこれを指定します。

```text
http://localhost:8765/overlay.html
```

推奨サイズは `896 x 300` 以上です。OBS 側のソースをこれより広くしても、カード外は透過です。

このサイズは、カード本体 `720px` と浮き上がり用の余白を含みます。

## 4K 配信用

1080p 用のURLはそのまま残し、4K配信ではURLに `?profile=4k` を付けます。

```text
http://localhost:8765/overlay.html?profile=4k
```

4K用の推奨サイズは `1792 x 600` 以上です。見た目を微調整したい場合は `?scale=1.75` のように任意の倍率も指定できます。

## 初回の macOS 権限

初回実行時に、Terminal または Python が Music.app を制御する許可を求められることがあります。許可しなかった場合は、macOS の **System Settings → Privacy & Security → Automation** で Terminal / Python から Music を制御できるようにしてください。

## ジャケット取得

ジャケットは次の順に取得します。

1. Music.app の `current track` から JXA で `rawData` / `data` を直接書き出す
2. 取れない場合、`artist + title` で iTunes Search API を検索してフォールバック画像を保存する

通常起動では、直接取得に失敗した曲だけ iTunes Search API に曲名とアーティスト名を送ります。

ネットワーク経由のフォールバックを使いたくない場合:

```bash
python3 nowplaying.py --no-network-artwork
```

国コードを変える場合:

```bash
python3 nowplaying.py --country US
```

直接取得できない理由を確認する場合:

```bash
python3 nowplaying.py --diagnose-artwork
```

`runtime/nowplaying.json` にも `artworkSource` と `artworkError` が出ます。`artworkSource` が `music` なら Music.app から直接取得、`itunes` なら検索フォールバックです。

## プレビュー

Music.app がなくてもレイアウトだけ確認する場合:

```bash
python3 nowplaying.py --demo
```

## 生成ファイル

実行中は `runtime/` に以下のファイルが生成されます。

- `nowplaying.json`: Browser Source が読む曲情報
- `nowplaying.txt`: OBS Text Source でも使える簡易表示
- `cover_direct.jpg` / `cover_direct.png` / `cover_fallback.jpg`: ジャケット画像
