# NUV Studio

GitHub Pagesで動作するNUV / MP4変換ツールです。ファイルはブラウザー内だけで処理します。

## 機能

- NUV → H.264 MP4。元の音声があれば最初の音声をAACで保存。
- 動画 → 非圧縮YUV420P NUV（映像のみ）。解像度・FPS指定。
- Python版が生成したNUVは構造を検証してから映像を取り出し、FFmpegのNUV終端エラーを回避。
- 入力128 MiB、NUV出力256 MiBまで。大きなファイルはPython版を使用。
- シングルスレッドffmpeg.wasm使用。SharedArrayBufferや特殊なHTTPヘッダーは不要。

## ローカル実行

Node.js 22以上、Python 3が必要です。

```sh
npm ci --ignore-scripts
npm run build
python -m http.server 8765 --directory dist
```

ブラウザーで http://localhost:8765 を開きます。

## GitHub Pages

このフォルダーの内容をリポジトリのルートに配置してください。
GitHubの Settings → Pages → Source で GitHub Actions を選択します。
mainへのpush、またはActionsのPublish GitHub Pagesを手動実行すると公開されます。
依存パッケージはビルド時に取得し、FFmpegエンジンをサイト自身から配信します。

## 制約

ブラウザーはネイティブFFmpegより遅く、変換にファイルサイズの数倍のメモリを使用します。
NUV作成時に削除された音声や解像度は復元できません。
外部のNUVはffmpeg.wasmの対応コーデックに依存します。破損ファイルでの復旧は保証しません。
FFmpeg出力にエラーがあるときは成功と断定せず、プレビューとログを表示します。

## 依存ライセンス

- @ffmpeg/ffmpeg: MIT（https://github.com/ffmpegwasm/ffmpeg.wasm）
- @ffmpeg/core: GPL-2.0-or-later（https://github.com/ffmpegwasm/ffmpeg.wasm/tree/main/packages/core）
- FFmpegソース: https://github.com/FFmpeg/FFmpeg
- ffmpeg.wasmビルドソース: https://github.com/ffmpegwasm/ffmpeg.wasm

ワークフローはnpmから公式配布物を取得します。ffmpeg.wasmのライセンス・ソースへのリンクは上記を参照してください。
