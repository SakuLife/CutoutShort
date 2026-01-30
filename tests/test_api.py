"""APIエンドポイントのテスト"""
from unittest.mock import patch

import pytest


class TestHealthEndpoints:
    """ヘルスチェックエンドポイントのテスト"""

    def test_healthz(self, api_client):
        """GET /healthz"""
        response = api_client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "timestamp" in data

    def test_version(self, api_client):
        """GET /version"""
        response = api_client.get("/version")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "git" in data


class TestJobCreation:
    """ジョブ作成エンドポイントのテスト"""

    def test_create_job_missing_api_key(self, api_client):
        """API キーなしでリクエストした場合"""
        response = api_client.post(
            "/jobs",
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id",
                "title_hint": "テスト動画"
            }
        )
        assert response.status_code == 422  # Validation error (missing header)

    def test_create_job_invalid_api_key(self, api_client):
        """無効なAPI キーでリクエストした場合"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "invalid_key"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id",
                "title_hint": "テスト動画"
            }
        )
        assert response.status_code == 401

    @patch('app.main.run_job')
    def test_create_job_drive_source(self, mock_run_job, api_client):
        """Driveソースでジョブを作成"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id_123",
                "title_hint": "テスト動画",
                "options": {
                    "target_count": 3,
                    "min_sec": 25,
                    "max_sec": 45
                }
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    @patch('app.main.run_job')
    def test_create_job_youtube_source(self, mock_run_job, api_client):
        """YouTubeソースでジョブを作成"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "youtube_url",
                "youtube_url": "https://www.youtube.com/watch?v=test123",
                "title_hint": "YouTube動画",
                "options": {
                    "target_count": 5
                }
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    def test_create_job_missing_drive_file_id(self, api_client):
        """drive_file_idが指定されていない場合"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "title_hint": "テスト動画"
            }
        )

        assert response.status_code == 422  # Validation error

    def test_create_job_missing_youtube_url(self, api_client):
        """youtube_urlが指定されていない場合"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "youtube_url",
                "title_hint": "YouTube動画"
            }
        )

        assert response.status_code == 422  # Validation error

    @patch('app.main.run_job')
    def test_create_job_with_idempotency_key(self, mock_run_job, api_client):
        """冪等キーを使用してジョブを作成"""
        idempotency_key = "unique_key_123"

        # 1回目のリクエスト
        response1 = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id",
                "idempotency_key": idempotency_key
            }
        )

        assert response1.status_code == 201
        job_id1 = response1.json()["job_id"]

        # 2回目のリクエスト（同じ冪等キー）
        response2 = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id",
                "idempotency_key": idempotency_key
            }
        )

        assert response2.status_code == 201
        job_id2 = response2.json()["job_id"]

        # 同じジョブIDが返される
        assert job_id1 == job_id2

    @patch('app.main.run_job')
    def test_create_job_with_dry_run(self, mock_run_job, api_client):
        """dry_runオプションでジョブを作成"""
        response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id",
                "options": {
                    "dry_run": True,
                    "target_count": 3
                }
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data


class TestJobStatus:
    """ジョブステータスエンドポイントのテスト"""

    def test_get_job_status_not_found(self, api_client):
        """存在しないジョブのステータスを取得"""
        response = api_client.get(
            "/jobs/nonexistent_job_id",
            headers={"X-API-KEY": "test_secret"}
        )
        assert response.status_code == 404

    @patch('app.main.run_job')
    def test_get_job_status_queued(self, mock_run_job, api_client):
        """queuedステータスのジョブを取得"""
        # ジョブを作成
        create_response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id"
            }
        )
        job_id = create_response.json()["job_id"]

        # ステータスを取得
        status_response = api_client.get(
            f"/jobs/{job_id}",
            headers={"X-API-KEY": "test_secret"}
        )

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["job_id"] == job_id
        valid_statuses = [
            "queued", "downloading", "transcribing",
            "cut_selecting", "rendering", "uploading", "done",
        ]
        assert data["status"] in valid_statuses
        assert "progress" in data
        assert "trace_id" in data

    def test_get_job_status_missing_api_key(self, api_client):
        """API キーなしでステータスを取得"""
        response = api_client.get("/jobs/some_job_id")
        assert response.status_code == 422  # Missing header


class TestJobRetry:
    """ジョブリトライエンドポイントのテスト"""

    def test_retry_job_not_found(self, api_client):
        """存在しないジョブをリトライ"""
        response = api_client.post(
            "/jobs/nonexistent_job_id/retry",
            headers={"X-API-KEY": "test_secret"},
            json={}
        )
        assert response.status_code == 404

    @patch('app.main.run_job')
    def test_retry_job_not_in_error_state(self, mock_run_job, api_client):
        """エラー状態でないジョブをリトライ"""
        # ジョブを作成（queuedまたはdownloading状態）
        create_response = api_client.post(
            "/jobs",
            headers={"X-API-KEY": "test_secret"},
            json={
                "source_type": "drive",
                "drive_file_id": "test_file_id"
            }
        )
        job_id = create_response.json()["job_id"]

        # すぐにリトライしようとする（まだエラーでない）
        retry_response = api_client.post(
            f"/jobs/{job_id}/retry",
            headers={"X-API-KEY": "test_secret"},
            json={}
        )

        # エラー状態でないのでリトライできない
        assert retry_response.status_code == 400

    def test_retry_job_with_options(self, api_client):
        """オプションを指定してリトライ（モック）"""
        # この場合は実際にエラー状態のジョブを作る必要があるため、
        # 実際にはJOBSストアを直接操作するか、
        # 完全な統合テストで実施する
        pass


class TestConcurrentJobs:
    """同時実行制限のテスト"""

    @pytest.mark.asyncio
    @patch('app.main.run_job')
    async def test_concurrent_job_limit(self, mock_run_job, api_client):
        """同時実行数の制限をテスト"""
        import asyncio

        # ジョブを複数作成
        job_ids = []
        for i in range(5):
            response = api_client.post(
                "/jobs",
                headers={"X-API-KEY": "test_secret"},
                json={
                    "source_type": "drive",
                    "drive_file_id": f"test_file_id_{i}"
                }
            )
            assert response.status_code == 201
            job_ids.append(response.json()["job_id"])

        # 少し待ってからステータスを確認
        await asyncio.sleep(0.1)

        # セマフォが機能しているか確認（詳細な検証は統合テストで）
        for job_id in job_ids:
            response = api_client.get(
                f"/jobs/{job_id}",
                headers={"X-API-KEY": "test_secret"}
            )
            assert response.status_code == 200
