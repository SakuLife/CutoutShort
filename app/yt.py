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

# プロキシ（Bot検出回避用、例: socks5://user:pass@host:port）
YT_DLP_PROXY = os.getenv("YT_DLP_PROXY", "")


def _build_base_cmd() -> list[str]:
    """yt-dlp共通オプションを構築"""
    cmd = ["yt-dlp"]

    # プロキシ設定（最優先のBot検出回避策）
    if YT_DLP_PROXY:
        cmd.extend(["--proxy", YT_DLP_PROXY])

    return cmd


def _add_auth_args(cmd: list[str], job_id: str | None = None) -> None:
    """認証関連の引数を追加（Cookies or player_client）"""
    if YOUTUBE_COOKIES_PATH and Path(YOUTUBE_COOKIES_PATH).exists():
        cmd.extend(["--cookies", YOUTUBE_COOKIES_PATH])
        log_info("Using YouTube cookies for authentication", job_id=job_id)
    else:
        cmd.extend([
            "--extractor-args", "youtube:player_client=web_embedded,web_safari",
        ])
        log_info("No cookies, using web_embedded client for bot bypass", job_id=job_id)


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
    cmd = _build_base_cmd()
    cmd.extend([
        "--format", "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_path,
        "--no-playlist",
        "--no-warnings",
    ])
    _add_auth_args(cmd, job_id=job_id)
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
        # Bot検出時のリトライ: 別のplayer_clientを順に試す
        if "Sign in to confirm" in (e.stderr or ""):
            fallback_clients = [
                "web_embedded,web_safari",
                "tv_embedded",
                "web_creator,mweb",
            ]
            for clients in fallback_clients:
                log_warning(
                    f"Bot detected, retrying with player_client={clients}",
                    job_id=job_id,
                )
                retry_cmd = _build_base_cmd()
                retry_cmd.extend([
                    "--format",
                    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "--output", output_path,
                    "--no-playlist",
                    "--no-warnings",
                    "--extractor-args", f"youtube:player_client={clients}",
                    url,
                ])
                try:
                    subprocess.run(
                        retry_cmd,
                        capture_output=True,
                        text=True,
                        timeout=config.DOWNLOAD_TIMEOUT,
                        check=True,
                    )
                    if Path(output_path).exists():
                        log_info(
                            f"Retry succeeded with {clients}: {output_path}",
                            job_id=job_id,
                        )
                        return output_path
                except subprocess.CalledProcessError as retry_e:
                    log_warning(
                        f"Retry with {clients} also failed",
                        job_id=job_id,
                        meta={"stderr": (retry_e.stderr or "")[:200]},
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

    cmd = _build_base_cmd()
    cmd.extend(["--dump-json", "--no-playlist"])
    _add_auth_args(cmd, job_id=job_id)
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
