/**
 * YouTuber OAuth認証システム
 *
 * 使い方:
 * 1. Google Cloud ConsoleでOAuthクライアントIDを作成
 * 2. 下のCLIENT_ID, CLIENT_SECRETを設定
 * 3. Webアプリとしてデプロイ
 * 4. デプロイURLをCloud ConsoleのリダイレクトURIに追加
 * 5. YouTuberにURLを共有してログインしてもらう
 */

// ===========================================
// 設定（Google Cloud Consoleから取得）
// ===========================================
const CLIENT_ID = 'YOUR_CLIENT_ID_HERE';
const CLIENT_SECRET = 'YOUR_CLIENT_SECRET_HERE';

// スプレッドシートID
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE';
const SHEET_NAME = 'YouTubers';

// OAuthスコープ（YouTubeアップロード権限）
const SCOPES = [
  'https://www.googleapis.com/auth/youtube.upload',
  'https://www.googleapis.com/auth/youtube.readonly'
].join(' ');

// ===========================================
// Webアプリのエントリーポイント
// ===========================================

/**
 * GETリクエスト処理
 * - 初回アクセス: 認証ページを表示
 * - コールバック: トークンを取得してスプシに保存
 */
function doGet(e) {
  const code = e.parameter.code;
  const error = e.parameter.error;

  // エラーがあれば表示
  if (error) {
    return createHtmlOutput(`
      <h1>認証エラー</h1>
      <p>エラー: ${error}</p>
      <p><a href="${getAuthUrl()}">もう一度試す</a></p>
    `);
  }

  // 認可コードがあればトークン取得
  if (code) {
    return handleCallback(code);
  }

  // 初回アクセス: 認証ページを表示
  return createAuthPage();
}

/**
 * 認証ページを作成
 */
function createAuthPage() {
  const authUrl = getAuthUrl();

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YouTubeショート自動投稿 - 認証</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      background: white;
      padding: 40px;
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      max-width: 500px;
      text-align: center;
    }
    h1 {
      color: #333;
      margin-bottom: 10px;
    }
    .subtitle {
      color: #666;
      margin-bottom: 30px;
    }
    .info-box {
      background: #f8f9fa;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 30px;
      text-align: left;
    }
    .info-box h3 {
      margin-top: 0;
      color: #333;
    }
    .info-box ul {
      margin: 0;
      padding-left: 20px;
      color: #555;
    }
    .info-box li {
      margin-bottom: 8px;
    }
    .auth-btn {
      display: inline-block;
      background: #ff0000;
      color: white;
      padding: 16px 40px;
      border-radius: 8px;
      text-decoration: none;
      font-size: 18px;
      font-weight: bold;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .auth-btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 30px rgba(255,0,0,0.3);
    }
    .note {
      margin-top: 20px;
      font-size: 12px;
      color: #999;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>YouTubeショート自動投稿</h1>
    <p class="subtitle">認証を行うと、あなたのチャンネルにショート動画を自動投稿できます</p>

    <div class="info-box">
      <h3>このシステムでできること</h3>
      <ul>
        <li>あなたの最新動画を自動でショート化</li>
        <li>毎日1本、自動でアップロード</li>
        <li>サムネイルとキャッチコピーを自動生成</li>
      </ul>
    </div>

    <div class="info-box">
      <h3>必要な権限</h3>
      <ul>
        <li>YouTubeへの動画アップロード</li>
        <li>チャンネル情報の読み取り</li>
      </ul>
    </div>

    <a href="${authUrl}" class="auth-btn">Googleでログイン</a>

    <p class="note">
      ※ パスワードは保存されません<br>
      ※ いつでも権限を取り消せます
    </p>
  </div>
</body>
</html>
  `;

  return HtmlService.createHtmlOutput(html)
    .setTitle('YouTubeショート自動投稿 - 認証');
}

/**
 * OAuth認可URLを生成
 */
function getAuthUrl() {
  const redirectUri = ScriptApp.getService().getUrl();

  const params = {
    client_id: CLIENT_ID,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: SCOPES,
    access_type: 'offline',  // リフレッシュトークンを取得
    prompt: 'consent'        // 毎回同意画面を表示（リフレッシュトークン確実に取得）
  };

  const queryString = Object.keys(params)
    .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
    .join('&');

  return `https://accounts.google.com/o/oauth2/v2/auth?${queryString}`;
}

/**
 * コールバック処理（トークン取得）
 */
function handleCallback(code) {
  const redirectUri = ScriptApp.getService().getUrl();

  // 認可コードをトークンに交換
  const tokenResponse = UrlFetchApp.fetch('https://oauth2.googleapis.com/token', {
    method: 'post',
    payload: {
      code: code,
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      redirect_uri: redirectUri,
      grant_type: 'authorization_code'
    },
    muteHttpExceptions: true
  });

  const tokenData = JSON.parse(tokenResponse.getContentText());

  if (tokenData.error) {
    return createHtmlOutput(`
      <h1>トークン取得エラー</h1>
      <p>${tokenData.error}: ${tokenData.error_description}</p>
      <p><a href="${getAuthUrl()}">もう一度試す</a></p>
    `);
  }

  const accessToken = tokenData.access_token;
  const refreshToken = tokenData.refresh_token;

  if (!refreshToken) {
    return createHtmlOutput(`
      <h1>エラー</h1>
      <p>リフレッシュトークンが取得できませんでした。</p>
      <p>Googleアカウントの<a href="https://myaccount.google.com/permissions" target="_blank">アプリの権限</a>からこのアプリを削除してから、もう一度お試しください。</p>
      <p><a href="${getAuthUrl()}">もう一度試す</a></p>
    `);
  }

  // チャンネル情報を取得
  const channelInfo = getChannelInfo(accessToken);

  if (!channelInfo) {
    return createHtmlOutput(`
      <h1>エラー</h1>
      <p>チャンネル情報の取得に失敗しました。</p>
      <p><a href="${getAuthUrl()}">もう一度試す</a></p>
    `);
  }

  // スプレッドシートに保存
  saveToSpreadsheet(channelInfo.title, channelInfo.id, refreshToken);

  // 成功ページを表示
  return createSuccessPage(channelInfo);
}

/**
 * チャンネル情報を取得
 */
function getChannelInfo(accessToken) {
  try {
    const response = UrlFetchApp.fetch(
      'https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',
      {
        headers: {
          'Authorization': `Bearer ${accessToken}`
        },
        muteHttpExceptions: true
      }
    );

    const data = JSON.parse(response.getContentText());

    if (data.items && data.items.length > 0) {
      const channel = data.items[0];
      return {
        id: channel.id,
        title: channel.snippet.title,
        thumbnail: channel.snippet.thumbnails.default.url
      };
    }
  } catch (e) {
    Logger.log('チャンネル情報取得エラー: ' + e.message);
  }

  return null;
}

/**
 * スプレッドシートに保存
 */
function saveToSpreadsheet(youtuberName, channelId, refreshToken) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SHEET_NAME);

  // シートがなければ作成
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    // ヘッダー行を追加
    sheet.getRange(1, 1, 1, 6).setValues([[
      'YouTuber名',
      'チャンネルID',
      '有効',
      '最終処理動画ID',
      '最終処理日',
      'refresh_token'
    ]]);
    // ヘッダーを太字に
    sheet.getRange(1, 1, 1, 6).setFontWeight('bold');
    // 列幅調整
    sheet.setColumnWidth(1, 150);
    sheet.setColumnWidth(2, 250);
    sheet.setColumnWidth(3, 60);
    sheet.setColumnWidth(4, 150);
    sheet.setColumnWidth(5, 120);
    sheet.setColumnWidth(6, 300);
  }

  // 既存のチャンネルIDを探す
  const data = sheet.getDataRange().getValues();
  let rowIndex = -1;

  for (let i = 1; i < data.length; i++) {
    if (data[i][1] === channelId) {
      rowIndex = i + 1; // 1-indexed
      break;
    }
  }

  const now = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');

  if (rowIndex > 0) {
    // 既存の行を更新（トークンのみ更新、他はそのまま）
    sheet.getRange(rowIndex, 6).setValue(refreshToken);
  } else {
    // 新しい行を追加
    const newRow = [
      youtuberName,
      channelId,
      true,  // 有効フラグ
      '',    // 最終処理動画ID（空）
      '',    // 最終処理日（空）
      refreshToken
    ];
    sheet.appendRow(newRow);
  }

  Logger.log(`Saved: ${youtuberName} (${channelId})`);
}

/**
 * 成功ページを作成
 */
function createSuccessPage(channelInfo) {
  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>認証完了</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
      min-height: 100vh;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      background: white;
      padding: 40px;
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      max-width: 500px;
      text-align: center;
    }
    .success-icon {
      font-size: 64px;
      margin-bottom: 20px;
    }
    h1 {
      color: #333;
      margin-bottom: 10px;
    }
    .channel-info {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 15px;
      background: #f8f9fa;
      padding: 20px;
      border-radius: 8px;
      margin: 20px 0;
    }
    .channel-info img {
      width: 60px;
      height: 60px;
      border-radius: 50%;
    }
    .channel-name {
      font-size: 18px;
      font-weight: bold;
      color: #333;
    }
    .channel-id {
      font-size: 12px;
      color: #666;
    }
    .message {
      color: #555;
      line-height: 1.6;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="success-icon">&#10004;</div>
    <h1>認証完了！</h1>

    <div class="channel-info">
      <img src="${channelInfo.thumbnail}" alt="Channel Icon">
      <div>
        <div class="channel-name">${channelInfo.title}</div>
        <div class="channel-id">${channelInfo.id}</div>
      </div>
    </div>

    <p class="message">
      あなたのチャンネルが登録されました。<br>
      これで自動ショート投稿が有効になります。<br><br>
      このページは閉じて大丈夫です。
    </p>
  </div>
</body>
</html>
  `;

  return HtmlService.createHtmlOutput(html)
    .setTitle('認証完了');
}

/**
 * HTMLレスポンスを作成（エラーページ用）
 */
function createHtmlOutput(body) {
  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YouTubeショート自動投稿</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f5f5;
      min-height: 100vh;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      background: white;
      padding: 40px;
      border-radius: 16px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.1);
      max-width: 500px;
      text-align: center;
    }
    a {
      color: #667eea;
    }
  </style>
</head>
<body>
  <div class="container">
    ${body}
  </div>
</body>
</html>
  `;

  return HtmlService.createHtmlOutput(html);
}

// ===========================================
// テスト用関数
// ===========================================

/**
 * 認証URLをログに出力（テスト用）
 */
function testGetAuthUrl() {
  Logger.log('Auth URL: ' + getAuthUrl());
  Logger.log('Redirect URI: ' + ScriptApp.getService().getUrl());
}
