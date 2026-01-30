"""YouTube API アップロード機能（マルチYouTuber対応）"""
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import config
from app.logging_utils import log_error, log_info
from app.youtube_channel import refresh_access_token

# YouTube API のスコープ
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


def get_youtube_service_from_refresh_token(refresh_token: str):
    """
    リフレッシュトークンからYouTube APIサービスを取得

    Args:
        refresh_token: スプシに保存されているリフレッシュトークン

    Returns:
        YouTube API サービスオブジェクト

    Raises:
        ValueError: トークン取得に失敗した場合
    """
    if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
        raise ValueError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env"
        )

    access_token = refresh_access_token(
        refresh_token=refresh_token,
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET
    )

    if not access_token:
        raise ValueError("Failed to refresh access token")

    creds = Credentials(token=access_token)
    return build('youtube', 'v3', credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    access_token: str,
    privacy_status: str = "public",
    category_id: str = "22",
    tags: list[str] | None = None,
    is_short: bool = True
) -> str | None:
    """
    アクセストークンを直接指定してYouTubeにアップロード
    （マルチYouTuber対応用）

    Args:
        video_path: 動画ファイルパス
        title: 動画タイトル
        description: 説明文
        access_token: YouTubeアクセストークン
        privacy_status: プライバシー設定 (public/private/unlisted)
        category_id: カテゴリID
        tags: タグリスト
        is_short: ショート動画かどうか

    Returns:
        動画ID（失敗時はNone）
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    log_info(f"Uploading to YouTube with token: {title}")

    try:
        # アクセストークンから認証情報を作成
        creds = Credentials(token=access_token)

        youtube = build('youtube', 'v3', credentials=creds)

        # ショート動画用のタグを追加
        default_tags = ['shorts', 'auto-generated']
        if is_short:
            default_tags.append('#Shorts')

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags or default_tags,
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False
            }
        }

        media = MediaFileUpload(
            video_path,
            chunksize=-1,
            resumable=True,
            mimetype='video/mp4'
        )

        log_info("Starting upload...")

        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log_info(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response['id']
        log_info(f"Upload complete: video_id={video_id}")

        return video_id

    except HttpError as e:
        log_error(f"YouTube API error: {e}", exc_info=True)
        return None
    except Exception as e:
        log_error(f"Upload failed: {e}", exc_info=True)
        return None


def upload_video_with_refresh_token(
    video_path: str,
    title: str,
    description: str,
    refresh_token: str,
    privacy_status: str = "public",
    category_id: str = "22",
    tags: list[str] | None = None,
    is_short: bool = True
) -> str | None:
    """
    リフレッシュトークンを使ってYouTubeにアップロード

    Args:
        video_path: 動画ファイルパス
        title: 動画タイトル
        description: 説明文
        refresh_token: スプシに保存されているリフレッシュトークン
        privacy_status: プライバシー設定
        category_id: カテゴリID
        tags: タグリスト
        is_short: ショート動画かどうか

    Returns:
        動画ID（失敗時はNone）
    """
    access_token = refresh_access_token(
        refresh_token=refresh_token,
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET
    )

    if not access_token:
        log_error("Failed to get access token from refresh token")
        return None

    return upload_video(
        video_path=video_path,
        title=title,
        description=description,
        access_token=access_token,
        privacy_status=privacy_status,
        category_id=category_id,
        tags=tags,
        is_short=is_short
    )


def get_video_url(video_id: str) -> str:
    """動画IDからYouTube URLを生成"""
    return f"https://www.youtube.com/watch?v={video_id}"