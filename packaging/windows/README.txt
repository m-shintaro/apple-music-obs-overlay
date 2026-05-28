OBS Apple Music Progress Bar

日本語
======

これは Apple Music の再生中トラックを、ジャケット画像と進行バー付きで OBS に表示するための Windows 用ポータブル版です。
Python のインストールは不要です。

使い方
------

1. ZIP を任意の場所に展開します。
2. Apple Music for Windows で曲を再生します。
3. `OBSAppleMusicProgressBar.exe` をダブルクリックして起動します。
4. OBS Studio を開き、ソースの `+` から `ブラウザ` を追加します。
5. ブラウザソースを次のように設定します。

URL: `http://localhost:8765/overlay.html`
幅: `560`
高さ: `140`

背景は透過です。配信中は `OBSAppleMusicProgressBar.exe` のウィンドウを閉じずに起動したままにしてください。

うまく表示されない場合
----------------------

- Apple Music で曲が再生中か確認してください。停止中は更新されません。
- OBS の URL が `http://localhost:8765/overlay.html` になっているか確認してください。
- 既に 8765 番ポートを使っている場合は、コマンドプロンプトで `OBSAppleMusicProgressBar.exe --port 8766` のように起動し、OBS 側の URL も `http://localhost:8766/overlay.html` に変更してください。
- `runtime` フォルダは実行時に使われる作業フォルダです。配信中は削除しないでください。


English
=======

This is the Windows portable build for showing the current Apple Music track in OBS with album artwork and a live progress bar.
Python is not required.

How to use
----------

1. Extract the ZIP anywhere.
2. Play a track in Apple Music for Windows.
3. Double-click `OBSAppleMusicProgressBar.exe`.
4. In OBS Studio, add a `Browser` source from the source `+` menu.
5. Configure the Browser source like this:

URL: `http://localhost:8765/overlay.html`
Width: `560`
Height: `140`

The overlay background is transparent. Keep the `OBSAppleMusicProgressBar.exe` window running while you stream or record.

Troubleshooting
---------------

- Make sure a track is playing in Apple Music. The overlay does not update while playback is stopped.
- Confirm the OBS URL is `http://localhost:8765/overlay.html`.
- If port 8765 is already in use, start from Command Prompt with `OBSAppleMusicProgressBar.exe --port 8766`, then change the OBS URL to `http://localhost:8766/overlay.html`.
- The `runtime` folder is used while the app is running. Do not delete it during streaming.
