# 固定版と最新版の試用環境

公式の [Installation](https://github.com/Aratako/Irodori-TTS#installation) とローカルチェックポイント対応を基に構成する。確認日: 2026-09-14。

このPCの作成時点: 固定版TTSは `8224daf`（独自変更あり）、固定モデルsnapshotは `2b28324dc263ed5e6638b3cf3dd94c82ead07b4b`。試用版TTSは `89f9d8f`。両環境で画面・状態APIの応答と試用版のランタイムimportを確認。GPU音声生成・聴感比較は未検証。試用版モデルは初回生成時に取得する。

## 起動

- `start-stable.bat`: 現在のTTSとPythonを維持し、保存したモデルをオフラインで使用。http://127.0.0.1:8765
- `start-latest.bat`: 別clone・別Python・別モデルキャッシュ・別エディターコピー・別データ。http://127.0.0.1:8766
- 元の `Irodori-TTS-Editor-start.bat` / `start.ps1` は従来動作。固定運用には `start-stable.bat` を使う。

起動時にgit pullやuv syncは実行しない。既存サーバーが8765を使用している場合は、作業を保存してそのサーバーを終了してから固定版を起動する。GPU生成は片方ずつ行う。

## 初回作成

作業フォルダで実行:

```powershell
& E:\Irodori-TTS\.venv\Scripts\python.exe -B -X utf8 setup-environments.py stable
& E:\Irodori-TTS\.venv\Scripts\python.exe -B -X utf8 setup-environments.py latest
```

既に完成したプロファイルは上書きしない。試用版の通信・インストール失敗後は同じコマンドで再試行できる。試用版の作成は公式の `git clone` → `uv sync --extra cu128` を実行し、エディター用のFastAPI・uvicorn・python-multipartを試用版だけに追加する。起動は `.venv` のPythonを直接使用し、公式の `uv run --no-sync` と同じく再同期を行わない。

`environments/` はローカル専用でGit対象外。モデルとCUDA環境を独立保存するため追加ディスク容量が必要。

## 固定範囲

固定版は `E:\Irodori-TTS` と既存 `.venv` をそのまま使う。この場所でgit pull・uv sync・pip installを行わない。
現在のHugging Faceキャッシュを `environments/stable/hf/hub` にリンクを実体化してコピーし、モデルの特定snapshot内のファイルを指定する。モデルが欠落したら停止し、最新版への自動切替はしない。補助モデルもオフライン取得のため、未キャッシュの依存モデルが必要になった場合は生成が失敗する。

`engine-source/` はGit情報・独自変更を含むソースの控え。`.venv`・生成音声・`my_work`・`ichigo_voice` は控えに含まない。`pip-freeze.txt` は導入済みパッケージ一覧で、完全な環境復元用ロックではない。災害復旧用の完全バックアップではないので、必要なら元のTTSフォルダとユーザーデータを別媒体へ保存する。

彩エディター自体は固定版でも現行コードを使う。試用版のエディターは作成時のコピーで、通常版の修正は自動反映しない。

## 設定と更新

`environments/stable.json` / `latest.json` を起動時に読み込む。`IRODORI_HOME` はエンジン、`EDITOR_CODE` はエディターコード、`EDITOR_DATA` は設定・辞書・保存データ、`EDITOR_PORT` はポート。`IRODORI_CHECKPOINT` はローカルモデルファイル、空欄なら `IRODORI_HF_CHECKPOINT` のモデルを取得する。

試用版は `EDITOR_SHARED_DATA` で通常版の辞書・登録マスターを読み取り専用参照する。追加・共有登録の編集は通常版で行う。変更は通常約1.8秒で反映し、生成中は完了後まで保留。試用版側で行マスターを選ぶか「共通マスターに設定」を押せば、音声をコピーせず使用できる。共通マスターの選択・話速・音声補正等は試用版ごとに保存する。

比較する `.irodori` はコピーを用意して開き、保存先・出力先も検証用にする。通常版のデータルートへの保存・出力は拒否する（その配下の試用版データ領域は使用可能）。通常版でマスターを削除すると試用版の割当も未登録になるため、試用中のマスターを通常版で削除しない。共有元に存在しない同梱マスターは試用版ローカルに取り込む。共有を解除する場合は `EDITOR_SHARED_DATA` を空にするが、共有IDを割り当てた行は別マスターへの再割当が必要になる。

次回の試用版更新は試用サーバーを終了した後、`environments/latest/Irodori-TTS` 内だけで `git pull --ff-only` と `uv sync --extra cu128` を実行する。エディター用追加依存が同期で削除された場合は、同フォルダで `uv pip install --python .venv/Scripts/python.exe fastapi uvicorn python-multipart` を実行する。固定版フォルダでは実行しない。

最新版のコードとモデルの版は別管理。新モデルへ変更するときは試用版JSONの `IRODORI_HF_CHECKPOINT` を変更し、サーバーを再起動する。最新コードとのAPI互換性と実際の生成品質は更新ごとに確認する。

共有対応の検証（2026-09-14）: 共有API・元データ不変・生成中の反映保留・共有マスターの保存/再読込を検証。試用版の実Python環境から辞書18件・共有マスター8件の参照と画面配信を確認。関連Pythonテスト5件とJavaScriptテスト3ファイルが成功。Python全体56件では6件が失敗し、改修前のコードでも同じ6件が再現した（疑似WAV、保存・マスター再利用・ゴミ箱の旧期待値）。ブラウザ実操作・GPU推論はこの共有改修では未検証。
