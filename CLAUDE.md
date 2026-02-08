# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

YouTube動画から自動でショート動画を生成・アップロードするシステム。マルチYouTuber対応。
GitHub Actions（毎日12:00 JST）で自動実行し、各YouTuberのチャンネルに投稿する。

## コマンド

```bash
# 開発環境
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# FastAPI サーバー起動
uvicorn app.main:app --reload --port 8080

# スケジューラー実行（GitHub Actionsと同じ）
python -m app.multi_scheduler

# コード品質
ruff check . --fix
ruff format .

# テスト
pytest
pytest --cov=app
```

## システム依存（Python外）

- **ffmpeg** / **ffprobe**: レンダリング・動画メタデータ取得
- **yt-dlp**: YouTube動画ダウンロード（pip経由でもOK）
- **日本語フォント**: fonts-noto-cjk（Ubuntu）/ Noto Sans CJK JP

## アーキテクチャ

### 2つのエントリーポイント

1. **`app/main.py`** - FastAPI HTTP API（Make/外部からジョブ投入）
2. **`app/multi_scheduler.py`** - GitHub Actions用スケジューラー（メイン運用）

### スケジューラーのフロー（multi_scheduler.py）

```
スプシ「YouTubers」シートから有効なYouTuber取得
  ↓
各YouTuberについて:
  ├─ ShortsQueueにpendingあり → 1本アップロードして終了
  └─ pending なし → 最新動画を処理↓
       ↓
YouTube最新動画を取得（youtube_channel.py）
  ↓
ジョブ実行: worker.pyの5フェーズパイプライン
  ↓
スコア閾値（SCORE_THRESHOLD）以上のショートをShortsQueueに追加
  ↓
1本だけアップロード、残りは翌日以降
```

### 5フェーズ ジョブパイプライン（worker.py）

```
Phase 1: ダウンロード  → drive_io.py / yt.py
Phase 2: 文字起こし    → transcribe.py（faster-whisper）
Phase 3: セグメント抽出 → cut_finder.py（Gemini LLM + 規則ベース）
Phase 4: レンダリング   → render.py + overlay_generator.py（ffmpeg）
Phase 5: アップロード   → youtube_upload.py / drive_io.py
```

各フェーズで失敗時のフォールバックあり（LLM→規則ベース→固定尺）。

### 認証の構成

| 用途 | 認証方式 | 設定場所 |
|------|---------|---------|
| Google Drive / Sheets | Service Account | `GOOGLE_APPLICATION_CREDENTIALS` |
| YouTube アップロード | OAuth refresh_token | スプシ「YouTubers」F列 |
| YouTube ダウンロード | Cookies（Bot回避） | `YOUTUBE_COOKIES` Secret |
| チャンネル情報取得 | API Key | `GEMINI_API_KEY`（共用） |

### スプレッドシートのシート構成

- **YouTubers**: チャンネル管理（名前, チャンネルID, refresh_token等）
- **ShortsQueue**: ショートのストック管理（スコア, ステータス, ファイルパス等）
- **UploadLog**: アップロード履歴

### 主要な環境変数

```
GOOGLE_APPLICATION_CREDENTIALS  # Service Account JSONパス
GEMINI_API_KEY                  # Gemini API + YouTube Data API兼用
SPREADSHEET_ID                  # Google Sheets ID
YOUTUBE_CLIENT_ID               # OAuth クライアントID
YOUTUBE_CLIENT_SECRET           # OAuth シークレット
YOUTUBE_COOKIES_PATH            # yt-dlp用Cookiesファイル
SCORE_THRESHOLD                 # ショート化スコア閾値（デフォルト0.6）
MAX_SHORTS_PER_VIDEO            # 1動画あたり最大ショート数（デフォルト5）
```

### GAS（gas/YouTubeAuth.gs）

YouTuberがブラウザでOAuth認証するためのWebアプリ。認証完了後、refresh_tokenをスプシに保存。
GASのCLIENT_ID/SECRET は .env と同じ値に統一する。

## 重要な設計判断

- **1日1本アップロード**: ShortsQueueからpendingを1本ずつ消化
- **スコアリング**: cut_finder.pyでGeminiが0.0〜1.0のスコアを付与。閾値以上のみキューに追加
- **段階的フォールバック**: LLM → 規則ベース（句読点+無音）→ 固定尺（35秒）
- **冪等性**: FastAPI側はidempotency_keyで重複ジョブ防止
- **並列制御**: `asyncio.Semaphore(MAX_CONCURRENT_JOBS)`でリソース保護

## カスタム例外

各モジュールに専用例外がある: `YtDlpError`, `TranscribeError`, `CutFinderError`, `RenderError`, `DriveIOError`, `YouTubeChannelError`

## GitHub Actions ランナー切り替え

現在: **Self-hosted**（自分のPC）

ワークフローファイル:
- `auto-shorts.yml` - 現在使用中
- `auto-shorts.github-hosted.yml.bak` - GitHub-hosted用バックアップ

### GitHub-hostedに戻す（無料枠が復活したら）

```powershell
cd D:\AutoSystem\PythonSystem\CutoutShort\.github\workflows
Rename-Item auto-shorts.yml auto-shorts.self-hosted.yml.bak
Rename-Item auto-shorts.github-hosted.yml.bak auto-shorts.yml
git add . && git commit -m "switch to github-hosted" && git push
```

### Self-hostedに戻す

```powershell
cd D:\AutoSystem\PythonSystem\CutoutShort\.github\workflows
Rename-Item auto-shorts.yml auto-shorts.github-hosted.yml.bak
Rename-Item auto-shorts.self-hosted.yml.bak auto-shorts.yml
git add . && git commit -m "switch to self-hosted" && git push
```

### Self-hostedランナーの起動

```powershell
cd D:\AutoSystem\PythonSystem\CutoutShort\.runner
.\run.cmd
```

常時起動したい場合はタスクスケジューラに登録（PC起動時に `run.cmd` を実行）。
