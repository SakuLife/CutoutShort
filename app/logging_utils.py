"""JSONロギングとトレース機能"""
import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any

# トレースIDをコンテキスト変数で管理（非同期環境でも安全）
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


class JSONFormatter(logging.Formatter):
    """JSON形式でログを出力するフォーマッタ"""

    def format(self, record: logging.LogRecord) -> str:
        """ログレコードをJSON形式に変換"""
        log_data = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "msg": record.getMessage(),
        }

        # トレースIDを追加
        trace_id = trace_id_var.get()
        if trace_id:
            log_data["trace_id"] = trace_id

        # 追加のメタデータ
        if hasattr(record, "job_id"):
            log_data["job_id"] = record.job_id

        if hasattr(record, "stage"):
            log_data["stage"] = record.stage

        if hasattr(record, "meta"):
            log_data["meta"] = record.meta

        # 例外情報
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """ロギングをセットアップ（コンソールをUTF-8に寄せる）"""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 既存のハンドラをクリア
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Windowsコンソールのcp932問題を避けるため、UTF-8ストリームを試す
    try:
        utf8_stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
        stream = utf8_stdout
    except Exception:
        stream = sys.stdout

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)


def set_trace_id(trace_id: str | None = None) -> str:
    """トレースIDをセット（指定がなければ自動生成）"""
    if trace_id is None:
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> str | None:
    """現在のトレースIDを取得"""
    return trace_id_var.get()


def clear_trace_id() -> None:
    """トレースIDをクリア"""
    trace_id_var.set(None)


class LogContext:
    """ログコンテキストマネージャー（with文で使用）"""

    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id
        self.previous_trace_id: str | None = None

    def __enter__(self) -> str:
        """コンテキスト開始時にトレースIDをセット"""
        self.previous_trace_id = get_trace_id()
        return set_trace_id(self.trace_id)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキスト終了時に元のトレースIDに戻す"""
        if self.previous_trace_id:
            trace_id_var.set(self.previous_trace_id)
        else:
            clear_trace_id()


def log_with_context(
    level: str,
    msg: str,
    job_id: str | None = None,
    stage: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """コンテキスト情報付きでログ出力"""
    logger = logging.getLogger(__name__)
    log_func = getattr(logger, level.lower())

    extra = {}
    if job_id:
        extra["job_id"] = job_id
    if stage:
        extra["stage"] = stage
    if meta:
        extra["meta"] = meta

    log_func(msg, extra=extra)


# 便利な関数
def log_info(
    msg: str,
    job_id: str | None = None,
    stage: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """INFOレベルでログ出力"""
    log_with_context("INFO", msg, job_id, stage, meta)


def log_error(
    msg: str,
    job_id: str | None = None,
    stage: str | None = None,
    meta: dict[str, Any] | None = None,
    exc_info: bool = False,
) -> None:
    """ERRORレベルでログ出力"""
    logger = logging.getLogger(__name__)
    extra = {}
    if job_id:
        extra["job_id"] = job_id
    if stage:
        extra["stage"] = stage
    if meta:
        extra["meta"] = meta

    logger.error(msg, extra=extra, exc_info=exc_info)


def log_warning(
    msg: str,
    job_id: str | None = None,
    stage: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """WARNINGレベルでログ出力"""
    log_with_context("WARNING", msg, job_id, stage, meta)


def log_debug(
    msg: str,
    job_id: str | None = None,
    stage: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """DEBUGレベルでログ出力"""
    log_with_context("DEBUG", msg, job_id, stage, meta)


# デフォルトでセットアップ
setup_logging()
