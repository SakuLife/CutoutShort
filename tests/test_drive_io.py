"""drive_io.pyのユニットテスト"""
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.drive_io import DriveIOError, _get_drive_service, download_from_drive, list_files_in_folder, upload_to_drive


class TestGetDriveService:
    """_get_drive_service関数のテスト"""

    @patch('app.drive_io.config')
    def test_credentials_not_set(self, mock_config):
        """認証情報が設定されていない場合"""
        mock_config.GOOGLE_APPLICATION_CREDENTIALS = None
        with pytest.raises(DriveIOError, match="GOOGLE_APPLICATION_CREDENTIALS"):
            _get_drive_service()

    @patch('app.drive_io.service_account.Credentials')
    @patch('app.drive_io.build')
    @patch('app.drive_io.config')
    def test_service_creation_success(self, mock_config, mock_build, mock_credentials):
        """サービスの作成が成功する場合"""
        mock_config.GOOGLE_APPLICATION_CREDENTIALS = "./test-sa.json"
        mock_creds = Mock()
        mock_credentials.from_service_account_file.return_value = mock_creds
        mock_build.return_value = Mock()

        service = _get_drive_service()
        assert service is not None
        mock_credentials.from_service_account_file.assert_called_once()


class TestDownloadFromDrive:
    """download_from_drive関数のテスト"""

    @patch('app.drive_io._get_drive_service')
    @patch('app.drive_io.MediaIoBaseDownload')
    def test_download_success(self, mock_downloader_class, mock_get_service, temp_dir):
        """ダウンロードが成功する場合"""
        # Driveサービスのモック
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        # ファイルメタデータ
        mock_service.files().get().execute.return_value = {
            "name": "test_video.mp4",
            "mimeType": "video/mp4",
            "size": "1024000"
        }

        # ダウンロード進捗のモック
        mock_downloader = MagicMock()
        mock_status = Mock()
        mock_status.progress.return_value = 0.5
        mock_downloader.next_chunk.side_effect = [
            (mock_status, False),
            (mock_status, True)  # 完了
        ]
        mock_downloader_class.return_value = mock_downloader

        output_path = temp_dir / "downloaded.mp4"
        result = download_from_drive(
            file_id="test_file_id",
            output_path=str(output_path),
            job_id="test_job"
        )

        assert result == str(output_path)

    @patch('app.drive_io._get_drive_service')
    def test_download_failure_with_retry(self, mock_get_service, temp_dir):
        """ダウンロードが失敗してリトライする場合"""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        # 全ての試行で失敗
        mock_service.files().get().execute.side_effect = Exception("Download error")

        output_path = temp_dir / "failed.mp4"

        with pytest.raises(DriveIOError, match="Failed to download"):
            download_from_drive(
                file_id="test_file_id",
                output_path=str(output_path),
                job_id="test_job"
            )


class TestUploadToDrive:
    """upload_to_drive関数のテスト"""

    @patch('app.drive_io._get_drive_service')
    @patch('app.drive_io.MediaFileUpload')
    def test_upload_success(self, mock_media_upload, mock_get_service, temp_dir):
        """アップロードが成功する場合"""
        # テストファイルを作成
        test_file = temp_dir / "test_upload.mp4"
        test_file.write_text("test content")

        # Driveサービスのモック
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        # アップロード成功のレスポンス
        mock_service.files().create().execute.return_value = {
            "id": "uploaded_file_id",
            "name": "test_upload.mp4",
            "webViewLink": "https://drive.google.com/file/d/uploaded_file_id/view"
        }

        # 共有設定の成功
        mock_service.permissions().create().execute.return_value = {}

        result = upload_to_drive(
            local_path=str(test_file),
            folder_id="test_folder_id",
            job_id="test_job"
        )

        assert "drive.google.com" in result
        assert "uploaded_file_id" in result

    @patch('app.drive_io._get_drive_service')
    def test_upload_failure_with_retry(self, mock_get_service, temp_dir):
        """アップロードが失敗してリトライする場合"""
        # テストファイルを作成
        test_file = temp_dir / "test_fail.mp4"
        test_file.write_text("test content")

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        # 全ての試行で失敗
        mock_service.files().create().execute.side_effect = Exception("Upload error")

        with pytest.raises(DriveIOError, match="Failed to upload"):
            upload_to_drive(
                local_path=str(test_file),
                folder_id="test_folder_id",
                job_id="test_job"
            )

    @patch('app.drive_io._get_drive_service')
    @patch('app.drive_io.MediaFileUpload')
    def test_upload_sharing_failure(self, mock_media_upload, mock_get_service, temp_dir):
        """アップロードは成功するが共有設定が失敗する場合"""
        # テストファイルを作成
        test_file = temp_dir / "test_share_fail.mp4"
        test_file.write_text("test content")

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        # アップロードは成功
        mock_service.files().create().execute.return_value = {
            "id": "uploaded_file_id",
            "name": "test_share_fail.mp4",
            "webViewLink": "https://drive.google.com/file/d/uploaded_file_id/view"
        }

        # 共有設定は失敗（でも処理は続行）
        mock_service.permissions().create().execute.side_effect = Exception("Sharing error")

        # 共有失敗でも結果は返る
        result = upload_to_drive(
            local_path=str(test_file),
            folder_id="test_folder_id",
            job_id="test_job"
        )

        assert "drive.google.com" in result


class TestListFilesInFolder:
    """list_files_in_folder関数のテスト"""

    @patch('app.drive_io._get_drive_service')
    def test_list_files_success(self, mock_get_service):
        """ファイル一覧取得が成功する場合"""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.files().list().execute.return_value = {
            "files": [
                {"id": "file1", "name": "video1.mp4", "mimeType": "video/mp4", "createdTime": "2024-01-01T00:00:00Z"},
                {"id": "file2", "name": "video2.mp4", "mimeType": "video/mp4", "createdTime": "2024-01-02T00:00:00Z"}
            ]
        }

        files = list_files_in_folder(folder_id="test_folder_id", job_id="test_job")

        assert len(files) == 2
        assert files[0]["name"] == "video1.mp4"
        assert files[1]["name"] == "video2.mp4"

    @patch('app.drive_io._get_drive_service')
    def test_list_files_failure(self, mock_get_service):
        """ファイル一覧取得が失敗する場合"""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.files().list().execute.side_effect = Exception("List error")

        files = list_files_in_folder(folder_id="test_folder_id", job_id="test_job")

        # エラーでも空のリストを返す
        assert files == []


class TestDriveIOIntegration:
    """統合テスト（実際のGoogle Drive接続が必要）"""

    @pytest.mark.skip(reason="実際のGoogle Drive認証情報が必要")
    def test_real_download_upload_cycle(self, temp_dir):
        """実際のDrive接続でダウンロード→アップロードサイクルをテスト"""
        # 実際のファイルIDとフォルダIDが必要
        test_file_id = "ACTUAL_FILE_ID"
        test_folder_id = "ACTUAL_FOLDER_ID"

        # ダウンロード
        download_path = temp_dir / "downloaded.mp4"
        download_from_drive(
            file_id=test_file_id,
            output_path=str(download_path),
            job_id="integration_test"
        )

        assert download_path.exists()

        # アップロード
        upload_link = upload_to_drive(
            local_path=str(download_path),
            folder_id=test_folder_id,
            job_id="integration_test"
        )

        assert "drive.google.com" in upload_link
