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
    get_processed_video_ids,
    get_queue_stats,
    get_youtubers,
    mark_short_uploaded,
    record_upload,
    update_youtuber_last_video,
)
from app.worker import run_job
from app.youtube_channel import VideoInfo, YouTuberInfo, get_latest_videos, get_video_url, refresh_access_token

# デバッグログ保存ディレクトリ
DEBUG_LOG_DIR = Path(os.getenv("DEBUG_LOG_DIR", "logs/debug"))


def _save_debug_log(
    youtuber_name: str,
    video_id: str,
    transcript: str,
    segments: list,
    candidates: list,
) -> None:
    """デバッグ用に台本・セグメント情報をファイルに保存"""
    try:
        DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', youtuber_name)
        filename = DEBUG_LOG_DIR / f"{timestamp}_{safe_name}_{video_id}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(f"DEBUG LOG: {youtuber_name}\n")
            f.write(f"Video ID: {video_id}\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n\n")

            # 台本（トランスクリプト）
            f.write("## TRANSCRIPT (文字起こし)\n")
            f.write("-" * 60 + "\n")
            f.write(transcript if transcript else "(empty)\n")
            f.write("\n\n")

            # セグメント抽出結果
            f.write("## SEGMENTS (抽出されたセグメント)\n")
            f.write("-" * 60 + "\n")
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}. [{seg.start:.1f}s - {seg.end:.1f}s] ")
                f.write(f"score={seg.score:.2f} method={seg.method}\n")
                f.write(f"   reason: {seg.reason}\n")
                if seg.hook_text:
                    f.write(f"   hook: {seg.hook_text}\n")
                f.write("\n")

            # 最終候補（タイトル生成後）
            f.write("## CANDIDATES (最終候補)\n")
            f.write("-" * 60 + "\n")
            for i, c in enumerate(candidates, 1):
                f.write(f"{i}. score={c['score']:.2f} | {c['method']}\n")
                f.write(f"   title: {c['title']}\n")
                f.write(f"   range: {c['start_sec']:.1f}s - {c['end_sec']:.1f}s\n")
                f.write(f"   reason: {c['reason']}\n")
                f.write("\n")

        log_info(f"    Debug log saved: {filename}")

    except Exception as e:
        log_warning(f"Failed to save debug log: {e}")


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
    log_info("")
    log_info("=" * 60)
    log_info("   AUTO SHORTS SCHEDULER - START")
    log_info("=" * 60)
    log_info(f"Score threshold: {SCORE_THRESHOLD}, Max shorts: {MAX_SHORTS_PER_VIDEO}")
    log_info("")

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

        log_info(f"Found {len(youtubers)} active YouTuber(s): {', '.join(y.name for y in youtubers)}")
        log_info("")

        # 処理結果を記録
        results: list[dict] = []

        # 2. 各YouTuberを処理
        for youtuber in youtubers:
            result = {
                "name": youtuber.name,
                "status": "unknown",
                "message": "",
                "short_url": None,
            }
            try:
                upload_result = await process_youtuber(youtuber)
                result["status"] = upload_result.get("status", "unknown")
                result["message"] = upload_result.get("message", "")
                result["short_url"] = upload_result.get("short_url")
            except Exception as e:
                result["status"] = "error"
                result["message"] = str(e)
                log_error(
                    f"Failed to process YouTuber {youtuber.name}: {e}",
                    exc_info=True
                )
            results.append(result)

        # 最終サマリーを出力
        _print_summary(results)

    except Exception as e:
        log_error(f"Scheduler failed: {e}", exc_info=True)
        raise


def _print_summary(results: list[dict]) -> None:
    """処理結果のサマリーを出力"""
    log_info("")
    log_info("=" * 60)
    log_info("   RESULTS SUMMARY")
    log_info("=" * 60)

    success_count = 0
    skip_count = 0
    error_count = 0

    for r in results:
        status = r["status"]
        name = r["name"]
        message = r["message"]
        short_url = r.get("short_url", "")

        if status == "uploaded":
            log_info(f"  [SUCCESS] {name}")
            log_info(f"            -> {short_url}")
            success_count += 1
        elif status == "skipped":
            log_info(f"  [SKIP]    {name} - {message}")
            skip_count += 1
        elif status == "error":
            log_info(f"  [ERROR]   {name} - {message}")
            error_count += 1
        else:
            log_info(f"  [???]     {name} - {message}")

    log_info("-" * 60)
    log_info(f"  Total: {len(results)} | Success: {success_count} | Skip: {skip_count} | Error: {error_count}")
    log_info("=" * 60)
    log_info("   AUTO SHORTS SCHEDULER - END")
    log_info("=" * 60)
    log_info("")


async def process_youtuber(youtuber: YouTuberInfo) -> dict:
    """
    1人のYouTuberを処理

    Args:
        youtuber: YouTuber情報

    Returns:
        処理結果 {"status": "uploaded"|"skipped"|"error", "message": str, "short_url": str|None}
    """
    log_info("")
    log_info("-" * 60)
    log_info(f"  CHANNEL: {youtuber.name}")
    log_info("-" * 60)

    # 最新動画を取得（複数候補）
    log_info(f"  Fetching latest videos...")
    candidates = get_latest_videos(youtuber.channel_id, YOUTUBE_API_KEY)

    if not candidates:
        log_warning(f"  No videos found")
        return {"status": "skipped", "message": "No videos found", "short_url": None}

    # UploadLogから処理済み動画IDを取得
    processed_ids = get_processed_video_ids(youtuber.channel_id)
    if youtuber.last_video_id:
        processed_ids.add(youtuber.last_video_id)

    # 未処理の動画を探す
    latest_video: VideoInfo | None = None
    for video in candidates:
        if video.video_id in processed_ids:
            log_info(f"  Already processed: {video.title[:40]}... - trying next")
            continue
        latest_video = video
        break

    if not latest_video:
        log_info(f"  All {len(candidates)} videos already processed - skipping")
        return {"status": "skipped", "message": "All videos processed", "short_url": None}

    log_info(f"  Selected: {latest_video.title[:40]}...")
    log_info(f"  Video ID: {latest_video.video_id}")

    # 1. 動画からショート候補を生成
    log_info(f"  Generating short candidates...")
    shorts_candidates = await create_shorts_from_video(
        video_info=latest_video,
        youtuber=youtuber
    )

    if not shorts_candidates:
        log_warning(f"  Failed to create short candidates")
        return {"status": "error", "message": "No shorts created", "short_url": None}

    # 2. スコア閾値以上のものをフィルタ
    qualified_shorts = [s for s in shorts_candidates if s['score'] >= SCORE_THRESHOLD]

    log_info(f"  Qualified: {len(qualified_shorts)}/{len(shorts_candidates)} (threshold: {SCORE_THRESHOLD})")

    if not qualified_shorts:
        log_warning(f"  No shorts passed score threshold")
        update_youtuber_last_video(
            row_index=youtuber.row_index,
            video_id=latest_video.video_id
        )
        return {"status": "skipped", "message": "No shorts above threshold", "short_url": None}

    # 3. 最高スコアのショートを即アップロード
    best_short = qualified_shorts[0]
    log_info(f"  Best short: score={best_short['score']:.2f}")
    log_info(f"  Title: {best_short['title'][:40]}...")

    # アクセストークンを取得
    log_info(f"  Getting access token...")
    access_token = refresh_access_token(
        youtuber.refresh_token,
        YOUTUBE_CLIENT_ID,
        YOUTUBE_CLIENT_SECRET
    )

    if not access_token:
        log_error(f"  Failed to get access token")
        return {"status": "error", "message": "Token refresh failed", "short_url": None}

    # 元動画のURL
    source_video_url = get_video_url(latest_video.video_id)

    # アップロード実行（18時に予約投稿）
    log_info(f"  Uploading to YouTube (scheduled 18:00 JST)...")
    short_url = await upload_short(
        video_path=best_short['file_path'],
        title=best_short['title'],
        description=best_short['description'],
        access_token=access_token,
        source_video_url=source_video_url,
        source_title=latest_video.title,
    )

    if short_url:
        log_info(f"  Upload SUCCESS!")
        log_info(f"  URL: {short_url}")

        # UploadLogに記録
        record_upload(
            youtuber_name=youtuber.name,
            channel_id=youtuber.channel_id,
            source_video_id=best_short['source_video_id'],
            short_title=best_short['title'],
            short_url=short_url,
            duration_sec=best_short.get('duration_sec', 0),
            start_sec=best_short.get('start_sec', 0),
            end_sec=best_short.get('end_sec', 0),
            method=best_short.get('method', ''),
            score=best_short.get('score', 0),
            reason=best_short.get('reason', ''),
        )

        # 最終処理動画IDを更新
        update_youtuber_last_video(
            row_index=youtuber.row_index,
            video_id=latest_video.video_id
        )

        return {"status": "uploaded", "message": "Success", "short_url": short_url}
    else:
        log_error(f"  Upload FAILED")
        return {"status": "error", "message": "Upload failed", "short_url": None}


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
            access_token=access_token,
            source_video_url=short.get('source_video_url'),
            source_title=short.get('source_title'),
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
                short_url=short_url,
                duration_sec=short.get('duration_sec', 0),
                start_sec=short.get('start_sec', 0),
                end_sec=short.get('end_sec', 0),
                method=short.get('method', ''),
                score=short.get('score', 0),
                reason=short.get('reason', ''),
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

    await run_job(job_id, job_request, JOBS)

    result = JOBS[job_id]

    if result.status != "done":
        log_error(f"    Job failed: {result.message}")
        # 失敗時もデバッグログを保存
        transcript_text = ""
        if result.artifacts.transcript_json:
            transcript_text = "\n".join(
                f"[{seg.start:.1f}s] {seg.text}"
                for seg in result.artifacts.transcript_json
            )
        _save_debug_log(
            youtuber_name=youtuber.name,
            video_id=video_info.video_id,
            transcript=transcript_text or f"(Job failed: {result.message})",
            segments=result.artifacts.segments or [],
            candidates=[],
        )
        return []

    log_info(f"    Clips generated: {len(result.outputs)}")

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

        # artifactsのsegmentsからスコア、理由、メソッドを取得
        method = "unknown"
        for seg in result.artifacts.segments:
            if abs(seg.start - segment_start) < 1.0 and abs(seg.end - segment_end) < 1.0:
                score = seg.score
                reason = seg.reason or ""
                method = seg.method or "unknown"
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
            'source_video_url': video_url,
            'source_title': video_info.title,
            'file_path': str(video_path.resolve()),
            'title': content["title"],
            'description': content["description"],
            'score': score,
            'reason': reason,
            'method': method,
            'start_sec': segment_start,
            'end_sec': segment_end,
            'duration_sec': segment_end - segment_start,
        })

    # スコア順にソート
    shorts_candidates.sort(key=lambda x: x['score'], reverse=True)

    log_info(f"    Candidates (sorted by score):")
    for i, s in enumerate(shorts_candidates):
        mark = "*" if s['score'] >= SCORE_THRESHOLD else " "
        log_info(f"      {mark} {i+1}. [{s['score']:.2f}] {s['title'][:35]}...")

    # デバッグログを保存
    transcript_text = ""
    if result.artifacts.transcript_json:
        transcript_text = "\n".join(
            f"[{seg.start:.1f}s] {seg.text}"
            for seg in result.artifacts.transcript_json
        )
    _save_debug_log(
        youtuber_name=youtuber.name,
        video_id=video_info.video_id,
        transcript=transcript_text,
        segments=result.artifacts.segments,
        candidates=shorts_candidates,
    )

    return shorts_candidates


async def upload_short(
    video_path: str,
    title: str,
    description: str,
    access_token: str,
    source_video_url: str | None = None,
    source_title: str | None = None,
    hashtags: list[str] | None = None,
    schedule_publish: bool = True,
) -> str | None:
    """
    ショート動画をYouTubeにアップロード（18時に予約投稿）

    Args:
        video_path: 動画ファイルパス
        title: タイトル
        description: 説明文（カスタムテキスト部分）
        access_token: アクセストークン
        source_video_url: 元動画のURL（説明欄に追加）
        source_title: 元動画のタイトル
        hashtags: カスタムハッシュタグ
        schedule_publish: 18時に予約投稿するか（デフォルトTrue）

    Returns:
        アップロードされた動画のURL
    """
    from app.youtube_upload import build_description, get_next_publish_time, upload_video

    try:
        # 説明文を構築（元動画リンク＋ハッシュタグ）
        full_description = build_description(
            source_video_url=source_video_url,
            source_title=source_title,
            hashtags=hashtags,
            custom_text=description,
        )

        # 予約投稿時刻を取得（18時JST）
        publish_at = get_next_publish_time() if schedule_publish else None

        video_id = upload_video(
            video_path=video_path,
            title=title,
            description=full_description,
            access_token=access_token,
            privacy_status="public",
            is_short=True,
            publish_at=publish_at,
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
