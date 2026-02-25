# GitHub Secrets設定ガイド

GitHub ActionsでCutoutShortを動作させるために必要なSecretsの設定方法を説明します。

---

## 方法1: YouTube認証を含む完全セットアップ（推奨）

YouTubeへの自動アップロード機能を使う場合はこちら。

### 前提条件

- Google Cloud Consoleで作成した `client_secret.json`
- 動画をアップロードするYouTubeアカウントへのアクセス
- Python環境

### 手順

#### 1. リポジトリをクローン・更新

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
git pull
```

#### 2. 必要なライブラリをインストール

```bash
pip install google-auth-oauthlib google-auth-httplib2
```

#### 3. client_secret.json を配置

Google Cloud Consoleからダウンロードした `client_secret_xxx.json` を `client_secret.json` という名前でリポジトリのルートディレクトリに配置します。

```bash
# 例: ダウンロードフォルダから移動
mv ~/Downloads/client_secret_*.json ./client_secret.json
```

#### 4. YouTube認証トークンを生成

```bash
python generate_youtube_token.py
```

- ブラウザが自動的に開きます
- **動画をアップロードするYouTubeアカウント**でログイン
- 「このアプリは確認されていません」→「詳細」→「移動」
- アクセス権限を「許可」

成功すると、以下のような1行のJSONが表示されます:

```json
{"token": "ya29.a0...", "refresh_token": "1//0e...", "token_uri": "https://oauth2.googleapis.com/token", ...}
```


#### 7. GitHub Secretsに設定

1. GitHubリポジトリのSettingsページを開く
2. **Settings** → **Secrets and variables** → **Actions**
3. 以下の3つのSecretを設定:

| Secret名 | 値 |
|---------|-----|
| `YOUTUBE_TOKEN_JSON` | 手順4でコピーした1行のJSON |

その他、以下のSecretsも必要です（既に設定済みの場合はスキップ）:
