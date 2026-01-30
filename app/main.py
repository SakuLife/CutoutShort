"""FastAPI メインアプリケーション"""
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.config import config
from app.logging_utils import log_error, log_info, log_warning, set_trace_id
from app.models import (
    CreateJobRequest,
    CreateJobResponse,
    HealthResponse,
    Job,
    JobArtifacts,
    JobStatusResponse,
    RetryJobRequest,
    VersionResponse,
)
from app.worker import run_job

# FastAPIアプリケーション
app = FastAPI(
    title="Auto Shorts API",
    description="全自動ショート動画生成API（Make連携）",
    version=config.VERSION
)

# ジョブストア（インメモリ）
# 本番環境ではRedis/Firestoreを推奨
JOBS: dict[str, Job] = {}

# 冪等キーマップ（idempotency_key -> job_id）
IDEMPOTENCY_MAP: dict[str, str] = {}

# セマフォ（並列実行数制限）
JOB_SEMAPHORE = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)


def verify_api_key(x_api_key: str = Header(...)) -> None:
    """API キー認証"""
    if x_api_key != config.MAKE_SHARED_SECRET:
        log_warning("Invalid API key attempt")
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.on_event("startup")
async def startup_event():
    """起動時の処理"""
    log_info("Application starting", meta={"version": config.VERSION, "git": config.GIT_SHA})

    # 設定のバリデーション
    errors = config.validate()
    if errors:
        log_error("Configuration validation failed", meta={"errors": errors})
        # 起動は続行するが警告
        for error in errors:
            log_warning(f"Config error: {error}")


@app.on_event("shutdown")
async def shutdown_event():
    """シャットダウン時の処理"""
    log_info("Application shutting down")


@app.get("/healthz", response_model=HealthResponse, tags=["Health"])
async def healthz():
    """ヘルスチェック"""
    return HealthResponse(
        ok=True,
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@app.get("/version", response_model=VersionResponse, tags=["Health"])
async def version():
    """バージョン情報"""
    return VersionResponse(
        version=config.VERSION,
        git=config.GIT_SHA
    )


@app.post("/jobs", response_model=CreateJobResponse, status_code=201, tags=["Jobs"])
async def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(..., alias="X-API-KEY")
):
    """ジョブを作成"""
    # API キー認証
    verify_api_key(x_api_key)

    # 冪等キーチェック
    if request.idempotency_key:
        existing_job_id = IDEMPOTENCY_MAP.get(request.idempotency_key)
        if existing_job_id:
            log_info(
                "Idempotency key match, returning existing job",
                meta={"idempotency_key": request.idempotency_key, "job_id": existing_job_id}
            )
            return CreateJobResponse(
                job_id=existing_job_id,
                status=JOBS[existing_job_id].status
            )

    # ジョブIDとトレースIDを生成
    job_id = str(uuid.uuid4())
    trace_id = set_trace_id(f"trace-{job_id[:12]}")

    log_info(
        "Creating job",
        job_id=job_id,
        meta={
            "source_type": request.source_type,
            "target_count": request.options.target_count
        }
    )

    # ジョブを作成
    job = Job(
        job_id=job_id,
        status="queued",
        progress=0.0,
        message="Job queued",
        inputs=request,
        artifacts=JobArtifacts(),
        outputs=[],
        trace_id=trace_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        attempt=1
    )

    JOBS[job_id] = job

    # 冪等キーを記録
    if request.idempotency_key:
        IDEMPOTENCY_MAP[request.idempotency_key] = job_id

    # バックグラウンドタスクとしてジョブを実行
    background_tasks.add_task(_run_job_with_semaphore, job_id, request)

    return CreateJobResponse(
        job_id=job_id,
        status="queued"
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(
    job_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY")
):
    """ジョブの状態を取得"""
    # API キー認証
    verify_api_key(x_api_key)

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job.to_response()


@app.post("/jobs/{job_id}/retry", response_model=CreateJobResponse, tags=["Jobs"])
async def retry_job(
    job_id: str,
    request: RetryJobRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(..., alias="X-API-KEY")
):
    """ジョブをリトライ"""
    # API キー認証
    verify_api_key(x_api_key)

    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "error":
        raise HTTPException(status_code=400, detail="Job is not in error state")

    log_info("Retrying job", job_id=job_id)

    # オプションを上書き
    if request.options:
        job.inputs.options = request.options

    # ジョブをリセット
    job.status = "queued"
    job.progress = 0.0
    job.message = "Job queued for retry"
    job.attempt += 1
    job.updated_at = datetime.utcnow()
    JOBS[job_id] = job

    # バックグラウンドタスクとしてジョブを実行
    background_tasks.add_task(_run_job_with_semaphore, job_id, job.inputs)

    return CreateJobResponse(
        job_id=job_id,
        status="queued"
    )


async def _run_job_with_semaphore(job_id: str, job_request: CreateJobRequest):
    """セマフォ付きでジョブを実行"""
    async with JOB_SEMAPHORE:
        log_info(
            f"Job acquired semaphore (concurrent: {config.MAX_CONCURRENT_JOBS - JOB_SEMAPHORE._value})",
            job_id=job_id
        )

        try:
            await run_job(job_id, job_request, JOBS)
        except Exception as e:
            log_error(f"Job execution failed: {e}", job_id=job_id, exc_info=True)
        finally:
            log_info("Job released semaphore", job_id=job_id)


@app.get("/download/{filename}", tags=["Files"])
async def download_file(
    filename: str,
    x_api_key: str = Header(..., alias="X-API-KEY")
):
    """生成された動画ファイルをダウンロード"""
    # API キー認証
    verify_api_key(x_api_key)

    # ファイルパスを構築
    file_path = Path(config.TMP_DIR) / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    log_info(f"Serving file: {filename}")

    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=filename
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """グローバル例外ハンドラ"""
    log_error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# アプリケーションのエントリポイント
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
