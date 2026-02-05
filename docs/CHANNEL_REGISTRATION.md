# チャンネル登録マニュアル

新規YouTuber（契約者）のチャンネルを登録する手順。

## 概要

このシステムでは、各YouTuberのチャンネルに自動でショート動画をアップロードするため、OAuth認証（refresh_token）が必要。

## 必要な情報

| 項目 | 説明 | 取得方法 |
|------|------|----------|
| 名前 | YouTuber名（管理用） | 任意 |
| チャンネルID | UCxxxxxxxx形式 | YouTubeから取得 |
| refresh_token | OAuth認証トークン | OAuth Playgroundで取得 |

---

## 手順1: チャンネルIDの取得

### 通常のチャンネル

1. YouTubeでチャンネルページを開く
2. URLを確認: `https://www.youtube.com/channel/UCxxxxxxxxxx`
3. `UCxxxxxxxxxx`の部分がチャンネルID

### ブランドチャンネルの場合

ブランドチャンネル（ビジネスアカウント管理）の場合も、同じ方法でチャンネルIDを取得可能。

1. 対象のブランドチャンネルでYouTubeにログイン
2. [YouTube Studio](https://studio.youtube.com) にアクセス
3. 左下の「設定」→「チャンネル」→「詳細設定」
4. 「チャンネルID」が表示される

---

## 手順2: refresh_tokenの取得

Google OAuth Playgroundを使用して手動で取得する。

### 事前準備

プロジェクトの`.env`ファイルから以下を確認:
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`

### 取得手順

1. [Google OAuth Playground](https://developers.google.com/oauthplayground) にアクセス

2. 右上の歯車アイコンをクリック
   - 「Use your own OAuth credentials」にチェック
   - OAuth Client ID: `.env`の`YOUTUBE_CLIENT_ID`を入力
   - OAuth Client Secret: `.env`の`YOUTUBE_CLIENT_SECRET`を入力

3. 左側のスコープ選択で以下を選択:
   ```
   YouTube Data API v3
     → https://www.googleapis.com/auth/youtube.upload
   ```

4. 「Authorize APIs」をクリック

5. **重要: ブランドチャンネルの選択**
   - Googleアカウントでログイン
   - 複数チャンネルがある場合、**アップロード先のチャンネルを選択**
   - ブランドチャンネルの場合は、該当のブランドアカウントを選択

6. アクセス許可を承認

7. 「Exchange authorization code for tokens」をクリック

8. 表示された `refresh_token` をコピー
   ```json
   {
     "access_token": "...",
     "refresh_token": "1//xxxxxxxxxxxxx",  ← これをコピー
     "token_type": "Bearer",
     "expires_in": 3600
   }
   ```

### 注意点

- refresh_tokenは**一度しか表示されない**ので必ずコピー
- 複数チャンネルを持つアカウントの場合、認証時に正しいチャンネルを選択することが重要
- refresh_tokenは秘密情報として扱う

---

## 手順3: スプレッドシートへの登録

### シート構成

`YouTubers`シートに以下の形式で登録:

| A列 | B列 | C列 | D列 | E列 | F列 |
|-----|-----|-----|-----|-----|-----|
| 名前 | チャンネルID | 有効 | 最終処理動画ID | 最終処理日時 | refresh_token |
| サンプルYouTuber | UCxxxxxxxxxx | TRUE | | | 1//xxxxxx |

### 登録手順

1. [スプレッドシート](https://docs.google.com/spreadsheets/)を開く
2. `YouTubers`シートを選択
3. 新しい行に以下を入力:
   - **A列**: YouTuber名（管理用の名前）
   - **B列**: チャンネルID（UCxxxx形式）
   - **C列**: `TRUE`（有効化）
   - **D列**: 空欄（自動入力される）
   - **E列**: 空欄（自動入力される）
   - **F列**: 取得したrefresh_token

### 有効/無効の切り替え

- C列を`TRUE`にすると処理対象
- C列を`FALSE`にすると処理スキップ（一時停止に便利）

---

## 手順4: 動作確認

### GitHub Actionsで手動実行

1. GitHubリポジトリの「Actions」タブを開く
2. 「Multi-YouTuber Auto Shorts」ワークフローを選択
3. 「Run workflow」をクリック

### ログの確認

- ワークフロー実行後、ログを確認
- `Processing YouTuber: [名前]`が表示されていれば認識成功
- `Failed to get access token`が出る場合はrefresh_tokenが無効

---

## トラブルシューティング

### Q: refresh_tokenが無効になった

**原因**: Googleアカウントのセキュリティ設定変更、パスワード変更など

**対処**: 手順2を再実行してrefresh_tokenを再取得

### Q: 間違ったチャンネルにアップロードされた

**原因**: OAuth認証時に別のチャンネルを選択していた

**対処**:
1. 手順2を再実行
2. ステップ5で正しいブランドチャンネルを選択
3. 新しいrefresh_tokenをスプレッドシートに登録

### Q: 「チャンネルが見つからない」エラー

**原因**: チャンネルIDが間違っている

**対処**:
1. YouTube Studioでチャンネルの「詳細設定」を確認
2. 正しい`UC`で始まるIDをコピー

### Q: ブランドチャンネルを選択できない

**原因**: Googleアカウントがブランドチャンネルの管理者でない

**対処**: YouTubeの「アカウントを切り替える」でブランドアカウントにアクセスできるか確認

---

## セキュリティ上の注意

- `refresh_token`はパスワードと同等の機密情報
- スプレッドシートの共有設定に注意（必要最小限のアクセス権限に）
- refresh_tokenが漏洩した場合は、Google Cloud Consoleから該当トークンを無効化

---

## 関連ファイル

- `.env`: OAuth Client ID/Secret
- `app/sheets.py`: スプレッドシート操作
- `app/youtube_upload.py`: アップロード処理
