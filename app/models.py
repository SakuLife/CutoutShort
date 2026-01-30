"""Pydanticデータモデル定義"""
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ========== リクエストモデル ==========

class JobOptions(BaseModel):
    """ジョブオプション"""
    target_count: int = Field(default=5, ge=1, le=8, description="生成する動画の本数（1〜8）")
    min_sec: int = Field(default=25, ge=10, le=60, description="最小秒数")
    max_sec: int = Field(default=45, ge=20, le=90, description="最大秒数")
    render_preset: str = Field(default="v1", description="レンダリングプリセット名")
    subtitle_style: str = Field(default="default", description="字幕スタイル名")
    dry_run: bool = Field(default=False, description="ドライラン（DL/解析のみ、書き出し/UL省略）")
    force_rule_based: bool = Field(default=False, description="LLMをスキップして規則ベースのみ使用")

    @field_validator("max_sec")
    @classmethod
    def validate_max_sec(cls, v: int, info) -> int:
        """max_secがmin_secより大きいことを確認"""
        if "min_sec" in info.data and v <= info.data["min_sec"]:
            raise ValueError("max_sec must be greater than min_sec")
        return v


class CreateJobRequest(BaseModel):
    """ジョブ作成リクエスト"""
    source_type: Literal["drive", "youtube_url"] = Field(description="入力ソースタイプ")
    drive_file_id: str | None = Field(default=None, description="Driveファイル ID（source_type=driveの場合必須）")
    youtube_url: str | None = Field(default=None, description="YouTube URL（source_type=youtube_urlの場合必須）")
    title_hint: str | None = Field(default=None, description="動画タイトルヒント")
    options: JobOptions = Field(default_factory=JobOptions, description="ジョブオプション")
    idempotency_key: str | None = Field(default=None, description="冪等キー（同一キーは同一ジョブ扱い）")

    @model_validator(mode="after")
    def validate_source_fields(self) -> "CreateJobRequest":
        """source_typeに応じた必須フィールドを検証"""
        if self.source_type == "drive" and not self.drive_file_id:
            raise ValueError("drive_file_id is required when source_type is 'drive'")
        if self.source_type == "youtube_url" and not self.youtube_url:
            raise ValueError("youtube_url is required when source_type is 'youtube_url'")
        return self


class RetryJobRequest(BaseModel):
    """ジョブリトライリクエスト"""
    options: JobOptions | None = Field(default=None, description="上書きするオプション")


# ========== レスポンスモデル ==========

class CreateJobResponse(BaseModel):
    """ジョブ作成レスポンス"""
    job_id: str = Field(description="ジョブID")
    status: str = Field(description="ジョブステータス")


class OutputInfo(BaseModel):
    """出力ファイル情報"""
    file_name: str = Field(description="ファイル名")
    drive_link: str = Field(description="Google Driveリンク")
    duration_sec: float = Field(description="動画の長さ（秒）")
    segment: dict[str, float] = Field(description="切り出し区間 {start, end}")
    method: Literal["llm", "rule"] = Field(description="抽出方法")


class JobStatusResponse(BaseModel):
    """ジョブステータスレスポンス"""
    job_id: str = Field(description="ジョブID")
    status: str = Field(description="ステータス")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="進捗率（0.0〜1.0）")
    message: str = Field(default="", description="メッセージ")
    outputs: list[OutputInfo] = Field(default_factory=list, description="出力ファイル一覧（done時のみ）")
    trace_id: str = Field(description="トレースID")


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンス"""
    ok: bool = Field(description="正常かどうか")
    timestamp: str = Field(description="タイムスタンプ")


class VersionResponse(BaseModel):
    """バージョン情報レスポンス"""
    version: str = Field(description="バージョン番号")
    git: str = Field(description="Gitコミットハッシュ")


# ========== 内部モデル ==========

class SegmentInfo(BaseModel):
    """切り出しセグメント情報"""
    start: float = Field(description="開始時刻（秒）")
    end: float = Field(description="終了時刻（秒）")
    score: float = Field(default=0.5, ge=0.0, le=1.0, description="スコア（0.0〜1.0）")
    method: Literal["llm", "rule"] = Field(description="抽出方法")
    reason: str | None = Field(default=None, description="選定理由")


class TranscriptSegment(BaseModel):
    """文字起こしセグメント"""
    start: float = Field(description="開始時刻（秒）")
    end: float = Field(description="終了時刻（秒）")
    text: str = Field(description="テキスト")


class JobArtifacts(BaseModel):
    """ジョブ中間成果物"""
    local_in: str | None = Field(default=None, description="ローカル入力ファイルパス")
    srt_path: str | None = Field(default=None, description="SRTファイルパス")
    transcript_json: list[TranscriptSegment] = Field(default_factory=list, description="文字起こしJSON")
    segments: list[SegmentInfo] = Field(default_factory=list, description="選定セグメント")
    rendered_files: list[str] = Field(default_factory=list, description="レンダリング済みファイルパス")
    drive_links: list[str] = Field(default_factory=list, description="アップロード済みDriveリンク")


class Job(BaseModel):
    """ジョブモデル（内部状態）"""
    job_id: str = Field(description="ジョブID")
    status: Literal[
        "queued",
        "downloading",
        "transcribing",
        "cut_selecting",
        "rendering",
        "uploading",
        "done",
        "error"
    ] = Field(default="queued", description="ジョブステータス")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="進捗率")
    message: str = Field(default="", description="メッセージ")
    inputs: CreateJobRequest = Field(description="入力パラメータ")
    artifacts: JobArtifacts = Field(default_factory=JobArtifacts, description="中間成果物")
    outputs: list[OutputInfo] = Field(default_factory=list, description="出力ファイル情報")
    trace_id: str = Field(description="トレースID")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="作成日時")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新日時")
    attempt: int = Field(default=1, ge=1, description="試行回数")

    class Config:
        json_encoders: ClassVar[dict] = {
            datetime: lambda v: v.isoformat()
        }

    def to_response(self) -> JobStatusResponse:
        """レスポンス形式に変換"""
        return JobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            progress=self.progress,
            message=self.message,
            outputs=self.outputs,
            trace_id=self.trace_id
        )
