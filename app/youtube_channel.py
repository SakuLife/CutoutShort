"""YouTubeチャンネル操作モジュール - 最新動画取得・トークン管理"""

from dataclasses import dataclass

import requests

from app.logging_utils import log_error, log_info


@dataclass
class VideoInfo:
    """動画情報"""
    video_id: str
    title: str
    description: str
    thumbnail_url: str
    published_at: str
    duration_seconds: int | None = None


@dataclass
class YouTuberInfo:
    """YouTuber情報（スプシから取得）"""
    name: str
    channel_id: str
    enabled: bool
    last_video_id: str | None
    last_processed_date: str | None
    refresh_token: str
    row_index: int  # スプシの行番号（更新用）


class YouTubeChannelError(Exception):
    """YouTubeチャンネル操作エラー"""
    pass


def get_latest_video(
    channel_id: str,
    api_key: str,
    min_duration_sec: int = 60
) -> VideoInfo | None:
    """
    チャンネルの最新動画を取得（ショート動画はスキップ）

    Args:
        channel_id: YouTubeチャンネルID（UCで始まる）
        api_key: YouTube Data API Key
        min_duration_sec: 最小動画長（秒）。これ未満はスキップ（デフォルト60秒）

    Returns:
        最新動画の情報、取得失敗時はNone
    """
    log_info(f"Fetching latest video for channel: {channel_id}")

    # チャンネルのuploadsプレイリストIDを取得
    uploads_playlist_id = _get_uploads_playlist_id(channel_id, api_key)
    if not uploads_playlist_id:
        log_error(f"Failed to get uploads playlist for channel: {channel_id}")
        return None

    # プレイリストから最新動画を複数取得（ショートをスキップするため）
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist_id,
        "maxResults": 10,  # 複数取得してショートをスキップ
        "key": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            log_info(f"No videos found for channel: {channel_id}")
            return None

        # 各動画の長さをチェックしてショートをスキップ
        for item in data["items"]:
            snippet = item["snippet"]
            content_details = item.get("contentDetails", {})
            video_id = content_details.get("videoId", snippet["resourceId"]["videoId"])

            # 動画の詳細情報を取得して長さをチェック
            duration = _get_video_duration(video_id, api_key)

            if duration is not None and duration < min_duration_sec:
                log_info(
                    f"Skipping short video ({duration}s): {snippet['title']}",
                    meta={"video_id": video_id}
                )
                continue

            video_info = VideoInfo(
                video_id=video_id,
                title=snippet["title"],
                description=snippet.get("description", ""),
                thumbnail_url=_get_best_thumbnail(snippet.get("thumbnails", {})),
                published_at=snippet["publishedAt"],
                duration_seconds=duration
            )

            log_info(
                f"Latest video found: {video_info.title}",
                meta={"video_id": video_info.video_id, "duration": duration}
            )

            return video_info

        log_info(f"No suitable videos found (all shorts?) for channel: {channel_id}")
        return None

    except requests.RequestException as e:
        log_error(f"Failed to fetch latest video: {e}")
        return None


def _get_video_duration(video_id: str, api_key: str) -> int | None:
    """動画の長さを取得（秒）"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "contentDetails",
        "id": video_id,
        "key": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return None

        duration_str = data["items"][0]["contentDetails"]["duration"]
        return _parse_iso8601_duration(duration_str)

    except (requests.RequestException, KeyError):
        return None


def _parse_iso8601_duration(duration: str) -> int:
    """ISO 8601形式の動画長を秒に変換（例: PT1H2M3S → 3723）"""
    import re
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def _get_uploads_playlist_id(channel_id: str, api_key: str) -> str | None:
    """チャンネルのuploadsプレイリストIDを取得"""
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "contentDetails",
        "id": channel_id,
        "key": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return None

        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    except (requests.RequestException, KeyError) as e:
        log_error(f"Failed to get uploads playlist: {e}")
        return None


def _get_best_thumbnail(thumbnails: dict) -> str:
    """利用可能な最高画質のサムネイルURLを取得"""
    for quality in ["maxres", "high", "medium", "default"]:
        if quality in thumbnails:
            return thumbnails[quality]["url"]
    return ""


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> str | None:
    """
    リフレッシュトークンからアクセストークンを取得

    Args:
        refresh_token: リフレッシュトークン
        client_id: OAuthクライアントID
        client_secret: OAuthクライアントシークレット

    Returns:
        アクセストークン、失敗時はNone
    """
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    try:
        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        access_token = data.get("access_token")
        if access_token:
            log_info("Access token refreshed successfully")
            return access_token

        log_error(f"No access token in response: {data}")
        return None

    except requests.RequestException as e:
        log_error(f"Failed to refresh access token: {e}")
        return None


def get_video_url(video_id: str) -> str:
    """動画IDからYouTube URLを生成"""
    return f"https://www.youtube.com/watch?v={video_id}"


def download_thumbnail(thumbnail_url: str, output_path: str) -> bool:
    """
    サムネイル画像をダウンロード

    Args:
        thumbnail_url: サムネイルURL
        output_path: 保存先パス

    Returns:
        成功時True
    """
    try:
        response = requests.get(thumbnail_url, timeout=30)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

        log_info(f"Thumbnail downloaded: {output_path}")
        return True

    except (OSError, requests.RequestException) as e:
        log_error(f"Failed to download thumbnail: {e}")
        return False
