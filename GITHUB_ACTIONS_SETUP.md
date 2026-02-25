# GitHub Actions セットアップ手順

GitHubリポジトリでこの自動化システムを動かすための設定手順です。

## 1. GitHub Secrets の設定

以下のURLから、リポジトリのSecretsを設定してください:
リポジトリの Settings → Secrets and variables → Actions

「New repository secret」をクリックして、以下の8つのSecretsを追加します。

### 必須Secrets一覧

| Secret名 | 説明 | 取得方法 |
|---------|------|---------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service AccountのJSON内容全体 | `service-account.json` の中身をコピー |
| `YOUTUBE_CLIENT_SECRET_JSON` | YouTube Client SecretのJSON内容全体 | `credentials/youtube-client-secret.json` の中身をコピー |
| `YOUTUBE_TOKEN_JSON` | YouTube認証トークン | `credentials/youtube-token.json` の中身をコピー |
| `MAKE_SHARED_SECRET` | API認証用の共有シークレット | 任意の文字列（例: `my_secret_key_123`） |
| `DRIVE_INPUT_FOLDER_ID` | Google Driveの入力フォルダID | DriveフォルダURLの最後の部分 |
| `DRIVE_READY_FOLDER_ID` | Google Driveの処理済みフォルダID | DriveフォルダURLの最後の部分 |
| `GEMINI_API_KEY` | Gemini APIキー | Google AI Studioから取得 |
| `SPREADSHEET_ID` | GoogleスプレッドシートID | スプレッドシートURLの `/d/` と `/edit` の間の部分 |

### 各Secretの詳細設定方法

#### 1. GOOGLE_SERVICE_ACCOUNT_JSON
```bash
# Windowsの場合
cat service-account.json
# 出力された内容全体をコピーしてGitHub Secretsに貼り付け
```

**重要**: JSON全体（`{` から `}` まで）をコピーしてください。改行も含めて全てコピーします。

#### 2. YOUTUBE_CLIENT_SECRET_JSON
```bash
cat credentials/youtube-client-secret.json
```

#### 3. YOUTUBE_TOKEN_JSON
```bash
cat credentials/youtube-token.json
```

#### 4. MAKE_SHARED_SECRET
任意の文字列を設定します。セキュリティのため、推測されにくい長い文字列を使用してください。

例:
```
AbCd1234EfGh5678IjKl9012MnOp
```

#### 5. DRIVE_INPUT_FOLDER_ID
Google Driveのフォルダを開いた時のURLから取得します。

例: `https://drive.google.com/drive/folders/1AbC123XyZ456DeF789GhI`
→ フォルダID: `1AbC123XyZ456DeF789GhI`

#### 6. DRIVE_READY_FOLDER_ID
処理済みファイルを移動するフォルダのID（上記と同じ方法で取得）

#### 7. GEMINI_API_KEY
[Google AI Studio](https://makersuite.google.com/app/apikey) から取得

#### 8. SPREADSHEET_ID
スプレッドシートのURLから取得します。

例: `https://docs.google.com/spreadsheets/d/1AbC123XyZ456DeF789GhI/edit`
→ スプレッドシートID: `1AbC123XyZ456DeF789GhI`

**重要**: スプレッドシートには「CutoutShort」という名前のシートが必要です。

## 2. スプレッドシートの準備

1. スプレッドシートに「CutoutShort」という名前のシートを作成（既にある場合はそのまま使用）
2. Service Accountのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）にスプレッドシートの編集権限を付与

## 3. Google Driveの準備

1. 入力フォルダと処理済みフォルダを作成
2. Service Accountのメールアドレスに両方のフォルダの編集権限を付与

## 4. ワークフローの実行

Secretsを設定したら、以下のいずれかの方法でワークフローを実行できます:

### 自動実行
毎日 12:00 JST（3:00 UTC）に自動実行されます。

### 手動実行
1. GitHubリポジトリの「Actions」タブを開く
2. 「Auto Shorts Scheduler」ワークフローを選択
3. 「Run workflow」ボタンをクリック

## 5. 動作確認

ワークフローが実行されると:
1. Google Driveの入力フォルダから動画をダウンロード
2. 動画を5本の縦型ショート動画に分割
3. YouTubeに1日1本ペースで予約投稿
4. スプレッドシートの「CutoutShort」シートに記録
5. 処理済みファイルを別フォルダに移動

ログはGitHub Actionsの実行画面で確認できます。

## トラブルシューティング

### Secretsの設定ミス
- JSON形式のSecretsは、`{` から `}` まで全体をコピー
- 改行やスペースも含めてそのままコピー
- ダブルクォートなどの特殊文字もエスケープ不要

### Service Accountのアクセスエラー
- DriveフォルダとSheetsがサービスアカウントと共有されているか確認
- 編集者権限が付与されているか確認

### YouTube認証エラー
- `YOUTUBE_TOKEN_JSON` が正しくコピーされているか確認
- ローカルで `python test_youtube_auth.py` を実行して再認証

### ワークフロー実行エラー
- GitHub Actionsの「Actions」タブでログを確認
- エラーメッセージから該当するSecretを確認・修正
