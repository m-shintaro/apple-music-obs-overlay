<div align="center">

# OBS Apple Music Progress Bar

**Apple Music / OS の再生中メディアセッション** の曲を、ジャケット画像とリアルタイムの
再生バー付きで OBS に表示する、軽量で透過なオーバーレイです。

![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![OBS](https://img.shields.io/badge/OBS-Browser%20Source-302E31)
![Dependencies](https://img.shields.io/badge/dependencies-optional%20Windows%20extra-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

[English](README.md) · **日本語**

<img src="docs/demo.png" alt="OBS Apple Music Progress Bar demo" width="100%">

</div>

---

## 概要

小さな Python バックエンドが現在の provider から再生情報（曲名・アーティスト・アルバム・
再生位置・総時間・ジャケット画像）を取得し、`runtime/nowplaying.json` に書き出します。
同梱の `overlay.html` がそのプラットフォーム共通のファイルを読み込み、OBS の **Browser Source** に
そのまま追加できる透過オーバーレイとして描画します。

macOS では標準の `osascript` と `sips` を使います。Windows では OS のメディアセッション
API（SMTC）を使うため、任意の Python extra をインストールします。

## Features

- macOS Music / Apple Music と Windows のメディアセッションをリアルタイム表示
- OBS Browser Source 用の完全な透過オーバーレイ
- 経過時間と総時間を表示するリアルタイム再生バー
- ジャケット画像を Music.app または Windows SMTC から取得し、失敗時は iTunes Search API で自動フォールバック
- 1080p / 4K 向けの表示倍率プリセットを内蔵
- 再生していなくてもレイアウトを確認できるデモモード

## Requirements

- Music.app / Apple Music が使える macOS、または Apple Music for Windows が使える Windows 10/11
- Python 3.9 以降
- OBS Studio

> macOS では追加の Python パッケージは不要です。Windows 対応には `winsdk` を含む
> 任意の `windows` extra が必要です。

## Quick Start

リポジトリをクローンし、ローカルサーバーを起動します。

```bash
git clone https://github.com/m-shintaro/apple-music-obs-overlay.git
cd apple-music-obs-overlay
python3 nowplaying.py
```

次に OBS で **Browser Source** を追加し、URL に以下を指定します。

```text
http://localhost:8765/overlay.html
```

推奨ソースサイズ:

| 解像度 | 最小サイズ   |
| ------ | ------------ |
| 1080p  | `896 × 300`  |
| 4K     | `1792 × 600` |

カードの周囲は透過です。OBS 側のソースサイズは推奨より大きくしても問題ありません。

### Windows セットアップ

リポジトリのディレクトリで、Windows 用の依存関係を 1 回だけインストールします。

```powershell
py -3 -m pip install ".[windows]"
```

その後、同じローカルサーバーを起動します。

```powershell
py -3 nowplaying.py
```

OBS Browser Source の URL は macOS / Windows 共通です。

```text
http://localhost:8765/overlay.html
```

## Usage

### 4K と倍率の調整

4K 配信では URL に `?profile=4k` を付けます。

```text
http://localhost:8765/overlay.html?profile=4k
```

任意の倍率を指定したい場合は `scale` を使います。

```text
http://localhost:8765/overlay.html?scale=1.75
```

### 再生なしでのプレビュー

実際の再生 provider に関係なくレイアウトだけ確認する場合:

```bash
python3 nowplaying.py --demo
```

`runtime/` に 1 回だけファイルを書き出して終了する場合:

```bash
python3 nowplaying.py --once
```

### コマンドラインオプション

| Option                 | Default     | Description                                    |
| ---------------------- | ----------- | ---------------------------------------------- |
| `--provider`           | `auto`      | `auto`、`macos`、`windows`、`demo` から選択    |
| `--port`               | `8765`      | HTTP サーバーのポート                          |
| `--bind`               | `127.0.0.1` | HTTP サーバーの bind アドレス                  |
| `--interval`           | `0.25`      | provider から再生情報を取得する間隔（秒）      |
| `--country`            | `JP`        | iTunes Search API の国コード                   |
| `--no-network-artwork` | off         | iTunes Search API によるジャケット取得を無効化 |
| `--demo`               | off         | `--provider demo` の互換エイリアス             |
| `--once`               | off         | ファイルを 1 回だけ書き出して終了              |
| `--diagnose-artwork`   | off         | provider のジャケット取得を診断                |

## macOS Permissions

初回実行時に、Terminal または Python が Music.app を制御する許可を求められることがあります。

誤って許可しなかった場合は、**システム設定 → プライバシーとセキュリティ → オートメーション**
で Terminal / Python から Music を制御できるように設定してください。

## Artwork

ジャケット画像は次の順で解決されます。

1. **Provider から取得** — macOS では Music.app から直接書き出し、Windows では SMTC の thumbnail を使います。
2. **iTunes Search API フォールバック** — `artist + title` で検索します。provider からの取得に
   失敗した場合のみ使用されます。

`runtime/nowplaying.json` には `artworkSource` と `artworkError` が含まれます。
`artworkSource` が `music` なら macOS の直接取得、`smtc` なら Windows SMTC の thumbnail、
`itunes` ならフォールバックが使われたことを意味します。

ジャケット取得の診断:

```bash
python3 nowplaying.py --diagnose-artwork
```

ネットワークフォールバックを完全に無効化:

```bash
python3 nowplaying.py --no-network-artwork
```

## Generated Files

実行中、以下のファイルが `runtime/` に生成されます。

| File                 | Description                                      |
| -------------------- | ------------------------------------------------ |
| `nowplaying.json`    | Browser Source が読み込む曲情報                  |
| `nowplaying.txt`     | OBS Text Source でも使える簡易テキスト出力       |
| `cover_direct.*`     | Music.app から直接取得したジャケット画像         |
| `cover_windows.*`    | Windows SMTC の thumbnail から取得した画像       |
| `cover_fallback.jpg` | iTunes Search API から取得したフォールバック画像 |

> `runtime/` 配下の生成物はすべて `.gitignore` で除外されます。

JSON の形式は [`docs/nowplaying-json.md`](docs/nowplaying-json.md) にまとめています。

## Troubleshooting

<details>
<summary><strong>OBS に何も表示されない</strong></summary>

- Music.app が起動しているか確認してください。
- 曲が停止状態の場合、オーバーレイは更新されません。
- Browser Source の URL が `http://localhost:8765/overlay.html` になっているか確認してください。
- `python3 nowplaying.py --demo` でデモ表示が出るか確認してください。
- Windows では `py -3 -m pip install ".[windows]"` を実行済みか、Apple Music がメディアセッションを公開しているか確認してください。

</details>

<details>
<summary><strong>ジャケット画像が表示されない</strong></summary>

- `python3 nowplaying.py --diagnose-artwork` で provider のジャケット取得診断結果を確認してください。
- iTunes Search API のフォールバックにはネットワーク接続が必要です。
- ネットワーク送信を避けたい場合は `--no-network-artwork` を使ってください。

</details>

<details>
<summary><strong>ポートが使用中</strong></summary>

別のポートで起動してください。

```bash
python3 nowplaying.py --port 8766
```

OBS 側の URL も同じポートに変更します。

```text
http://localhost:8766/overlay.html
```

</details>

## Privacy

このツールは macOS ではローカルの Music.app、Windows では OS のメディアセッション API から
再生情報を取得し、ローカルの `runtime/` ディレクトリに保存します。

デフォルトでは、provider からのジャケット取得に失敗した場合のみ、曲名とアーティスト名を
iTunes Search API に送信してフォールバック画像を検索します。この動作を無効にするには
`--no-network-artwork` を指定してください。

## Contributing

Issue や Pull Request を歓迎します。バグ報告の際は、OS のバージョン、OBS の
バージョン、provider（`auto` / `macos` / `windows` / `demo`）、`python3 nowplaying.py --diagnose-artwork` の出力を添えていただけると
助かります。

## License

このプロジェクトは MIT License で公開されています。詳細は [LICENSE](LICENSE) を参照してください。

## Credits

- **Creator** — shin ([GitHub: @m-shintaro](https://github.com/m-shintaro), [X: @xyzmiku](https://x.com/xyzmiku))
- [OBS Studio](https://obsproject.com/) — 配信ソフトウェアと Browser Source の実行環境
- Apple Music / Music.app — macOS 上の再生情報の取得元
- Windows Media Control / SMTC — Windows 上の再生情報の取得元
- [iTunes Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/) — ジャケット画像のフォールバック検索

---

> **Disclaimer** — このプロジェクトは Apple Inc. または OBS Project による公式
> プロジェクトではありません。Apple、Apple Music、iTunes、macOS は Apple Inc. の
> 商標です。OBS および OBS Studio は OBS Project の名称です。楽曲情報やジャケット
> 画像の権利は各権利者に帰属します。
