"""マルチYouTuber対応スケジューラー

各YouTuberのチャンネルから最新動画を取得し、
ショート動画を生成して本人のチャンネルにアップロードする。

フロー:
1. ShortsQueueにpendingがあれば1本アップロード
2. なければ最新動画を処理して複数ショート候補を生成
3. スコア閾値以上のものをキューに追加
4. その中から1本アップロード
"""

import asyncio
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from app.config import config
from app.logging_utils import log_error, log_info, log_warning
from app.models import CreateJobRequest, Job, JobArtifacts, JobOptions
from app.sheets import (
    add_shorts_to_queue,
    get_pending_shorts,
    get_queue_stats,
    get_youtubers,
    mark_short_uploaded,
    record_upload,
    update_youtuber_last_video,
)
from app.worker import run_job
from app.youtube_channel import VideoInfo, YouTuberInfo, get_latest_video, get_video_url, refresh_access_token

# YouTube API Key（チャンネル情報取得用、Gemini APIと共通）
YOUTUBE_API_KEY = os.getenv("GEMINI_API_KEY", "")

# OAuth クライアント情報
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")

# スコア閾値（これ以上のスコアのセグメントのみショート化）
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.6"))

# 1動画から生成する最大ショート数
MAX_SHORTS_PER_VIDEO = int(os.getenv("MAX_SHORTS_PER_VIDEO", "5"))


async def main():
    """
    メイン処理:
    1. スプシからYouTuberリストを取得
    2. 各YouTuberについて:
       - キューにpendingがあれば1本アップロード
       - なければ新しい動画を処理
    """
    log_info("=== Multi-YouTuber Auto Shorts Scheduler Started ===")
    log_info(f"Score threshold: {SCORE_THRESHOLD}, Max shorts per video: {MAX_SHORTS_PER_VIDEO}")

    if not YOUTUBE_API_KEY:
        log_error("GEMINI_API_KEY (YouTube API Key) is not set")
        return

    if not YOUTUBE_CLIENT_ID or not YOUTUBE_CLIENT_SECRET:
        log_error("YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET is not set")
        return

    try:
        # 1. スプシからYouTuberリストを取得
        youtubers = get_youtubers()

        if not youtubers:
            log_info("No active YouTubers found. Exiting.")
            return

        log_info(f"Found {len(youtubers)} active YouTuber(s)")

        # 2. 各YouTuberを処理
        for youtuber in youtubers:
            try:
                await process_youtuber(youtuber)
            except Exception as e:
                log_error(
                    f"Failed to process YouTuber {youtuber.name}: {e}",
                    exc_info=True
                )
                continue

        log_info("=== Multi-YouTuber Auto Shorts Scheduler Completed ===")

    except Exception as e:
        log_error(f"Scheduler failed: {e}", exc_info=True)
        raise


async def process_youtuber(youtuber: YouTuberInfo):
    """
    1人のYouTuberを処理

    Args:
        youtuber: YouTuber情報
    """
    log_info(f"Processing YouTuber: {youtuber.name} ({youtuber.channel_id})")

    # キューの状態を確認
    stats = get_queue_stats(youtuber.channel_id)
    log_info(f"Queue stats: pending={stats['pending']}, uploaded={stats['uploaded']}")

    # 1. キューにpendingがあるか確認
    pending_shorts = get_pending_shorts(youtuber.channel_id)

    if pending_shorts:
        log_info(f"Found {len(pending_shorts)} pending shorts in queue")
        # キューから1本アップロード
        await upload_from_queue(youtuber, pending_shorts[0])
        return

    # 2. キューが空なら新しい動画を処理
    log_info("No pending shorts, checking for new video...")

    # 最新動画を取得
    latest_video = get_latest_video(youtuber.channel_id, YOUTUBE_API_KEY)

    if not latest_video:
        log_warning(f"No videos found for {youtuber.name}")
        return

    log_info(f"Latest video: {latest_video.title} ({latest_video.video_id})")

    # 既に処理済みかチェック
    if youtuber.last_video_id == latest_video.video_id:
        log_info(f"Video already processed: {latest_video.video_id}")
        return

    # 3. 動画からショート候補を生成
    shorts_candidates = await create_shorts_from_video(
        video_info=latest_video,
        youtuber=youtuber
    )

    if not shorts_candidates:
        log_warning(f"No shorts candidates created for {youtuber.name}")
        # 動画は処理済みとしてマーク（次回スキップ）
        update_youtuber_last_video(
            row_index=youtuber.row_index,
            video_id=latest_video.video_id
        )
        return

    # 4. スコア閾値以上のものをフィルタ
    qualified_shorts = [s for s in shorts_candidates if s['score'] >= SCORE_THRESHOLD]

    log_info(f"Qualified shorts (score >= {SCORE_THRESHOLD}): {len(qualified_shorts)}/{len(shorts_candidates)}")

    if not qualified_shorts:
        log_warning(f"No shorts passed score threshold for {youtuber.name}")
        update_youtuber_last_video(
            row_index=youtuber.row_index,
            video_id=latest_video.video_id
        )
        return

    # 5. キューに追加
    add_shorts_to_queue(qualified_shorts)

    # 6. 最終処理動画IDを更新
    update_youtuber_last_video(
        row_index=youtuber.row_index,
        video_id=latest_video.video_id
    )

    # 7. 1本アップロード
    await upload_from_queue(youtuber, qualified_shorts[0])


async def upload_from_queue(youtuber: YouTuberInfo, short: dict) -> bool:
    """
    キューからショートをアップロード

    Args:
        youtuber: YouTuber情報
        short: ショート情報

    Returns:
        成功したかどうか
    """
    log_info(f"Uploading from queue: {short['title']} (score: {short['score']})")

    # アクセストークンを取得
    access_token = refresh_access_token(
        youtuber.refresh_token,
        YOUTUBE_CLIENT_ID,
        YOUTUBE_CLIENT_SECRET
    )

    if not access_token:
        log_error(f"Failed to get access token for {youtuber.name}")
        return False

    try:
        short_url = await upload_short(
            video_path=short['file_path'],
            title=short['title'],
            description=short['description'],
            access_token=access_token
        )

        if short_url:
            log_info(f"Uploaded short: {short_url}")

            # キューのステータスを更新
            if 'row_index' in short:
                mark_short_uploaded(short['row_index'], short_url)

            # UploadLogにも記録
            record_upload(
                youtuber_name=youtuber.name,
                channel_id=youtuber.channel_id,
                source_video_id=short['source_video_id'],
                short_title=short['title'],
                short_url=short_url
            )

            return True

    except Exception as e:
        log_error(f"Failed to upload short: {e}", exc_info=True)

    return False


async def create_shorts_from_video(
    video_info: VideoInfo,
    youtuber: YouTuberInfo
) -> list[dict]:
    """
    動画からショート動画候補を生成

    Args:
        video_info: 動画情報
        youtuber: YouTuber情報

    Returns:
        生成されたショート動画候補のリスト
    """
    log_info(f"Creating shorts from: {video_info.title}")

    # YouTube URLを生成
    video_url = get_video_url(video_info.video_id)

    # ジョブリクエストを作成（複数候補を生成）
    job_request = CreateJobRequest(
        source_type="youtube_url",
        youtube_url=video_url,
        title_hint=video_info.title,
        options=JobOptions(
            target_count=MAX_SHORTS_PER_VIDEO,
            min_sec=30,
            max_sec=45
        )
    )

    # ジョブを実行
    job_id = str(uuid.uuid4())
    JOBS = {}

    job = Job(
        job_id=job_id,
        status="queued",
        progress=0.0,
        message="Job queued",
        inputs=job_request,
        artifacts=JobArtifacts(),
        outputs=[],
        trace_id=f"trace-{job_id[:12]}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        attempt=1
    )

    JOBS[job_id] = job

    log_info(f"Starting job {job_id}")

    await run_job(job_id, job_request, JOBS)

    result = JOBS[job_id]

    if result.status != "done":
        log_error(f"Job failed: {result.message}")
        return []

    log_info(f"Job completed: {len(result.outputs)} clips generated")

    # 出力ファイルの情報を収集
    shorts_candidates = []

    for idx, output in enumerate(result.outputs):
        video_file = output.file_name
        if not video_file:
            continue

        video_path = Path(video_file)
        if not video_path.is_absolute():
            video_path = Path(config.TMP_DIR) / video_file

        # セグメント情報を取得
        segment = output.segment or {}
        segment_start = segment.get("start", 0)
        segment_end = segment.get("end", 0)

        # スコアと理由を取得（artifactsから）
        score = 0.5
        reason = ""

        # artifactsのsegmentsからスコアと理由を探す
        for seg in result.artifacts.segments:
            if abs(seg.start - segment_start) < 1.0 and abs(seg.end - segment_end) < 1.0:
                score = seg.score
                reason = seg.reason or ""
                break

        # AI生成タイトルと説明文
        from app.content_generator import generate_title_and_description

        segment_text = _extract_segment_transcript(
            result.artifacts.srt_path,
            segment_start,
            segment_end
        )

        content = generate_title_and_description(
            transcript_text=segment_text,
            source_url=video_url,
            fallback_title=f"{video_info.title} - Short {idx+1}"
        )

        shorts_candidates.append({
            'youtuber_name': youtuber.name,
            'channel_id': youtuber.channel_id,
            'source_video_id': video_info.video_id,
            'file_path': str(video_path.resolve()),
            'title': content["title"],
            'description': content["description"],
            'score': score,
            'reason': reason,
            'start_sec': segment_start,
            'end_sec': segment_end
        })

    # スコア順にソート
    shorts_candidates.sort(key=lambda x: x['score'], reverse=True)

    log_info(f"Created {len(shorts_candidates)} short candidates")
    for i, s in enumerate(shorts_candidates):
        log_info(f"  {i+1}. score={s['score']:.2f} | {s['title'][:30]}... | {s['reason']}")

    return shorts_candidates


async def upload_short(
    video_path: str,
    title: str,
    description: str,
    access_token: str
) -> str | None:
    """
    ショート動画をYouTubeにアップロード

    Args:
        video_path: 動画ファイルパス
        title: タイトル
        description: 説明文
        access_token: アクセストークン

    Returns:
        アップロードされた動画のURL
    """
    from app.youtube_upload import upload_video

    try:
        video_id = upload_video(
            video_path=video_path,
            title=title,
            description=description,
            access_token=access_token,
            privacy_status="public",
            is_short=True
        )

        if video_id:
            return f"https://youtube.com/shorts/{video_id}"

    except Exception as e:
        log_error(f"Upload failed: {e}", exc_info=True)

    return None


def _extract_segment_transcript(srt_path: str, start_sec: float, end_sec: float) -> str:
    """
    SRTファイルから指定時間範囲のテキストを抽出

    Args:
        srt_path: SRTファイルパス
        start_sec: 開始時刻（秒）
        end_sec: 終了時刻（秒）

    Returns:
        該当範囲のテキスト
    """
    try:
        if not srt_path or not Path(srt_path).exists():
            log_warning(f"SRT file not found: {srt_path}")
            return ""

        with open(srt_path, encoding='utf-8') as f:
            content = f.read()

        # SRT形式のパース
        pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)'
        matches = re.findall(pattern, content, re.DOTALL)

        def srt_time_to_seconds(time_str: str) -> float:
            """SRT時刻を秒に変換"""
            h, m, s = time_str.split(':')
            s, ms = s.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        # 該当範囲のテキストを収集
        texts = []
        for _, start_time, end_time, text in matches:
            start = srt_time_to_seconds(start_time)
            end = srt_time_to_seconds(end_time)

            # 範囲内のテキストのみ追加
            if start >= start_sec and end <= end_sec:
                texts.append(text.strip())

        return ' '.join(texts)

    except Exception as e:
        log_error(f"Failed to extract segment transcript: {e}", exc_info=True)
        return ""


if __name__ == "__main__":
    asyncio.run(main())
