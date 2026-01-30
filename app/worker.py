"""ジョブ実行ワーカー"""
import re
from datetime import datetime
from pathlib import Path

from app import content_generator, cut_finder, drive_io, render, transcribe, yt
from app.config import config
from app.logging_utils import log_error, log_info, log_warning, set_trace_id
from app.models import CreateJobRequest, Job, OutputInfo, SegmentInfo


async def run_job(
    job_id: str,
    job_request: CreateJobRequest,
    jobs_store: dict[str, Job]
) -> None:
    """
    ジョブを非同期で実行

    Args:
        job_id: ジョブID
        job_request: ジョブリクエスト
        jobs_store: ジョブストア（辞書）
    """
    # トレースIDをセット
    set_trace_id(f"trace-{job_id[:12]}")

    # ジョブを取得
    job = jobs_store.get(job_id)
    if not job:
        log_error(f"Job {job_id} not found in store", job_id=job_id)
        return

    try:
        log_info("Job started", job_id=job_id, stage="queued")

        # フェーズ1: ダウンロード
        await _phase_download(job, jobs_store)

        # フェーズ2: 文字起こし
        await _phase_transcribe(job, jobs_store)

        # フェーズ3: セグメント抽出
        await _phase_cut_selection(job, jobs_store)

        # フェーズ4: レンダリング
        if not job.inputs.options.dry_run:
            await _phase_render(job, jobs_store)

            # フェーズ5: アップロード
            await _phase_upload(job, jobs_store)

        # 完了
        job.status = "done"
        job.progress = 1.0
        job.message = f"Successfully created {len(job.outputs)} clips"
        job.updated_at = datetime.utcnow()
        jobs_store[job_id] = job

        log_info(
            "Job completed successfully",
            job_id=job_id,
            stage="done",
            meta={"output_count": len(job.outputs)}
        )

    except Exception as e:
        log_error(f"Job failed: {e}", job_id=job_id, exc_info=True)

        job.status = "error"
        job.message = f"Error: {e!s}"
        job.updated_at = datetime.utcnow()
        jobs_store[job_id] = job


async def _phase_download(job: Job, jobs_store: dict[str, Job]) -> None:
    """フェーズ1: 入力ファイルをダウンロード"""
    job.status = "downloading"
    job.progress = 0.1
    job.updated_at = datetime.utcnow()
    jobs_store[job.job_id] = job

    log_info("Phase 1: Downloading input", job_id=job.job_id, stage="downloading")

    # 一時ファイルパス
    local_in = config.get_tmp_path(f"{job.job_id}_input.mp4")

    try:
        if job.inputs.source_type == "drive":
            # Drive からダウンロード
            drive_io.download_from_drive(
                file_id=job.inputs.drive_file_id,
                output_path=local_in,
                job_id=job.job_id
            )

        elif job.inputs.source_type == "youtube_url":
            # YouTube からダウンロード
            yt.download_youtube_video(
                url=job.inputs.youtube_url,
                output_path=local_in,
                job_id=job.job_id
            )

        else:
            raise ValueError(f"Unknown source_type: {job.inputs.source_type}")

        job.artifacts.local_in = local_in
        job.progress = 0.2
        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"Download failed: {e}", job_id=job.job_id, exc_info=True)
        raise


async def _phase_transcribe(job: Job, jobs_store: dict[str, Job]) -> None:
    """フェーズ2: 文字起こし"""
    job.status = "transcribing"
    job.progress = 0.3
    job.updated_at = datetime.utcnow()
    jobs_store[job.job_id] = job

    log_info("Phase 2: Transcribing", job_id=job.job_id, stage="transcribing")

        # 動画の長さをチェック（念のため二重チェック）
    try:
        duration = transcribe.get_video_duration(job.artifacts.local_in)
        min_duration = job.inputs.options.min_sec
        
        if duration < min_duration:
            log_error(
                f"Video too short: {duration:.1f}s < {min_duration}s",
                job_id=job.job_id
            )
            raise ValueError(f"Video duration ({duration:.1f}s) is shorter than minimum required ({min_duration}s)")
    except Exception as e:
        if "too short" in str(e).lower():
            raise
        log_warning(f"Could not check video duration: {e}", job_id=job.job_id)
        
    try:
        srt_path, transcript_json = transcribe.transcribe_to_srt(
            in_mp4=job.artifacts.local_in,
            job_id=job.job_id
        )

        job.artifacts.srt_path = srt_path
        job.artifacts.transcript_json = transcript_json
        job.progress = 0.5
        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"Transcription failed: {e}", job_id=job.job_id, exc_info=True)

        # フォールバック: 固定尺で3本生成
        log_warning("Falling back to fixed-duration segments", job_id=job.job_id)
        await _fallback_fixed_segments(job, jobs_store)
        raise


async def _phase_cut_selection(job: Job, jobs_store: dict[str, Job]) -> None:
    """フェーズ3: 切り出しセグメント選定"""
    job.status = "cut_selecting"
    job.progress = 0.6
    job.updated_at = datetime.utcnow()
    jobs_store[job.job_id] = job

    log_info("Phase 3: Selecting segments", job_id=job.job_id, stage="cut_selecting")

    try:
        segments = cut_finder.pick_segments(
            transcript_json=job.artifacts.transcript_json,
            video_path=job.artifacts.local_in,
            target_num=job.inputs.options.target_count,
            min_sec=job.inputs.options.min_sec,
            max_sec=job.inputs.options.max_sec,
            title_hint=job.inputs.title_hint,
            force_rule_based=job.inputs.options.force_rule_based,
            job_id=job.job_id
        )

        job.artifacts.segments = segments
        job.progress = 0.7
        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"Segment selection failed: {e}", job_id=job.job_id, exc_info=True)
        raise


async def _phase_render(job: Job, jobs_store: dict[str, Job]) -> None:
    """フェーズ4: レンダリング"""
    job.status = "rendering"
    job.progress = 0.75
    job.updated_at = datetime.utcnow()
    jobs_store[job.job_id] = job

    log_info("Phase 4: Rendering clips", job_id=job.job_id, stage="rendering")

    try:
        overlay_title, overlay_bottom = _build_overlay_texts(job)

        rendered_files = render.render_clipset(
            in_mp4=job.artifacts.local_in,
            srt_path=job.artifacts.srt_path,
            segments=job.artifacts.segments,
            output_dir=config.TMP_DIR,
            job_id=job.job_id,
            title=overlay_title,
            bottom_text=overlay_bottom
        )

        job.artifacts.rendered_files = rendered_files
        job.progress = 0.85
        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"Rendering failed: {e}", job_id=job.job_id, exc_info=True)
        raise


def _build_overlay_texts(job: Job) -> tuple[str, str]:
    """タイトルと下部テキストを生成（LLM→フォールバック）。"""
    try:
        transcript_text = " ".join(seg.text for seg in job.artifacts.transcript_json) or ""
    except Exception:
        transcript_text = ""

    fallback_title = job.inputs.title_hint or "メインのタイトル"
    try:
        gen = content_generator.generate_title_and_description(
            transcript_text=transcript_text or fallback_title,
            source_url=None,
            fallback_title=fallback_title,
        )
        generated_title = gen.get("title") or fallback_title
        description = gen.get("description", "")
        log_info(
            "AI generated overlay text",
            job_id=job.job_id,
            meta={
                "title_raw": (generated_title or "")[:80],
                "description_head": (description or "").replace("\n", " ")[:120],
            },
        )
    except Exception as e:
        log_warning(f"Title generation failed, using fallback: {e}", job_id=job.job_id)
        generated_title = fallback_title
        description = ""

    # 文字化け（?だらけなど）を検知してフォールバック
    if _looks_garbled(generated_title):
        generated_title = fallback_title
    generated_title = _fit_overlay_text(generated_title, 12)

    # 下部テキストは説明の先頭行/文から短く抽出
    bottom_raw = _shorten_bottom_text(description, max_len=24)
    bottom = bottom_raw or "動画のポイント"
    if _looks_garbled(bottom):
        bottom = "動画のポイント"
    bottom = _fit_overlay_text(bottom, 18)
    log_info(
        "Overlay text after validation",
        job_id=job.job_id,
        meta={
            "title": generated_title,
            "bottom": bottom,
        },
    )
    return generated_title, bottom


def _shorten_bottom_text(description: str, max_len: int = 20) -> str:
    """説明文から先頭の短いフレーズを抽出."""
    if not description:
        return ""
    # 1行目を取得し、ハッシュタグ以降は削除
    first_line = description.splitlines()[0]
    first_line = first_line.split("#")[0]
    first_line = re.sub(r"\s+", " ", first_line).strip()
    if not first_line:
        return ""
    if len(first_line) > max_len:
        return first_line[:max_len] + "…"
    return first_line


def _fit_overlay_text(text: str, max_len: int) -> str:
    """オーバーレイ用に長さを制限（超過は末尾を省略記号で短縮）。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _looks_garbled(text: str) -> bool:
    """'?'や置換文字が多い/日本語が無い場合は文字化けとみなす."""
    if not text:
        return True

    s = text.strip()
    if not s:
        return True

    total = len(s)
    bad = s.count("?") + s.count("？") + s.count("\ufffd")
    q_ratio = bad / total
    has_cjk = any("\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff" for c in s)
    non_ascii = sum(1 for c in s if ord(c) > 127)
    non_ascii_ratio = non_ascii / total

    # 置換文字や?が1文字でもあれば問答無用で弾く
    if bad > 0:
        return True

    # 反復しがちな文字列（？？？など）は日本語が無ければ弾く
    no_space = s.replace(" ", "")
    repetitive = len(set(no_space)) <= 2 and len(no_space) >= 4
    mojibake_markers = ("縺", "繧", "蜿", "遘", "鬮", "髢", "邱")

    # 全角含む?や置換文字が20%以上、もしくは日本語無しで?が混入/同一文字ばかりならNG
    if q_ratio >= 0.2 or (not has_cjk and (q_ratio > 0 or repetitive)):
        return True

    # 日本語が無く、ASCIIを超える文字（文字化けパターン）が3割超ならNG（例: ã„ã§ã‚“）
    if not has_cjk and non_ascii_ratio > 0.3:
        return True

    # CP932系の文字化けでよく出る文字が含まれていればNG
    if any(marker in s for marker in mojibake_markers):
        return True

    return False


async def _phase_upload(job: Job, jobs_store: dict[str, Job]) -> None:
    """フェーズ5: ローカルファイル情報を記録（Driveアップロードはスキップ）"""
    job.status = "uploading"
    job.progress = 0.9
    job.updated_at = datetime.utcnow()
    jobs_store[job.job_id] = job

    log_info("Phase 5: Preparing local file download links", job_id=job.job_id, stage="uploading")

    try:
        outputs = []

        for i, (rendered_file, segment) in enumerate(
            zip(job.artifacts.rendered_files, job.artifacts.segments), start=1
        ):
            # ローカルファイルのダウンロードリンクを生成
            file_name = Path(rendered_file).name
            download_link = f"/download/{file_name}"

            # 動画の長さを取得
            duration_sec = segment.end - segment.start

            # OutputInfo を作成
            outputs.append(OutputInfo(
                file_name=file_name,
                drive_link=download_link,  # HTTPダウンロードリンク
                duration_sec=duration_sec,
                segment={"start": segment.start, "end": segment.end},
                method=segment.method
            ))

            log_info(f"File ready for download: {file_name}", job_id=job.job_id)

        job.outputs = outputs
        job.progress = 0.95
        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"File preparation failed: {e}", job_id=job.job_id, exc_info=True)
        raise


async def _fallback_fixed_segments(job: Job, jobs_store: dict[str, Job]) -> None:
    """
    Whisper失敗時のフォールバック: 固定尺で3本生成
    """
    log_warning("Using fallback: fixed-duration segments", job_id=job.job_id)

    try:
        # 動画の長さを取得
        duration = transcribe.get_video_duration(job.artifacts.local_in)

        # 固定尺セグメント（25-45秒の中間値: 35秒）
        segment_duration = (job.inputs.options.min_sec + job.inputs.options.max_sec) / 2
        num_segments = min(3, int(duration / segment_duration))

        segments = []
        for i in range(num_segments):
            start = i * segment_duration
            end = min(start + segment_duration, duration)

            segments.append(SegmentInfo(
                start=start,
                end=end,
                score=0.5,
                method="rule",
                reason="フォールバック（固定尺）"
            ))

        job.artifacts.segments = segments

        # 空のSRTを作成（字幕なし）
        srt_path = config.get_tmp_path(f"{job.job_id}_fallback.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("")  # 空ファイル

        job.artifacts.srt_path = srt_path
        job.artifacts.transcript_json = []

        job.updated_at = datetime.utcnow()
        jobs_store[job.job_id] = job

    except Exception as e:
        log_error(f"Fallback failed: {e}", job_id=job.job_id, exc_info=True)
        raise


def cleanup_job_files(job: Job) -> None:
    """
    ジョブの一時ファイルをクリーンアップ

    Args:
        job: ジョブ
    """
    try:
        # 入力ファイル
        if job.artifacts.local_in:
            Path(job.artifacts.local_in).unlink(missing_ok=True)

        # SRTファイル
        if job.artifacts.srt_path:
            Path(job.artifacts.srt_path).unlink(missing_ok=True)

        # レンダリング済みファイル
        for rendered_file in job.artifacts.rendered_files:
            Path(rendered_file).unlink(missing_ok=True)

        log_info("Cleaned up job files", job_id=job.job_id)

    except Exception as e:
        log_warning(f"Cleanup failed: {e}", job_id=job.job_id)
