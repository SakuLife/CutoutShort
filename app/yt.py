"""yt-dlpラッパー - YouTube動画ダウンロード"""
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from app.config import config
from app.logging_utils import log_error, log_info, log_warning


class YtDlpError(Exception):
    """yt-dlp例外"""
    pass


# Cookiesファイルパス（環境変数から取得、フォールバック用）
YOUTUBE_COOKIES_PATH = os.getenv("YOUTUBE_COOKIES_PATH", "")

# プロキシ（Bot検出回避用、例: socks5://user:pass@host:port）
YT_DLP_PROXY = os.getenv("YT_DLP_PROXY", "")

# PO Token Server設定
POT_SERVER_BASE_URL = os.getenv(
    "POT_SERVER_BASE_URL",
    f"http://127.0.0.1:{os.getenv('POT_SERVER_PORT', '4416')}"
)

# PO Tokenサーバーの利用可否キャッシュ
_pot_server_available: bool | None = None


def _check_pot_server() -> bool:
    """PO Tokenサーバーが利用可能か確認（結果をキャッシュ）"""
    global _pot_server_available
    if _pot_server_available is not None:
        return _pot_server_available

    try:
        req = urllib.request.Request(f"{POT_SERVER_BASE_URL}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            _pot_server_available = resp.status == 200
    except Exception:
        _pot_server_available = False

    log_info(f"PO Token Server available: {_pot_server_available}")
    return _pot_server_available


def _build_base_cmd() -> list[str]:
    """yt-dlp共通オプションを構築"""
    cmd = ["yt-dlp"]

    # プロキシ設定（最優先のBot検出回避策）
    if YT_DLP_PROXY:
        cmd.extend(["--proxy", YT_DLP_PROXY])

    return cmd


def _add_auth_args(cmd: list[str], job_id: str | None = None) -> None:
    """認証関連の引数を追加（PO Token → Cookies → player_client）"""

    # 優先度1: PO Token Server（自動リフレッシュ、推奨）
    if _check_pot_server():
        # jim60105/bgutil-ytdlp-pot-provider-rs 用の正しいextractor-args形式
        cmd.extend([
            "--extractor-args",
            f"youtubepot-bgutil:getpot_bgutil_baseurl={POT_SERVER_BASE_URL}",
        ])
        log_info(f"Using PO Token Server at {POT_SERVER_BASE_URL}", job_id=job_id)
        return

    # 優先度2: Cookies（手動更新が必要、フォールバック）
    if YOUTUBE_COOKIES_PATH and Path(YOUTUBE_COOKIES_PATH).exists():
        cmd.extend(["--cookies", YOUTUBE_COOKIES_PATH])
        log_warning("PO Token Server unavailable, falling back to cookies", job_id=job_id)
        return

    # 優先度3: player_client指定（最終手段）
    cmd.extend([
        "--extractor-args", "youtube:player_client=web_embedded,web_safari",
    ])
    log_warning("No PO Token Server or cookies, using web_embedded client", job_id=job_id)


def _build_download_args(output_path: str, url: str) -> list[str]:
    """ダウンロード用の共通引数を構築"""
    return [
        "--format", "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_path,
        "--no-playlist",
        "--no-warnings",
    ]


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
    cmd.extend(_build_download_args(output_path, url))
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
        stderr = e.stderr or ""

        # 初回失敗の詳細をログ（PO Token診断用）
        log_warning(
            f"yt-dlp initial attempt failed (rc={e.returncode})",
            job_id=job_id,
            meta={"stderr_head": stderr[:500]},
        )

        # Bot検出時のリトライ
        if "Sign in to confirm" in stderr or "bot" in stderr.lower():
            result = _retry_bot_detected(url, output_path, job_id)
            if result:
                return result

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


def _retry_bot_detected(
    url: str, output_path: str, job_id: str | None
) -> str | None:
    """Bot検出時のリトライ処理"""

    # 優先度1: Cookiesでリトライ（設定されている場合）
    if YOUTUBE_COOKIES_PATH and Path(YOUTUBE_COOKIES_PATH).exists():
        log_warning(
            f"Bot detected, retrying with cookies: {YOUTUBE_COOKIES_PATH}",
            job_id=job_id,
        )
        retry_cmd = _build_base_cmd()
        retry_cmd.extend(_build_download_args(output_path, url))
        retry_cmd.extend(["--cookies", YOUTUBE_COOKIES_PATH])
        retry_cmd.append(url)

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
                    f"Retry with cookies succeeded: {output_path}",
                    job_id=job_id,
                )
                return output_path
        except subprocess.CalledProcessError as retry_e:
            log_warning(
                "Retry with cookies also failed",
                job_id=job_id,
                meta={"stderr": (retry_e.stderr or "")[:200]},
            )

    # 優先度2: player_clientフォールバック
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
        retry_cmd.extend(_build_download_args(output_path, url))
        retry_cmd.extend([
            "--extractor-args", f"youtube:player_client={clients}",
        ])
        retry_cmd.append(url)

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

    return None


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
