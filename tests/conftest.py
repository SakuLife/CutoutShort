"""pytest設定とフィクスチャ"""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """テストデータディレクトリ"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    """一時ディレクトリ"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_env_vars(monkeypatch):
    """環境変数と config オブジェクトのモック"""
    monkeypatch.setenv("MAKE_SHARED_SECRET", "test_secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "./test-sa.json")
    monkeypatch.setenv("DRIVE_INPUT_FOLDER_ID", "test_input_folder")
    monkeypatch.setenv("DRIVE_READY_FOLDER_ID", "test_ready_folder")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("TMP_DIR", tempfile.gettempdir())

    # config はクラス属性でインポート時に評価されるため、直接パッチする
    from app.config import config
    monkeypatch.setattr(config, "MAKE_SHARED_SECRET", "test_secret")
    monkeypatch.setattr(config, "GOOGLE_APPLICATION_CREDENTIALS", "./test-sa.json")
    monkeypatch.setattr(config, "DRIVE_INPUT_FOLDER_ID", "test_input_folder")
    monkeypatch.setattr(config, "DRIVE_READY_FOLDER_ID", "test_ready_folder")
    monkeypatch.setattr(config, "WHISPER_MODEL", "tiny")
    monkeypatch.setattr(config, "MAX_CONCURRENT_JOBS", 1)
    monkeypatch.setattr(config, "TMP_DIR", tempfile.gettempdir())


@pytest.fixture
def api_client(mock_env_vars):
    """FastAPIテストクライアント"""
    from app.main import IDEMPOTENCY_MAP, JOBS, app

    # テスト間のジョブストアをクリア
    JOBS.clear()
    IDEMPOTENCY_MAP.clear()
    return TestClient(app)


@pytest.fixture
def sample_transcript():
    """サンプル文字起こしデータ"""
    from app.models import TranscriptSegment
    return [
        TranscriptSegment(start=0.0, end=5.0, text="こんにちは、今日は動画編集について説明します。"),
        TranscriptSegment(start=5.0, end=12.0, text="まず最初に、ショート動画の重要性についてお話しします。"),
        TranscriptSegment(
            start=12.0, end=20.0, text="ショート動画は視聴者の注意を引きやすく、拡散されやすいという特徴があります。"
        ),
        TranscriptSegment(start=20.0, end=28.0, text="次に、効果的なショート動画の作り方を3つのポイントで解説します。"),
        TranscriptSegment(start=28.0, end=35.0, text="1つ目は、最初の3秒でフックを作ることです。"),
        TranscriptSegment(start=35.0, end=42.0, text="2つ目は、簡潔でわかりやすい内容にすることです。"),
        TranscriptSegment(start=42.0, end=50.0, text="3つ目は、強いCTAで締めくくることです。"),
        TranscriptSegment(start=50.0, end=58.0, text="これらのポイントを意識すれば、効果的なショート動画が作れます。"),
        TranscriptSegment(start=58.0, end=65.0, text="最後に、実際の事例を見てみましょう。"),
        TranscriptSegment(
            start=65.0, end=75.0, text="この動画では再生回数が100万回を超えました。その理由を分析してみます。"
        ),
    ]


@pytest.fixture
def sample_segments():
    """サンプルセグメント情報"""
    from app.models import SegmentInfo
    return [
        SegmentInfo(start=5.0, end=35.0, score=0.85, method="llm", reason="3つのポイント解説"),
        SegmentInfo(start=35.0, end=65.0, score=0.80, method="llm", reason="具体的なテクニック"),
        SegmentInfo(start=20.0, end=50.0, score=0.75, method="rule", reason="規則ベース抽出"),
    ]
