"""Whisper文字起こし機能"""
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

from app.config import config
from app.logging_utils import log_error, log_info
from app.models import TranscriptSegment


class TranscribeError(Exception):
    """文字起こし例外"""
    pass


def transcribe_to_srt(
    in_mp4: str,
    job_id: str | None = None
) -> tuple[str, list[TranscriptSegment]]:
    """
    動画ファイルを文字起こしし、SRTファイルとtranscript JSONを生成

    Args:
        in_mp4: 入力動画ファイルパス
        job_id: ジョブID（ログ用）

    Returns:
        (srt_path, transcript_json)
        - srt_path: SRTファイルパス
        - transcript_json: [{"start": float, "end": float, "text": str}]

    Raises:
        TranscribeError: 文字起こし失敗時
    """
    log_info(f"Starting transcription: {in_mp4}", job_id=job_id, stage="transcribing")

    # 入力ファイルの存在確認
    if not Path(in_mp4).exists():
        raise TranscribeError(f"Input file not found: {in_mp4}")

    try:
        # faster-whisperモデルをロード
        log_info(
            f"Loading Whisper model: {config.WHISPER_MODEL}",
            job_id=job_id,
            meta={
                "model": config.WHISPER_MODEL,
                "device": config.WHISPER_DEVICE,
                "compute_type": config.WHISPER_COMPUTE_TYPE
            }
        )

        model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE
        )

        # 文字起こし実行
        log_info("Running Whisper transcription...", job_id=job_id)
        segments, info = model.transcribe(
            in_mp4,
            language="ja",  # 日本語優先（自動検出も可）
            vad_filter=True,  # 音声区間検出
            word_timestamps=False  # 単語レベルのタイムスタンプは不要
        )

        log_info(
            "Transcription info",
            job_id=job_id,
            meta={
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration
            }
        )

        # セグメントを処理
        transcript_segments: list[TranscriptSegment] = []
        srt_lines: list[str] = []
        segment_num = 1

        for segment in segments:
            # transcript JSON用
            transcript_segments.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip()
                )
            )

            # SRT形式用
            srt_lines.append(str(segment_num))
            srt_lines.append(
                f"{_format_timestamp_srt(segment.start)} --> {_format_timestamp_srt(segment.end)}"
            )
            # 字幕は最大2行に整形（句読点で区切る）
            formatted_text = _format_subtitle_text(segment.text.strip())
            srt_lines.append(formatted_text)
            srt_lines.append("")  # 空行

            segment_num += 1

        log_info(
            f"Transcription completed: {len(transcript_segments)} segments",
            job_id=job_id,
            meta={"segment_count": len(transcript_segments)}
        )

        # SRTファイルを保存
        srt_path = str(Path(in_mp4).with_suffix(".srt"))
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

        log_info(f"SRT file saved: {srt_path}", job_id=job_id)

        return srt_path, transcript_segments

    except Exception as e:
        log_error(f"Transcription failed: {e}", job_id=job_id, exc_info=True)
        raise TranscribeError(f"Transcription error: {e}") from e


def _format_timestamp_srt(seconds: float) -> str:
    """
    秒数をSRT形式のタイムスタンプに変換

    Args:
        seconds: 秒数

    Returns:
        "HH:MM:SS,mmm" 形式の文字列
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = round((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_subtitle_text(text: str, max_lines: int = 2, max_chars_per_line: int = 30) -> str:
    """
    字幕テキストを整形（最大2行、句読点で区切る）

    Args:
        text: 元のテキスト
        max_lines: 最大行数
        max_chars_per_line: 1行あたりの最大文字数

    Returns:
        整形されたテキスト
    """
    # 句読点で分割
    delimiters = ["。", "、", "！", "？", ".", ",", "!", "?"]
    lines = []
    current_line = ""

    for char in text:
        current_line += char

        # 句読点で区切るか、最大文字数に達した場合
        if char in delimiters or len(current_line) >= max_chars_per_line:
            lines.append(current_line.strip())
            current_line = ""

            if len(lines) >= max_lines:
                break

    # 残りがあれば追加
    if current_line.strip() and len(lines) < max_lines:
        lines.append(current_line.strip())

    return "\n".join(lines[:max_lines])


def get_video_duration(video_path: str) -> float:
    """
    動画の長さを取得（秒）

    Args:
        video_path: 動画ファイルパス

    Returns:
        動画の長さ（秒）

    Raises:
        TranscribeError: 取得失敗時
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        duration = float(result.stdout.strip())
        return duration

    except Exception as e:
        log_error(f"Failed to get video duration: {e}", exc_info=True)
        raise TranscribeError(f"Failed to get video duration: {e}") from e
