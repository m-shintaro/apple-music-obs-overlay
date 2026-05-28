<div align="center">

# OBS Apple Music Progress Bar

**Apple Music / now-playing メディアセッション** で再生中の曲を、ジャケット画像と
リアルタイムの再生バー付きで OBS に表示する、軽量で透過なオーバーレイです。

![Release](https://img.shields.io/github/v/release/m-shintaro/apple-music-obs-overlay)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![OBS](https://img.shields.io/badge/OBS-Browser%20Source-302E31)
![Dependencies](https://img.shields.io/badge/dependencies-optional%20Windows%20extra-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

[English](README.md) · **日本語**

<img src="docs/demo.png" alt="OBS Apple Music Progress Bar demo" width="100%">

</div>

---

> **Windows ユーザーの方へ:** Python は不要です。
> [**最新リリース**](https://github.com/m-shintaro/apple-music-obs-overlay/releases/latest)
> からポータブル ZIP をダウンロードし、実行ファイルをダブルクリックするだけで動きます。
> 詳しくは [Windows ポータブル ZIP](#windows-ポータブル-zippython-不要) を参照してください。

## 概要

小さな Python バックエンドが、有効なプロバイダーから現在のトラック情報（曲名・
アーティスト・アルバム・再生位置・総時間・ジャケット画像）を取得し、
`runtime/nowplaying.json` に書き出します。同梱の `overlay.html` がそのプラット
フォーム非依存のファイルを読み込み、OBS の **Browser Source** にそのまま追加できる
透過オーバーレイとして描画します。

macOS は標準コマンドの `osascript` と `sips` 経由で Music.app を使用します。
Windows はオプションの Python extra 経由で OS のメディアセッション API（SMTC）を使用します。

## Features

- macOS Music / Apple Music と Windows メディアセッションのリアルタイム表示
- OBS Browser Source 用の完全な透過オーバーレイ
- 経過時間と総時間を表示するリアルタイム再生バー
- Music.app または Windows SMTC からジャケット画像を取得し、失敗時は iTunes Search API で自動フォールバック
- 1080p / 4K 向けの表示倍率プリセットを内蔵
- 再生していなくてもレイアウトを確認できるデモモード

## Requirements

- Music.app / Apple Music を備えた macOS、または Apple Music for Windows を備えた Windows 10/11
- Python 3.9 以降 _(Windows ポータブル ZIP では不要)_
- OBS Studio

> macOS では追加の Python パッケージは不要です。Windows サポートには、`winsdk` を
> インストールするオプションの `windows` extra が必要です。

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

Python をインストールしたくない場合は、下の
[Windows ポータブル ZIP](#windows-ポータブル-zippython-不要) に進んでください。

それ以外の場合は、リポジトリのディレクトリで、オプションの Windows 依存を一度
インストールします。

```powershell
py -3 -m pip install ".[windows]"
```

その後、同じローカルサーバーを起動します。

```powershell
py -3 nowplaying.py
```

OBS の Browser Source URL は両プラットフォームで共通です。

```text
http://localhost:8765/overlay.html
```

### Windows ポータブル ZIP（Python 不要）

Windows では Python のインストールは不要です。最新リリースからポータブルビルドを
ダウンロードしてください。

1. [**Releases** ページ](https://github.com/m-shintaro/apple-music-obs-overlay/releases/latest) を開きます。
2. **Assets** から `OBSAppleMusicProgressBar-<version>-windows-<arch>.zip` をダウンロードします。
3. ZIP を任意の場所に展開し、`OBSAppleMusicProgressBar.exe` をダブルクリックします。

コンソールウィンドウに OBS の Browser Source URL が表示されます。

```text
http://localhost:8765/overlay.html
```

ポータブルビルドは、実行ファイルと同じ場所に `runtime/` フォルダを書き出します。

<details>
<summary>ポータブル ZIP を自分でビルドする</summary>

Windows 上でローカルにポータブル ZIP をビルドする場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

ZIP は `dist/OBSAppleMusicProgressBar-<version>-windows-<arch>.zip` に出力されます。

</details>

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

メディアプロバイダーに依存せずレイアウトだけ確認する場合:

```bash
python3 nowplaying.py --demo
```

`runtime/` に 1 回だけファイルを書き出して終了する場合:

```bash
python3 nowplaying.py --once
```

### コマンドラインオプション

| Option                 | Default     | Description                                         |
| ---------------------- | ----------- | --------------------------------------------------- |
| `--provider`           | `auto`      | プロバイダー: `auto` / `macos` / `windows` / `demo` |
| `--port`               | `8765`      | HTTP サーバーのポート                               |
| `--bind`               | `127.0.0.1` | HTTP サーバーの bind アドレス                       |
| `--interval`           | `0.25`      | プロバイダーの取得間隔（秒）                        |
| `--country`            | `JP`        | iTunes Search API の国コード                        |
| `--no-network-artwork` | off         | iTunes Search API によるジャケット取得を無効化      |
| `--demo`               | off         | `--provider demo` のエイリアス                      |
| `--once`               | off         | ファイルを 1 回だけ書き出して終了                   |
| `--diagnose-artwork`   | off         | プロバイダーのジャケット取得を診断                  |

## macOS Permissions

初回実行時に、Terminal または Python が Music.app を制御する許可を求められることがあります。

誤って許可しなかった場合は、**システム設定 → プライバシーとセキュリティ → オートメーション**
で Terminal / Python から Music を制御できるように設定してください。

## Artwork

ジャケット画像は次の順で解決されます。

1. **プロバイダーのジャケット** — macOS では Music.app から直接書き出し、Windows では
   SMTC のサムネイルデータを使用します。
2. **iTunes Search API フォールバック** — `artist + title` で検索します。プロバイダーの
   取得に失敗した場合のみ使用されます。

`runtime/nowplaying.json` には `artworkSource` と `artworkError` が含まれます。
`artworkSource: "music"` は macOS の直接取得に成功、`artworkSource: "smtc"` は
Windows の SMTC サムネイルデータを使用、`artworkSource: "itunes"` はフォールバックを
使用したことを意味します。

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
| `cover_windows.*`    | Windows SMTC サムネイルデータから取得した画像    |
| `cover_fallback.jpg` | iTunes Search API から取得したフォールバック画像 |

> `runtime/` 配下の生成物はすべて `.gitignore` で除外されます。

JSON スキーマは [`docs/nowplaying-json.md`](docs/nowplaying-json.md) に記載されています。

## Troubleshooting

<details>
<summary><strong>OBS に何も表示されない</strong></summary>

- Music.app が起動しているか確認してください。
- 再生が停止している間はオーバーレイは更新されません。
- Browser Source の URL が `http://localhost:8765/overlay.html` か確認してください。
- `python3 nowplaying.py --demo` でデモ表示が出るか確認してください。
- Windows では `py -3 -m pip install ".[windows]"` を実行済み（またはポータブル EXE を起動済み）で、Apple Music がメディアセッションを公開しているか確認してください。

</details>

<details>
<summary><strong>ジャケット画像が表示されない</strong></summary>

- `python3 nowplaying.py --diagnose-artwork` でプロバイダーのジャケット取得の診断結果を確認してください。
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

このツールは、macOS ではローカルの Music.app から、Windows ではシステムのメディア
セッション API から再生情報を取得し、ローカルの `runtime/` ディレクトリに保存します。

デフォルトでは、プロバイダーからのジャケット取得に失敗した場合のみ、曲名とアーティスト名を
iTunes Search API に送信してフォールバック画像を検索します。この動作を無効にするには
`--no-network-artwork` を指定してください。

## Contributing

Issue や Pull Request を歓迎します。バグ報告の際は、OS のバージョン、OBS のバージョン、
プロバイダー（`auto` / `macos` / `windows` / `demo`）、
`python3 nowplaying.py --diagnose-artwork` の出力を添えていただけると助かります。

## License

本プロジェクトは MIT License で公開されています。詳細は [LICENSE](LICENSE) を参照してください。

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
