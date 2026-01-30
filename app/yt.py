"""yt-dlpラッパー - YouTube動画ダウンロード"""
import os
import subprocess
from pathlib import Path

from app.config import config
from app.logging_utils import log_error, log_info, log_warning


class YtDlpError(Exception):
    """yt-dlp例外"""
    pass


# Cookiesファイルパス（環境変数から取得）
YOUTUBE_COOKIES_PATH = os.getenv("YOUTUBE_COOKIES_PATH", "")


def download_youtube_video(
    url: str,
    output_path: str,
    job_id: str | None = None
) -> str:
    """
    YouTube動画をダウンロード

    Args:
        url: YouTube URL
        output_path: 保存先パス
        job_id: ジョブID（ログ用）

    Returns:
        保存先パス

    Raises:
        YtDlpError: ダウンロード失敗時
    """
    log_info(f"Downloading YouTube video: {url}", job_id=job_id, stage="downloading")

    # 出力ファイルパスを確保
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # yt-dlpコマンドを構築
    # H.264 + AAC形式でダウンロード（YouTubeショートに最適化）
    cmd = [
        "yt-dlp",
        "--format", "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_path,
        "--no-playlist",  # プレイリストの場合は最初の動画のみ
        "--no-warnings",
    ]

    # Cookiesファイルがあれば使用し、player_clientを最適化
    if YOUTUBE_COOKIES_PATH and Path(YOUTUBE_COOKIES_PATH).exists():
        cmd.extend(["--cookies", YOUTUBE_COOKIES_PATH])
        # Cookies使用時はデフォルトクライアント（tv_downgraded,web,web_safari）
        log_info("Using YouTube cookies for authentication", job_id=job_id)
    else:
        # Cookiesなし: web_embeddedはPO Token不要でBot検出を回避しやすい
        cmd.extend([
            "--extractor-args", "youtube:player_client=web_embedded,web_safari",
        ])
        log_info("No cookies, using web_embedded client for bot bypass", job_id=job_id)

    cmd.append(url)

    try:
        log_info(
            "Running yt-dlp command",
            job_id=job_id,
            meta={"command": " ".join(cmd)}
        )

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.DOWNLOAD_TIMEOUT,
            check=True,
        )

        log_info(f"YouTube download completed: {output_path}", job_id=job_id)

        # ダウンロードされたファイルが存在するか確認
        if not Path(output_path).exists():
            raise YtDlpError(f"Downloaded file not found: {output_path}")

        return output_path

    except subprocess.TimeoutExpired as e:
        log_error(
            f"yt-dlp timeout after {config.DOWNLOAD_TIMEOUT}s",
            job_id=job_id,
            exc_info=True
        )
        raise YtDlpError(f"YouTube download timeout: {e}") from e

    except subprocess.CalledProcessError as e:
        # Cookies使用時にBot検出されたら、web_embeddedクライアントでリトライ
        if "Sign in to confirm" in (e.stderr or "") and YOUTUBE_COOKIES_PATH:
            log_warning(
                "Bot detected with cookies, retrying with web_embedded client",
                job_id=job_id,
            )
            retry_cmd = [
                "yt-dlp",
                "--format",
                "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--output", output_path,
                "--no-playlist",
                "--no-warnings",
                "--extractor-args", "youtube:player_client=web_embedded,web_safari",
                url,
            ]
            try:
                subprocess.run(
                    retry_cmd,
                    capture_output=True,
                    text=True,
                    timeout=config.DOWNLOAD_TIMEOUT,
                    check=True,
                )
                if Path(output_path).exists():
                    log_info(f"Retry succeeded: {output_path}", job_id=job_id)
                    return output_path
            except subprocess.CalledProcessError as retry_e:
                log_error(
                    "Retry also failed",
                    job_id=job_id,
                    meta={"stderr": retry_e.stderr},
                )

        log_error(
            f"yt-dlp failed with return code {e.returncode}",
            job_id=job_id,
            meta={"stdout": e.stdout, "stderr": e.stderr},
            exc_info=True
        )
        raise YtDlpError(f"YouTube download failed: {e.stderr}") from e

    except Exception as e:
        log_error(f"Unexpected error in yt-dlp: {e}", job_id=job_id, exc_info=True)
        raise YtDlpError(f"YouTube download error: {e}") from e


def get_video_info(url: str, job_id: str | None = None) -> dict:
    """
    YouTube動画の情報を取得（タイトル、長さなど）

    Args:
        url: YouTube URL
        job_id: ジョブID（ログ用）

    Returns:
        動画情報の辞書

    Raises:
        YtDlpError: 情報取得失敗時
    """
    log_info(f"Getting YouTube video info: {url}", job_id=job_id)

    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
    ]

    # Cookiesファイルがあれば使用
    if YOUTUBE_COOKIES_PATH and Path(YOUTUBE_COOKIES_PATH).exists():
        cmd.extend(["--cookies", YOUTUBE_COOKIES_PATH])
    else:
        cmd.extend([
            "--extractor-args", "youtube:player_client=web_embedded,web_safari",
        ])

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )

        import json
        info = json.loads(result.stdout)

        video_info = {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "upload_date": info.get("upload_date", ""),
            "description": info.get("description", "")
        }

        log_info(
            "Video info retrieved",
            job_id=job_id,
            meta=video_info
        )

        return video_info

    except subprocess.TimeoutExpired as e:
        log_error("get_video_info timeout", job_id=job_id, exc_info=True)
        raise YtDlpError(f"Video info retrieval timeout: {e}") from e

    except subprocess.CalledProcessError as e:
        log_error(
            "get_video_info failed",
            job_id=job_id,
            meta={"stderr": e.stderr},
            exc_info=True
        )
        raise YtDlpError(f"Video info retrieval failed: {e.stderr}") from e

    except Exception as e:
        log_error(f"Unexpected error in get_video_info: {e}", job_id=job_id, exc_info=True)
        raise YtDlpError(f"Video info error: {e}") from e
