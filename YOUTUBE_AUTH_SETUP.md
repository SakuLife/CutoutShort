# YouTube API認証情報の取得手順

このドキュメントでは、GitHub ActionsでYouTubeに動画をアップロードするために必要な認証情報（JSON）を取得する方法を説明します。

## 必要なもの

- Google Cloud Consoleへのアクセス権限
- 動画をアップロードするYouTubeアカウント
- Python環境（トークン生成用）

---

## 手順1: YouTube Data API v3を有効化

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 対象のプロジェクトを選択
3. 左メニュー → 「APIとサービス」 → 「ライブラリ」
4. 検索バーで「**YouTube Data API v3**」を検索
5. 「YouTube Data API v3」をクリック → 「**有効にする**」

---

## 手順2: OAuth 2.0 クライアントIDを作成

### 2-1. 認証情報ページへ移動

1. 左メニュー → 「APIとサービス」 → 「**認証情報**」
2. 上部の「**+ 認証情報を作成**」をクリック
3. 「**OAuth クライアント ID**」を選択

### 2-2. OAuth同意画面の設定（初回のみ）

同意画面の設定を求められた場合:

1. User Type: **「外部」** を選択 → 「作成」
2. アプリ情報:
   - アプリ名: `CutoutShort YouTube Uploader`（任意）
   - ユーザーサポートメール: 自分のメールアドレス
3. デベロッパーの連絡先情報: 自分のメールアドレス
4. 「**保存して次へ**」を3回クリックして完了

### 2-3. OAuthクライアントIDを作成

1. アプリケーションの種類: **「デスクトップアプリ」** を選択
2. 名前: `YouTube Upload Client`（任意）
3. 「**作成**」をクリック

### 2-4. クライアントシークレットJSONをダウンロード

1. 作成されたOAuth 2.0 クライアントIDの一覧で、作成したクライアントの右側にある **ダウンロードアイコン（↓）** をクリック
2. JSONファイルがダウンロードされます（例: `client_secret_xxx.json`）
3. このファイルをわかりやすい場所に保存（例: `client_secret.json`）

---

## 手順3: YouTube認証トークンを生成

クライアントシークレットだけではYouTubeにアップロードできません。**実際にYouTubeアカウントで認証したトークン**を生成する必要があります。

### 3-1. 必要なライブラリをインストール

```bash
pip install google-auth-oauthlib google-auth-httplib2
```

### 3-2. トークン生成スクリプトを実行

1. ダウンロードした `client_secret.json` をプロジェクトのルートディレクトリに配置
2. 以下のコマンドを実行:

```bash
python generate_youtube_token.py
```

3. ブラウザが自動的に開きます
4. **動画をアップロードするYouTubeアカウント**でログイン
5. 「このアプリは確認されていません」と表示された場合:
   - 左下の「**詳細**」をクリック
   - 「**（アプリ名）に移動（安全ではないページ）**」をクリック
6. アクセス権限のリクエストで「**許可**」をクリック
7. ブラウザに「認証フローが完了しました」と表示されたら成功

### 3-3. 生成されたトークンを確認

スクリプトが完了すると、以下のように1行のJSON形式で表示されます:

```
{"token": "ya29.a0...", "refresh_token": "1//0e...", "token_uri": "https://oauth2.googleapis.com/token", ...}
```

この**1行全体**をコピーしてください。

---

## 手順4: GitHub Secretsに設定

### 4-1. リポジトリのSettings → Secretsへ移動

1. GitHubリポジトリのSettingsページにアクセス
2. 「**Settings**」タブをクリック
3. 左メニュー → 「**Secrets and variables**」 → 「**Actions**」

### 4-2. YOUTUBE_CLIENT_SECRET_JSON を設定

1. 「**New repository secret**」をクリック
2. Name: `YOUTUBE_CLIENT_SECRET_JSON`
3. Secret: 手順2-4でダウンロードした `client_secret.json` の**内容全体を1行に圧縮**してペースト

**圧縮方法（オプション）:**
```bash
python -c "import json; print(json.dumps(json.load(open('client_secret.json'))))"
```

4. 「**Add secret**」をクリック

### 4-3. YOUTUBE_TOKEN_JSON を設定

1. 「**New repository secret**」をクリック
2. Name: `YOUTUBE_TOKEN_JSON`
3. Secret: 手順3-3でコピーした**1行のJSON**をペースト
4. 「**Add secret**」をクリック

---

## 確認

GitHub Actionsを手動実行して、以下のメッセージが表示されれば成功です:

```
✓ youtube-client-secret.json created successfully
✓ youtube-token.json created successfully
```

---

## トラブルシューティング

### 「service-account.json is not valid JSON」エラー

- JSONをコピーする際に、**余計な改行やスペースが入っていないか**確認
- 必ず**1行のJSON形式**で設定してください
- 上記の圧縮コマンドを使うと確実です

### 「このアプリは確認されていません」と表示される

- これは正常です。自分で作成したアプリなので「詳細」→「移動」で進んでください
- Googleの審査は不要です（自分のYouTubeチャンネルにアップロードするだけなので）

### トークンの有効期限

- `refresh_token` があれば、アクセストークンは自動的に更新されます
- 初回認証時に必ず `refresh_token` が含まれているか確認してください

---

## 参考

- [YouTube Data API - Upload Videos](https://developers.google.com/youtube/v3/guides/uploading_a_video)
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
