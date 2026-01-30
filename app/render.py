"""ffmpegレンダリング機能."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from app.config import config
from app.logging_utils import log_error, log_info
from app.models import SegmentInfo
from app.overlay_generator import generate_overlay_card


class RenderError(Exception):
    """レンダリング失敗時に送出."""


def render_clipset(
    in_mp4: str,
    srt_path: str,
    segments: list[SegmentInfo],
    output_dir: str | None = None,
    job_id: str | None = None,
    title: str | None = None,
    bottom_text: str | None = None,
    top_text: str | None = None,
) -> list[str]:
    """
    セグメントリストから複数のショート動画をレンダリングする.
    """
    log_info(f"Starting rendering {len(segments)} clips", job_id=job_id, stage="rendering")

    if output_dir is None:
        output_dir = str(Path(in_mp4).parent)
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    rendered_files: list[str] = []

    for i, segment in enumerate(segments, start=1):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = _sanitize_filename(title) if title else "clip"
            output_path = Path(output_dir) / f"{timestamp}_{i:02d}_{safe_title}.mp4"

            log_info(
                f"Rendering clip {i}/{len(segments)}: {segment.start:.1f}s - {segment.end:.1f}s",
                job_id=job_id,
                meta={"clip_num": i, "start": segment.start, "end": segment.end},
            )

            _render_single_clip(
                in_mp4=in_mp4,
                srt_path=srt_path,
                start=segment.start,
                end=segment.end,
                output_path=str(output_path),
                job_id=job_id,
                title=title,
                bottom_text=bottom_text,
                top_text=top_text,
            )

            rendered_files.append(str(output_path))
            log_info(f"Clip {i} rendered successfully: {output_path}", job_id=job_id)

        except Exception as e:
            log_error(f"Failed to render clip {i}: {e}", job_id=job_id, exc_info=True)
            continue

    if not rendered_files:
        raise RenderError("No clips were successfully rendered")

    log_info(f"Rendering completed: {len(rendered_files)} clips", job_id=job_id)
    return rendered_files


def _render_single_clip(
    in_mp4: str,
    srt_path: str,
    start: float,
    end: float,
    output_path: str,
    job_id: str | None,
    title: str | None = None,
    bottom_text: str | None = None,
    top_text: str | None = None,
) -> None:
    """
    単一クリップをレンダリング（9:16 1080x1920、レターボックス、グローオーバーレイ付き）.
    """
    duration = end - start

    overlay_top = top_text or "音楽業界社長が語る!!"
    overlay_title = title or "メインのタイトル"
    overlay_bottom = bottom_text or "動画のポイントとか"

    overlay_path = Path(output_path).with_suffix(".overlay.png")
    generate_overlay_card(
        output_path=str(overlay_path),
        top_text=overlay_top,
        title_text=overlay_title,
        bottom_text=overlay_bottom,
    )

    # メイン映像を9:16にレターボックス化
    vf_main = (
        "scale=iw*min(1080/iw\\,1920/ih):ih*min(1080/iw\\,1920/ih),"
        "pad=1080:1920:(1080-iw)/2:(1920-ih)/2,"
        "setsar=1"
    )

    # オーバーレイを重ねる
    vf_overlay = (
        "[0:v]" + vf_main + "[base];"
        "[1:v]format=rgba[ol];"
        "[base][ol]overlay=0:0,format=yuv420p[outv]"
    )

    af = "loudnorm=I=-16:TP=-1.5:LRA=11"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        in_mp4,
        "-i",
        str(overlay_path),
        "-filter_complex",
        vf_overlay,
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-af",
        af,
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        output_path,
    ]

    try:
        log_info(
            "Running ffmpeg command",
            job_id=job_id,
            meta={"command": " ".join(cmd[:10]) + "..."},
        )

        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.RENDER_TIMEOUT,
            check=True,
            encoding="utf-8",
            errors="ignore",
        )

        if not Path(output_path).exists():
            raise RenderError(f"Output file not created: {output_path}")

        file_size = Path(output_path).stat().st_size
        if file_size < 1000:
            raise RenderError(f"Output file too small: {file_size} bytes")

    except subprocess.TimeoutExpired as e:
        log_error(
            f"ffmpeg timeout after {config.RENDER_TIMEOUT}s",
            job_id=job_id,
            exc_info=True,
        )
        raise RenderError(f"Rendering timeout: {e}") from e

    except subprocess.CalledProcessError as e:
        log_error(
            f"ffmpeg failed with return code {e.returncode}",
            job_id=job_id,
            meta={"stderr": e.stderr[-500:] if e.stderr else ""},
            exc_info=True,
        )
        raise RenderError(f"Rendering failed: {e.stderr}") from e

    except Exception as e:
        log_error(f"Unexpected rendering error: {e}", job_id=job_id, exc_info=True)
        raise RenderError(f"Rendering error: {e}") from e

    finally:
        try:
            overlay_path.unlink(missing_ok=True)
        except Exception:
            pass


def get_video_resolution(video_path: str) -> tuple[int, int]:
    """動画の解像度を取得する."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            video_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        width, height = map(int, result.stdout.strip().split(","))
        return width, height

    except Exception as e:
        raise RenderError(f"Failed to get video resolution: {e}") from e


def _sanitize_filename(name: str, max_len: int = 40) -> str:
    """ファイル名に使えるようにサニタイズ."""
    if not name:
        return "clip"
    import re

    sanitized = re.sub(r'[\\\\/:*?"<>|]', "_", name)
    sanitized = sanitized.strip()
    if not sanitized:
        sanitized = "clip"
    if len(sanitized) > max_len:
        sanitized = sanitized[:max_len]
    return sanitized
