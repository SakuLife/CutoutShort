"""Google Sheets 記録機能 + YouTuber管理"""
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import config
from app.logging_utils import log_error, log_info, log_warning
from app.youtube_channel import YouTuberInfo

# Google Sheets API のスコープ
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


def get_sheets_service():
    """
    Google Sheets API サービスを取得

    Returns:
        Sheets API サービスオブジェクト
    """
    credentials_path = Path(config.GOOGLE_APPLICATION_CREDENTIALS)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Google Service Account credentials not found at {credentials_path}. "
            "Please place your service-account.json file there."
        )

    credentials = Credentials.from_service_account_file(
        str(credentials_path),
        scopes=SCOPES
    )

    return build('sheets', 'v4', credentials=credentials)


def get_sheet(spreadsheet_id: str | None = None, worksheet_name: str = "CutoutShort"):
    """
    gspread を使ってワークシートオブジェクトを取得
    
    Args:
        spreadsheet_id: スプレッドシートID（未指定の場合は環境変数から取得）
        worksheet_name: ワークシート名（デフォルト: CutoutShort）
    
    Returns:
        gspread.Worksheet オブジェクト
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    credentials_path = Path(config.GOOGLE_APPLICATION_CREDENTIALS)

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Google Service Account credentials not found at {credentials_path}"
        )

    credentials = Credentials.from_service_account_file(
        str(credentials_path),
        scopes=SCOPES
    )

    gc = gspread.authorize(credentials)
    spreadsheet = gc.open_by_key(spreadsheet_id)
    
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        # ワークシートが存在しない場合は作成
        log_warning(f"Worksheet '{worksheet_name}' not found, creating new one")
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=12)
        
        # ヘッダーを追加
        headers = [
            '投稿日時', 'タイトル', 'YouTube URL', '動画秒数',
            '開始位置', '終了位置', '抽出方法', 'ステータス',
            'Input Tokens', 'Output Tokens', 'Total Tokens', 'コスト (円)'
        ]
        worksheet.append_row(headers)
        log_info(f"Created new worksheet '{worksheet_name}' with headers")
    
    return worksheet


def record_to_sheet(
    data: dict[str, Any],
    spreadsheet_id: str | None = None,
    range_name: str = "CutoutShort!A:L"
) -> dict[str, Any]:
    """
    Googleスプレッドシートに記録を追加

    Args:
        data: 記録するデータ（辞書形式）
        spreadsheet_id: スプレッドシートID（未指定の場合は環境変数から取得）
        range_name: 書き込み先の範囲（デフォルト: CutoutShort!A:L）

    Returns:
        APIレスポンス

    Raises:
        ValueError: spreadsheet_idが指定されていない場合
        HttpError: Google Sheets API エラー
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError(
            "Spreadsheet ID is required. "
            "Set SPREADSHEET_ID in .env or pass it as an argument."
        )

    log_info(f"Recording to spreadsheet: {spreadsheet_id}")

    try:
        service = get_sheets_service()

        # データを行形式に変換
        values = [[
            data.get('date', ''),
            data.get('title', ''),
            data.get('youtube_url', ''),
            data.get('duration', 0),
            data.get('segment_start', 0),
            data.get('segment_end', 0),
            data.get('method', ''),
            data.get('status', 'pending'),
            data.get('input_tokens', 0),
            data.get('output_tokens', 0),
            data.get('total_tokens', 0),
            f"¥{data.get('cost_jpy', 0.0):.4f}"
        ]]

        body = {
            'values': values
        }

        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()

        log_info(
            f"Recorded to sheet: {result.get('updates', {}).get('updatedRows', 0)} row(s) added"
        )

        return result

    except HttpError as e:
        log_error(f"Google Sheets API error: {e}", exc_info=True)
        raise
    except Exception as e:
        log_error(f"Failed to record to sheet: {e}", exc_info=True)
        raise


def initialize_sheet_headers(
    spreadsheet_id: str | None = None,
    range_name: str = "CutoutShort!A1:L1"
) -> dict[str, Any]:
    """
    スプレッドシートにヘッダー行を作成

    Args:
        spreadsheet_id: スプレッドシートID
        range_name: ヘッダーを書き込む範囲

    Returns:
        APIレスポンス
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    log_info(f"Initializing sheet headers: {spreadsheet_id}")

    try:
        service = get_sheets_service()

        headers = [[
            '投稿日時',
            'タイトル',
            'YouTube URL',
            '動画秒数',
            '開始位置',
            '終了位置',
            '抽出方法',
            'ステータス',
            'Input Tokens',
            'Output Tokens',
            'Total Tokens',
            'コスト (円)'
        ]]

        body = {
            'values': headers
        }

        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        log_info("Sheet headers initialized successfully")

        return result

    except HttpError as e:
        log_error(f"Google Sheets API error: {e}", exc_info=True)
        raise
    except Exception as e:
        log_error(f"Failed to initialize headers: {e}", exc_info=True)
        raise


def update_status(
    youtube_url: str,
    new_status: str,
    spreadsheet_id: str | None = None,
    range_name: str = "CutoutShort!C:H"
) -> dict[str, Any] | None:
    """
    YouTube URLを検索してステータスを更新

    Args:
        youtube_url: 検索するYouTube URL
        new_status: 新しいステータス
        spreadsheet_id: スプレッドシートID
        range_name: 検索範囲

    Returns:
        更新結果（見つからない場合はNone）
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    log_info(f"Updating status for: {youtube_url} -> {new_status}")

    try:
        service = get_sheets_service()

        # データを取得
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        values = result.get('values', [])

        # YouTube URLを検索（C列 = インデックス0）
        for idx, row in enumerate(values, start=2):  # ヘッダー行をスキップ
            if row and len(row) > 0 and row[0] == youtube_url:
                # ステータス列（H列 = 範囲内インデックス5）を更新
                update_range = f"CutoutShort!H{idx}"

                body = {
                    'values': [[new_status]]
                }

                update_result = service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=update_range,
                    valueInputOption='RAW',
                    body=body
                ).execute()

                log_info(f"Status updated for row {idx}")
                return update_result

        log_warning(f"YouTube URL not found in sheet: {youtube_url}")
        return None

    except HttpError as e:
        log_error(f"Google Sheets API error: {e}", exc_info=True)
        raise
    except Exception as e:
        log_error(f"Failed to update status: {e}", exc_info=True)
        raise


# ===========================================
# YouTuber管理機能
# ===========================================

def get_youtubers(
    spreadsheet_id: str | None = None,
    sheet_name: str = "YouTubers"
) -> list[YouTuberInfo]:
    """
    YouTubersシートから有効な契約者リストを取得

    Args:
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名

    Returns:
        YouTuberInfoのリスト
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    log_info(f"Fetching YouTubers from sheet: {sheet_name}")

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)
        all_values = worksheet.get_all_values()

        if len(all_values) <= 1:
            log_info("No YouTubers found in sheet")
            return []

        youtubers = []
        # ヘッダー行をスキップ（index 0）
        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 6:
                continue

            # 有効フラグをチェック（C列）
            enabled = str(row[2]).upper() in ('TRUE', '1', 'YES', 'はい')

            if not enabled:
                continue

            youtuber = YouTuberInfo(
                name=row[0],
                channel_id=row[1],
                enabled=enabled,
                last_video_id=row[3] if len(row) > 3 and row[3] else None,
                last_processed_date=row[4] if len(row) > 4 and row[4] else None,
                refresh_token=row[5] if len(row) > 5 else "",
                row_index=row_idx
            )

            if youtuber.refresh_token:
                youtubers.append(youtuber)
            else:
                log_warning(f"YouTuber {youtuber.name} has no refresh token, skipping")

        log_info(f"Found {len(youtubers)} active YouTubers")
        return youtubers

    except Exception as e:
        log_error(f"Failed to fetch YouTubers: {e}", exc_info=True)
        raise


def update_youtuber_last_video(
    row_index: int,
    video_id: str,
    spreadsheet_id: str | None = None,
    sheet_name: str = "YouTubers"
) -> None:
    """
    YouTuberの最終処理動画IDと日時を更新

    Args:
        row_index: スプシの行番号
        video_id: 処理した動画ID
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    log_info(f"Updating last video for row {row_index}: {video_id}")

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)

        # D列（最終処理動画ID）とE列（最終処理日）を更新
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.update(f"D{row_index}:E{row_index}", [[video_id, now]])

        log_info(f"Updated row {row_index}: video_id={video_id}, date={now}")

    except Exception as e:
        log_error(f"Failed to update YouTuber last video: {e}", exc_info=True)
        raise


def record_upload(
    youtuber_name: str,
    channel_id: str,
    source_video_id: str,
    short_title: str,
    short_url: str,
    duration_sec: float = 0,
    start_sec: float = 0,
    end_sec: float = 0,
    method: str = "",
    score: float = 0,
    reason: str = "",
    spreadsheet_id: str | None = None,
    sheet_name: str = "UploadLog"
) -> None:
    """
    アップロード記録をUploadLogシートに追加

    Args:
        youtuber_name: YouTuber名
        channel_id: チャンネルID
        source_video_id: 元動画のID
        short_title: ショート動画のタイトル
        short_url: ショート動画のURL
        duration_sec: 動画秒数
        start_sec: 開始位置（秒）
        end_sec: 終了位置（秒）
        method: 抽出方法（llm/rule）
        score: スコア
        reason: 選定理由
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    log_info(f"Recording upload: {short_title}")

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)

        # 記録を追加（既存ヘッダーに合わせる）
        # ヘッダー: 投稿日時 | タイトル | YouTube URL | 動画秒数 | 開始位置 | 終了位置 | 抽出方法 | ステータス | スコア | 選定理由 | YouTuber | 元動画ID
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.append_row([
            now,                    # 投稿日時
            short_title,            # タイトル
            short_url,              # YouTube URL
            round(duration_sec, 1), # 動画秒数
            round(start_sec, 1),    # 開始位置
            round(end_sec, 1),      # 終了位置
            method,                 # 抽出方法
            "uploaded",             # ステータス
            round(score, 2),        # スコア
            reason,                 # 選定理由
            youtuber_name,          # YouTuber
            source_video_id,        # 元動画ID
        ])

        log_info(f"Upload recorded: {short_url}")

    except Exception as e:
        log_error(f"Failed to record upload: {e}", exc_info=True)
        raise


def get_processed_video_ids(
    channel_id: str,
    spreadsheet_id: str | None = None,
    sheet_name: str = "UploadLog"
) -> set[str]:
    """
    UploadLogから指定チャンネルの処理済み元動画IDを取得

    Args:
        channel_id: チャンネルID
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名

    Returns:
        処理済み元動画IDのセット
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        return set()

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)
        rows = worksheet.get_all_values()

        if len(rows) <= 1:
            return set()

        # ヘッダー行をスキップ、L列(12列目)=元動画ID
        processed_ids: set[str] = set()
        for row in rows[1:]:
            if len(row) >= 12 and row[11]:  # 元動画ID列
                processed_ids.add(row[11])

        return processed_ids

    except Exception as e:
        log_warning(f"Failed to get processed video IDs: {e}")
        return set()


# ===========================================
# ShortsQueue機能（ショート動画のストック管理）
# ===========================================

SHORTS_QUEUE_HEADERS = [
    'YouTuber名',
    'チャンネルID',
    '元動画ID',
    'ファイルパス',
    'タイトル',
    '説明文',
    'スコア',
    '選定理由',
    '開始秒',
    '終了秒',
    'ステータス',
    'アップロード日時',
    'ショートURL',
    '作成日時'
]


def get_pending_shorts(
    channel_id: str,
    spreadsheet_id: str | None = None,
    sheet_name: str = "ShortsQueue"
) -> list[dict]:
    """
    未アップロードのショート動画を取得

    Args:
        channel_id: チャンネルID
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名

    Returns:
        未アップロードのショート情報リスト
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)
        all_values = worksheet.get_all_values()

        if len(all_values) <= 1:
            return []

        pending_shorts = []
        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 11:
                continue

            # チャンネルIDが一致 & ステータスがpending
            if row[1] == channel_id and row[10] == 'pending':
                pending_shorts.append({
                    'row_index': row_idx,
                    'youtuber_name': row[0],
                    'channel_id': row[1],
                    'source_video_id': row[2],
                    'file_path': row[3],
                    'title': row[4],
                    'description': row[5],
                    'score': float(row[6]) if row[6] else 0.0,
                    'reason': row[7],
                    'start_sec': float(row[8]) if row[8] else 0.0,
                    'end_sec': float(row[9]) if row[9] else 0.0,
                    'status': row[10]
                })

        # スコア順にソート（高い順）
        pending_shorts.sort(key=lambda x: x['score'], reverse=True)

        log_info(f"Found {len(pending_shorts)} pending shorts for {channel_id}")
        return pending_shorts

    except Exception as e:
        log_error(f"Failed to get pending shorts: {e}", exc_info=True)
        return []


def add_shorts_to_queue(
    shorts: list[dict],
    spreadsheet_id: str | None = None,
    sheet_name: str = "ShortsQueue"
) -> int:
    """
    ショート動画をキューに追加

    Args:
        shorts: ショート情報のリスト
            [{ youtuber_name, channel_id, source_video_id, file_path,
               title, description, score, reason, start_sec, end_sec }, ...]
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名

    Returns:
        追加した件数
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    if not shorts:
        return 0

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)

        # ヘッダーがなければ追加
        headers = worksheet.row_values(1)
        if not headers:
            worksheet.append_row(SHORTS_QUEUE_HEADERS)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rows_to_add = []
        for short in shorts:
            rows_to_add.append([
                short.get('youtuber_name', ''),
                short.get('channel_id', ''),
                short.get('source_video_id', ''),
                short.get('file_path', ''),
                short.get('title', ''),
                short.get('description', ''),
                short.get('score', 0.0),
                short.get('reason', ''),
                short.get('start_sec', 0.0),
                short.get('end_sec', 0.0),
                'pending',  # ステータス
                '',  # アップロード日時（空）
                '',  # ショートURL（空）
                now  # 作成日時
            ])

        # 一括追加
        worksheet.append_rows(rows_to_add)

        log_info(f"Added {len(rows_to_add)} shorts to queue")
        return len(rows_to_add)

    except Exception as e:
        log_error(f"Failed to add shorts to queue: {e}", exc_info=True)
        raise


def mark_short_uploaded(
    row_index: int,
    short_url: str,
    spreadsheet_id: str | None = None,
    sheet_name: str = "ShortsQueue"
) -> None:
    """
    ショートをアップロード済みにマーク

    Args:
        row_index: スプシの行番号
        short_url: アップロードされたショートのURL
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID is required")

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # K列(ステータス), L列(アップロード日時), M列(ショートURL)を更新
        worksheet.update(f"K{row_index}:M{row_index}", [['uploaded', now, short_url]])

        log_info(f"Marked row {row_index} as uploaded: {short_url}")

    except Exception as e:
        log_error(f"Failed to mark short as uploaded: {e}", exc_info=True)
        raise


def get_queue_stats(
    channel_id: str,
    spreadsheet_id: str | None = None,
    sheet_name: str = "ShortsQueue"
) -> dict:
    """
    キューの統計情報を取得

    Args:
        channel_id: チャンネルID
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名

    Returns:
        { pending: int, uploaded: int, total: int }
    """
    if not spreadsheet_id:
        spreadsheet_id = config.SPREADSHEET_ID

    if not spreadsheet_id:
        return {'pending': 0, 'uploaded': 0, 'total': 0}

    try:
        worksheet = get_sheet(spreadsheet_id, sheet_name)
        all_values = worksheet.get_all_values()

        pending = 0
        uploaded = 0

        for row in all_values[1:]:
            if len(row) >= 11 and row[1] == channel_id:
                if row[10] == 'pending':
                    pending += 1
                elif row[10] == 'uploaded':
                    uploaded += 1

        return {
            'pending': pending,
            'uploaded': uploaded,
            'total': pending + uploaded
        }

    except Exception as e:
        log_error(f"Failed to get queue stats: {e}", exc_info=True)
        return {'pending': 0, 'uploaded': 0, 'total': 0}
