# ターミナルコマンド集（コピペ用）

デスクトップにリポジトリをクローンした場合の、ターミナルにコピペするだけで実行できるコマンドをまとめました。

---

## 🔧 事前準備

### Windowsの場合

PowerShellまたはコマンドプロンプトを開いて以下を実行:

```powershell
# デスクトップに移動
cd ~/Desktop

# リポジトリをクローン（初回のみ）
git clone https://github.com/<your-username>/<your-repo>.git

# リポジトリに移動
cd <your-repo>

# 最新版に更新
git pull
```

### Mac/Linuxの場合

ターミナルを開いて以下を実行:

```bash
# デスクトップに移動
cd ~/Desktop

# リポジトリをクローン（初回のみ）
git clone https://github.com/<your-username>/<your-repo>.git

# リポジトリに移動
cd <your-repo>

# 最新版に更新
git pull
```

---

## 📦 1. 必要なライブラリをインストール

リポジトリのルートディレクトリで実行:

```bash
pip install google-auth-oauthlib google-auth-httplib2
```

---

## 📁 2. client_secret.json を配置

### ダウンロードフォルダから移動する場合

**Windowsの場合:**
```powershell
# ダウンロードフォルダにあるclient_secret_*.jsonをリポジトリにコピー
Copy-Item ~\Downloads\client_secret_*.json .\client_secret.json
```

**Mac/Linuxの場合:**
```bash
# ダウンロードフォルダにあるclient_secret_*.jsonをリポジトリにコピー
cp ~/Downloads/client_secret_*.json ./client_secret.json
```

### 手動で配置する場合

1. Google Cloud Consoleからダウンロードした `client_secret_xxx.json` を開く
2. ファイルをリポジトリフォルダにドラッグ&ドロップ
3. ファイル名を `client_secret.json` にリネーム

---

## 🔐 3. YouTube認証トークンを生成

リポジトリのルートディレクトリで実行:

```bash
python generate_youtube_token.py
```

### 実行後の流れ:

1. ブラウザが自動的に開きます
2. **動画をアップロードするYouTubeアカウント**でログイン
3. 「このアプリは確認されていません」と表示されたら:
   - 左下の「**詳細**」をクリック
   - 「**（アプリ名）に移動（安全ではないページ）**」をクリック
4. アクセス権限のリクエストで「**許可**」をクリック
5. ブラウザに「認証フローが完了しました」と表示される
6. ターミナルに戻ると、1行のJSONが表示されます

### 表示された1行のJSONをコピー

ターミナルに表示された以下のような行を全てコピーしてください:

```
{"token": "ya29.a0...", "refresh_token": "1//0e...", "token_uri": "https://oauth2.googleapis.com/token", ...}
```

**この1行をGitHub Secretsに設定してください。**

---

## 📋 4. その他のJSON情報を取得（こちらで設定するため）

### サービスアカウントJSONを1行に圧縮

Google Cloud Consoleからダウンロードしたサービスアカウントの `.json` を、リポジトリのルートディレクトリに配置してから:

**ファイル名を確認:**
```bash
# Windowsの場合
dir *.json

# Mac/Linuxの場合
ls *.json
```

**1行に圧縮（ファイル名を実際の名前に置き換えてください）:**
```bash
python -c "import json; print(json.dumps(json.load(open('your-service-account.json'))))"
```

**出力された1行のJSONをGitHub Secretsに設定してください。**

### client_secret.json を1行に圧縮

```bash
python -c "import json; print(json.dumps(json.load(open('client_secret.json'))))"
```

**出力された1行のJSONをGitHub Secretsに設定してください。**

---

## 🎯 まとめ: 送ってもらう3つのJSON

以下の3つのコマンドを順番に実行して、出力された1行のJSONをそれぞれGitHub Secretsに設定してください:

### 1️⃣ YouTube認証トークン
```bash
python generate_youtube_token.py
```
→ ブラウザで認証後、表示される1行のJSONをコピー

### 2️⃣ サービスアカウントJSON（ファイル名は実際の名前に置き換え）
```bash
python -c "import json; print(json.dumps(json.load(open('your-service-account.json'))))"
```
→ 表示される1行のJSONをコピー

### 3️⃣ client_secret.json
```bash
python -c "import json; print(json.dumps(json.load(open('client_secret.json'))))"
```
→ 表示される1行のJSONをコピー

---

## ❓ トラブルシューティング

### 「python が見つかりません」エラー

Pythonがインストールされていない場合:

**Windowsの場合:**
1. [Python公式サイト](https://www.python.org/downloads/) からダウンロード
2. インストール時に「Add Python to PATH」にチェック

**Mac/Linuxの場合:**
```bash
# Macの場合（Homebrewを使用）
brew install python

# Ubuntuの場合
sudo apt install python3 python3-pip
```

### 「pip が見つかりません」エラー

```bash
# Windowsの場合
python -m ensurepip --upgrade

# Mac/Linuxの場合
python3 -m ensurepip --upgrade
```

### 「ModuleNotFoundError」エラー

```bash
# 必要なライブラリを再インストール
pip install --upgrade google-auth-oauthlib google-auth-httplib2
```

### ブラウザが自動的に開かない

ターミナルに表示されるURLを手動でコピーして、ブラウザに貼り付けてください:

```
Please visit this URL to authorize this application: https://accounts.google.com/o/oauth2/auth?...
```

### JSONのコピーに失敗する（Windowsの場合）

PowerShellでコマンドを実行後、出力を右クリックして「選択」→ドラッグで全選択 → Enterキーでコピー

---

## 📞 サポート

問題が解決しない場合は、エラーメッセージのスクリーンショットと一緒にIssueを作成してください。
