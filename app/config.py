"""環境変数管理モジュール"""
import os
from pathlib import Path

from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()


class Config:
    """設定管理クラス - 環境変数から設定を読み込む"""

    # API認証
    MAKE_SHARED_SECRET: str = os.getenv("MAKE_SHARED_SECRET", "")

    # Google Drive設定
    GOOGLE_APPLICATION_CREDENTIALS: str | None = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    DRIVE_INPUT_FOLDER_ID: str = os.getenv("DRIVE_INPUT_FOLDER_ID", "")
    DRIVE_READY_FOLDER_ID: str = os.getenv("DRIVE_READY_FOLDER_ID", "")
    DRIVE_OUTPUT_FOLDER_ID: str = os.getenv("DRIVE_OUTPUT_FOLDER_ID", "")

    # Whisper設定
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")  # tiny|base|small|medium|large
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cpu")  # cpu|cuda
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8|float16|float32

    # LLM設定（任意）
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")

    # Google Sheets設定
    SPREADSHEET_ID: str | None = os.getenv("SPREADSHEET_ID")
    SHEET_YOUTUBERS: str = os.getenv("SHEET_YOUTUBERS", "YouTubers")
    SHEET_UPLOAD_LOG: str = os.getenv("SHEET_UPLOAD_LOG", "UploadLog")

    # YouTube OAuth設定（マルチYouTuber用）
    YOUTUBE_CLIENT_ID: str = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "")

    # ジョブ管理
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))

    # ファイルパス
    TMP_DIR: str = os.getenv("TMP_DIR", "/tmp")

    # バージョン情報
    VERSION: str = "1.0.0"
    GIT_SHA: str = os.getenv("GIT_SHA", "dev")

    # ffmpeg設定
    FFMPEG_THREADS: int = int(os.getenv("FFMPEG_THREADS", "0"))  # 0=auto

    # リトライ設定
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF_BASE: float = float(os.getenv("RETRY_BACKOFF_BASE", "2.0"))  # 秒

    # タイムアウト設定
    DOWNLOAD_TIMEOUT: int = int(os.getenv("DOWNLOAD_TIMEOUT", "600"))  # 10分
    TRANSCRIBE_TIMEOUT: int = int(os.getenv("TRANSCRIBE_TIMEOUT", "1800"))  # 30分
    RENDER_TIMEOUT: int = int(os.getenv("RENDER_TIMEOUT", "600"))  # 10分
    UPLOAD_TIMEOUT: int = int(os.getenv("UPLOAD_TIMEOUT", "600"))  # 10分

    @classmethod
    def validate(cls) -> list[str]:
        """必須の設定値をチェックし、不足している項目のリストを返す"""
        errors = []

        if not cls.MAKE_SHARED_SECRET:
            errors.append("MAKE_SHARED_SECRET is required")

        if not cls.GOOGLE_APPLICATION_CREDENTIALS:
            errors.append("GOOGLE_APPLICATION_CREDENTIALS is required")
        elif not Path(cls.GOOGLE_APPLICATION_CREDENTIALS).exists():
            errors.append(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {cls.GOOGLE_APPLICATION_CREDENTIALS}")

        if not cls.DRIVE_INPUT_FOLDER_ID:
            errors.append("DRIVE_INPUT_FOLDER_ID is required")

        if not cls.DRIVE_READY_FOLDER_ID:
            errors.append("DRIVE_READY_FOLDER_ID is required")

        return errors

    @classmethod
    def get_tmp_path(cls, filename: str) -> str:
        """一時ファイルのパスを生成"""
        tmp_dir = Path(cls.TMP_DIR)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return str(tmp_dir / filename)


# グローバル設定インスタンス
config = Config()
